import unittest
from app.config import settings
from app.ai.llm_client import LLMOrchestrator
from app.ai.embeddings import SemanticSearchEngine
from app.ai.schemas import AIAction
from app.speech.speechkit import YandexSpeechKitService

@unittest.skipUnless(settings.yandex_api_key and settings.yandex_folder_id, "Yandex credentials not configured")
class TestIntentRecognition(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orchestrator = LLMOrchestrator()

    async def asyncTearDown(self):
        await self.orchestrator.aclose()

    async def test_create_task_with_relative_date(self):
        res = await self.orchestrator.parse_intent("Напомни мне завтра в 10 утра позвонить Ивану")
        self.assertEqual(res.action, AIAction.CREATE_TASK)
        self.assertTrue(res.params.get("is_reminder"))
        self.assertIsNotNone(res.params.get("due_date"))
        self.assertEqual(res.params.get("due_time"), "10:00")

    async def test_create_meeting_with_time(self):
        res = await self.orchestrator.parse_intent("Добавь встречу с командой завтра в 15:00")
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertIn("Встреча", res.params.get("title", ""))
        self.assertEqual(res.params.get("start_time"), "15:00")

    async def test_meeting_with_exact_time_does_not_convert_to_pm(self):
        res = await self.orchestrator.parse_intent("встреча сегодня в 2:39")
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_time"), "02:39")

    async def test_heuristic_fallback_exact_time(self):
        self.orchestrator.yandex_api_key = None
        self.orchestrator.yandex_folder_id = None
        res = await self.orchestrator.parse_intent("встреча сегодня в 2:39")
        self.assertEqual(res.action, AIAction.UNKNOWN)

    async def test_meeting_clarification_dialog(self):
        step1 = await self.orchestrator.parse_intent("Поставь встречу с Иваном завтра")
        self.assertEqual(step1.action, AIAction.ASK_CLARIFICATION)
        self.assertEqual(step1.params.get("missing_slot"), "time")

        context = {
            "awaiting_slot": step1.params.get("missing_slot"),
            "draft_data": step1.params.get("draft_data")
        }
        step2 = await self.orchestrator.parse_intent("В 15:00", context=context)
        self.assertEqual(step2.action, AIAction.CREATE_MEETING)
        self.assertEqual(step2.params.get("start_time"), "15:00")

    def _get_tz_now_date(self):
        from zoneinfo import ZoneInfo
        import datetime
        tz_name = getattr(self.orchestrator, "_current_timezone", "Europe/Moscow")
        return datetime.datetime.now(ZoneInfo(tz_name)).date()

    async def test_clarification_with_today_and_custom_time(self):
        today_str = str(self._get_tz_now_date())
        context = {
            "awaiting_slot": "time",
            "draft_data": {"title": "Встреча с Кириллом"}
        }
        res = await self.orchestrator.parse_intent("На сегодня 2:30", context=context)
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_date"), today_str)
        self.assertEqual(res.params.get("start_time"), "02:30")

    async def test_clarification_date_slot_preserves_time(self):
        today_str = str(self._get_tz_now_date())
        context = {
            "awaiting_slot": "date",
            "draft_data": {"title": "Встреча", "start_time": "02:53"}
        }
        res = await self.orchestrator.parse_intent("сегодня", context=context)
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_date"), today_str)
        self.assertEqual(res.params.get("start_time"), "02:53")

    async def test_clarification_with_tomorrow_relative_date(self):
        import datetime
        tomorrow_str = str(self._get_tz_now_date() + datetime.timedelta(days=1))
        context = {
            "awaiting_slot": "time",
            "draft_data": {"title": "Встреча с Кириллом"}
        }
        res = await self.orchestrator.parse_intent("На завтра в 14:00", context=context)
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_date"), tomorrow_str)
        self.assertEqual(res.params.get("start_time"), "14:00")

    async def test_clarification_defaults_to_today_when_no_date_provided(self):
        today_str = str(self._get_tz_now_date())
        context = {
            "awaiting_slot": "time",
            "draft_data": {"title": "Встреча с Кириллом"}
        }
        res = await self.orchestrator.parse_intent("15:00", context=context)
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_date"), today_str)
        self.assertEqual(res.params.get("start_time"), "15:00")

    async def test_get_schedule(self):
        res_today = await self.orchestrator.parse_intent("Что у меня сегодня?")
        self.assertEqual(res_today.action, AIAction.GET_SCHEDULE)
        self.assertEqual(res_today.params.get("filter_type"), "all")

        res_meetings = await self.orchestrator.parse_intent("мои встречи")
        self.assertEqual(res_meetings.action, AIAction.GET_SCHEDULE)
        self.assertEqual(res_meetings.params.get("filter_type"), "meetings")

        res_week = await self.orchestrator.parse_intent("Что запланировано на эту неделю?")
        self.assertEqual(res_week.action, AIAction.GET_SCHEDULE)

    async def test_get_archive(self):
        from unittest.mock import AsyncMock
        from app.ai.schemas import AIResponse
        self.orchestrator._call_yandex_gpt = AsyncMock(side_effect=[
            AIResponse(action=AIAction.GET_ARCHIVE, params={"filter_type": "all"}),
            AIResponse(action=AIAction.GET_ARCHIVE, params={"filter_type": "meetings"}),
            AIResponse(action=AIAction.GET_ARCHIVE, params={"filter_type": "tasks"})
        ])

        res_all = await self.orchestrator.parse_intent("Покажи архив")
        self.assertEqual(res_all.action, AIAction.GET_ARCHIVE)
        self.assertEqual(res_all.params.get("filter_type"), "all")

        res_meetings = await self.orchestrator.parse_intent("Покажи старые встречи")
        self.assertEqual(res_meetings.action, AIAction.GET_ARCHIVE)
        self.assertEqual(res_meetings.params.get("filter_type"), "meetings")

        res_tasks = await self.orchestrator.parse_intent("Покажи выполненные задачи")
        self.assertEqual(res_tasks.action, AIAction.GET_ARCHIVE)
        self.assertEqual(res_tasks.params.get("filter_type"), "tasks")

    async def test_search_records(self):
        res = await self.orchestrator.parse_intent("Найди задачу про презентацию")
        self.assertEqual(res.action, AIAction.SEARCH_RECORDS)
        self.assertIn("презентаци", res.params.get("query", ""))

    async def test_multi_intent_parsing(self):
        from unittest.mock import AsyncMock
        from app.ai.schemas import AIResponse
        self.orchestrator._call_yandex_gpt = AsyncMock(return_value=AIResponse(
            action=AIAction.MULTI_ACTION,
            params={},
            sub_actions=[
                AIResponse(action=AIAction.CREATE_MEETING, params={"start_time": "14:00"}),
                AIResponse(action=AIAction.CREATE_TASK, params={"due_time": "18:00"})
            ]
        ))
        query = "Поставь встречу с Михаилом завтра в 14:00 и напомни купить кофе в 18:00"
        res = await self.orchestrator.parse_intent(query)
        self.assertEqual(res.action, AIAction.MULTI_ACTION)
        self.assertIsNotNone(res.sub_actions)
        self.assertEqual(len(res.sub_actions), 2)
        self.assertEqual(res.sub_actions[0].action, AIAction.CREATE_MEETING)
        self.assertEqual(res.sub_actions[0].params.get("start_time"), "14:00")
        self.assertEqual(res.sub_actions[1].action, AIAction.CREATE_TASK)
        self.assertEqual(res.sub_actions[1].params.get("due_time"), "18:00")

    async def test_create_recurring_task_daily(self):
        from unittest.mock import AsyncMock
        from app.ai.schemas import AIResponse
        self.orchestrator._call_yandex_gpt = AsyncMock(return_value=AIResponse(
            action=AIAction.CREATE_TASK,
            params={"title": "Пить витамины", "due_time": "09:00", "recurrence": "daily"}
        ))
        res = await self.orchestrator.parse_intent("Каждый день в 9:00 пить витамины")
        self.assertEqual(res.action, AIAction.CREATE_TASK)
        self.assertEqual(res.params.get("recurrence"), "daily")
        self.assertEqual(res.params.get("due_time"), "09:00")
        self.assertIn("витамины", res.params.get("title", "").lower())

    async def test_create_recurring_meeting_weekly(self):
        from unittest.mock import AsyncMock
        from app.ai.schemas import AIResponse
        self.orchestrator._call_yandex_gpt = AsyncMock(return_value=AIResponse(
            action=AIAction.CREATE_MEETING,
            params={"title": "Планерка с командой", "start_time": "10:00", "recurrence": "weekly:mon"}
        ))
        res = await self.orchestrator.parse_intent("По понедельникам в 10:00 планерка с командой")
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("recurrence"), "weekly:mon")
        self.assertEqual(res.params.get("start_time"), "10:00")
        self.assertIn("планерка", res.params.get("title", "").lower())

    async def test_create_recurring_task_weekdays(self):
        from unittest.mock import AsyncMock
        from app.ai.schemas import AIResponse
        self.orchestrator._call_yandex_gpt = AsyncMock(return_value=AIResponse(
            action=AIAction.CREATE_TASK,
            params={"title": "Зарядка", "due_time": "09:00", "recurrence": "weekdays"}
        ))
        res = await self.orchestrator.parse_intent("По будням в 9:00 зарядка")
        self.assertEqual(res.action, AIAction.CREATE_TASK)
        self.assertEqual(res.params.get("recurrence"), "weekdays")
        self.assertEqual(res.params.get("due_time"), "09:00")

    async def test_one_off_meeting_does_not_set_recurrence(self):
        from unittest.mock import AsyncMock
        from app.ai.schemas import AIResponse
        self.orchestrator._call_yandex_gpt = AsyncMock(return_value=AIResponse(
            action=AIAction.CREATE_MEETING,
            params={"title": "Встреча с дизайнером", "start_time": "10:00", "recurrence": None}
        ))
        res = await self.orchestrator.parse_intent("В понедельник в 10:00 встреча с дизайнером")
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertIsNone(res.params.get("recurrence"))

    async def test_dialogue_recurring_task_and_schedule(self):
        from app.orchestrator.dialogue import DialogueOrchestrator
        from app.storage.db import Database
        mem_db = Database(":memory:")
        orch = DialogueOrchestrator(llm=self.orchestrator, db=mem_db)

        reply1 = await orch.handle_text(100, "Каждый день в 9:00 пить витамины")
        self.assertIn("ежедневно", reply1.text)

        reply2 = await orch.handle_text(100, "Расписание")
        self.assertIn("ежедневно", reply2.text)
        self.assertIn("пить витамины", reply2.text.lower())

    def test_system_prompt_includes_timezone_and_calendar(self):
        from app.ai.prompts import get_system_prompt
        prompt_default = get_system_prompt()
        self.assertIn("Europe/Moscow", prompt_default)
        self.assertIn("КАЛЕНДАРНЫЙ КОНТЕКСТ", prompt_default)
        self.assertIn("Текущая неделя", prompt_default)
        self.assertIn("Следующая неделя", prompt_default)

        prompt_custom = get_system_prompt("Asia/Yekaterinburg")
        self.assertIn("Asia/Yekaterinburg", prompt_custom)


class TestSemanticSearch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = SemanticSearchEngine()

    async def asyncTearDown(self):
        await self.engine.aclose()

    async def test_local_similarity(self):
        records = [
            {"id": 1, "title": "Согласовать контракт с поставщиком", "type": "task"},
            {"id": 2, "title": "Подготовить отчет по продажам", "type": "task"},
            {"id": 3, "title": "Встреча с командой разработки", "type": "meeting"}
        ]
        results = self.engine.rank_records("договор", records, top_k=1)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], 1)

    async def test_tz_query_matching(self):
        records = [
            {"id": 1, "title": "Согласовать контракт с поставщиком", "type": "task"},
            {"id": 2, "title": "Купить продукты домой", "type": "task"},
            {"id": 3, "title": "Подготовить презентацию для демо", "type": "task"}
        ]
        from unittest.mock import AsyncMock
        from app.ai.schemas import AIResponse
        orch = LLMOrchestrator()
        orch.parse_intent = AsyncMock(return_value=AIResponse(
            action=AIAction.SEARCH_RECORDS,
            params={"record_type": "tasks", "query": "договору"}
        ))
        res = await orch.parse_intent("Я когда-то ставил задачу по договору, найди ее")
        await orch.aclose()
        self.assertEqual(res.action, AIAction.SEARCH_RECORDS)
        self.assertEqual(res.params.get("record_type"), "tasks")
        ranked = self.engine.rank_records(res.params.get("query"), records, top_k=1)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], 1)

    async def test_inflected_forms_search(self):
        records = [
            {"id": 1, "title": "Сделать презентацию со слайдами", "type": "task"},
            {"id": 2, "title": "Записаться к врачу", "type": "task"}
        ]
        ranked = self.engine.rank_records("слайды", records, top_k=1)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], 1)

        ranked2 = self.engine.rank_records("со слайдами", records, top_k=1)
        self.assertEqual(len(ranked2), 1)
        self.assertEqual(ranked2[0]["id"], 1)

    def test_clean_text_for_tts(self):
        raw = "📦 Расписание (*сегодня*):\n• [x] Купить молоко\n• [ ] Написать отчет (🔄 ежедневно) ✅"
        cleaned = YandexSpeechKitService.clean_text_for_tts(raw)
        self.assertNotIn("📦", cleaned)
        self.assertNotIn("✅", cleaned)
        self.assertNotIn("*", cleaned)
        self.assertNotIn("[x]", cleaned)
        self.assertNotIn("[ ]", cleaned)
        self.assertIn("Выполнено: Купить молоко", cleaned)
        self.assertIn("Задача: Написать отчет", cleaned)
        self.assertIn("повторяется ежедневно", cleaned)


@unittest.skipUnless(settings.yandex_api_key and settings.yandex_folder_id, "Yandex credentials not configured")
class TestYandexCloudLive(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.speech = YandexSpeechKitService()

    async def asyncTearDown(self):
        await self.speech.aclose()

    async def test_speechkit_roundtrip(self):
        audio = await self.speech.text_to_speech("Тест голосового ассистента")
        self.assertIsNotNone(audio)
        self.assertGreater(len(audio), 1000)

        text = await self.speech.speech_to_text(audio)
        self.assertIsNotNone(text)
        self.assertIn("тест", text.lower())

if __name__ == "__main__":
    unittest.main()

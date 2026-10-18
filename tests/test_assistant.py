import unittest
from app.config import settings
from app.ai.llm_client import LLMOrchestrator
from app.ai.embeddings import SemanticSearchEngine
from app.ai.schemas import AIAction
from app.speech.speechkit import YandexSpeechKitService

class TestIntentRecognition(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orchestrator = LLMOrchestrator()

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
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_time"), "02:39")

    async def test_meeting_clarification_dialog(self):
        # Step 1: no time specified -> triggers clarification
        step1 = await self.orchestrator.parse_intent("Поставь встречу с Иваном завтра")
        self.assertEqual(step1.action, AIAction.ASK_CLARIFICATION)
        self.assertEqual(step1.params.get("missing_slot"), "time")
        
        # Step 2: user provides missing time
        context = {
            "awaiting_slot": step1.params.get("missing_slot"),
            "draft_data": step1.params.get("draft_data")
        }
        step2 = await self.orchestrator.parse_intent("В 15:00", context=context)
        self.assertEqual(step2.action, AIAction.CREATE_MEETING)
        self.assertEqual(step2.params.get("start_time"), "15:00")

    async def test_clarification_with_today_and_custom_time(self):
        import datetime
        today_str = str(datetime.datetime.now().date())
        context = {
            "awaiting_slot": "time",
            "draft_data": {"title": "Встреча с Кириллом"}
        }
        res = await self.orchestrator.parse_intent("На сегодня 2:30", context=context)
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_date"), today_str)
        self.assertEqual(res.params.get("start_time"), "02:30")

    async def test_clarification_date_slot_preserves_time(self):
        import datetime
        today_str = str(datetime.datetime.now().date())
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
        tomorrow_str = str(datetime.datetime.now().date() + datetime.timedelta(days=1))
        context = {
            "awaiting_slot": "time",
            "draft_data": {"title": "Встреча с Кириллом"}
        }
        res = await self.orchestrator.parse_intent("На завтра в 14:00", context=context)
        self.assertEqual(res.action, AIAction.CREATE_MEETING)
        self.assertEqual(res.params.get("start_date"), tomorrow_str)
        self.assertEqual(res.params.get("start_time"), "14:00")

    async def test_clarification_defaults_to_today_when_no_date_provided(self):
        import datetime
        today_str = str(datetime.datetime.now().date())
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

    async def test_search_records(self):
        res = await self.orchestrator.parse_intent("Найди задачу про презентацию")
        self.assertEqual(res.action, AIAction.SEARCH_RECORDS)
        self.assertIn("презентаци", res.params.get("query", ""))

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

    async def test_local_similarity(self):
        records = [
            {"id": 1, "title": "Согласовать контракт с поставщиком", "type": "task"},
            {"id": 2, "title": "Подготовить отчет по продажам", "type": "task"},
            {"id": 3, "title": "Встреча с командой разработки", "type": "meeting"}
        ]
        results = self.engine.rank_records("договор", records, top_k=1)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], 1)


@unittest.skipUnless(settings.yandex_api_key and settings.yandex_folder_id, "Yandex credentials not configured")
class TestYandexCloudLive(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.speech = YandexSpeechKitService()

    async def test_speechkit_roundtrip(self):
        audio = await self.speech.text_to_speech("Тест голосового ассистента")
        self.assertIsNotNone(audio)
        self.assertGreater(len(audio), 1000)

        text = await self.speech.speech_to_text(audio)
        self.assertIsNotNone(text)
        self.assertIn("тест", text.lower())

if __name__ == "__main__":
    unittest.main()

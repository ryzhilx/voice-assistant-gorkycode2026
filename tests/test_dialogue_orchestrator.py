import datetime
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.ai.schemas import AIAction, AIResponse
from app.ai.llm_client import LLMOrchestrator
from app.orchestrator.dialogue import DEFAULT_QUESTION, DialogueOrchestrator
from app.storage.db import Database

CHAT = 1
DRAFT = {"title": "Встреча с Иваном", "start_date": "2026-10-18"}

def clarification(question="На какое время поставить встречу?"):
    params = {"missing_slot": "time", "draft_data": dict(DRAFT)}
    if question:
        params["question"] = question
    return AIResponse(action=AIAction.ASK_CLARIFICATION, params=params)

class TestDialogueOrchestrator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.llm = MagicMock(parse_intent=AsyncMock())
        self.db = Database(":memory:")
        self.orch = DialogueOrchestrator(llm=self.llm, db=self.db)

    async def test_clarification_saves_draft_and_returns_question(self):
        self.llm.parse_intent.return_value = clarification()

        reply = await self.orch.handle_text(CHAT, "Поставь встречу с Иваном завтра")

        self.assertEqual(reply.text, "На какое время поставить встречу?")
        self.assertTrue(self.orch.has_pending(CHAT))
        self.llm.parse_intent.assert_awaited_once_with("Поставь встречу с Иваном завтра", None)

    async def test_answer_resumes_with_draft_and_clears_pending(self):
        self.llm.parse_intent.return_value = clarification()
        await self.orch.handle_text(CHAT, "Поставь встречу с Иваном завтра")

        self.llm.parse_intent.return_value = AIResponse(
            action=AIAction.CREATE_MEETING, params={**DRAFT, "start_time": "15:00"}
        )
        reply = await self.orch.handle_text(CHAT, "В 15:00")

        self.llm.parse_intent.assert_awaited_with("В 15:00", {"awaiting_slot": "time", "draft_data": DRAFT})
        self.assertFalse(self.orch.has_pending(CHAT))
        self.assertIn("Встреча", reply.text)
        self.assertIn("15:00", reply.text)

    async def test_repeated_clarification_keeps_pending(self):
        self.llm.parse_intent.return_value = clarification()
        await self.orch.handle_text(CHAT, "Поставь встречу с Иваном завтра")
        await self.orch.handle_text(CHAT, "не знаю")

        self.assertTrue(self.orch.has_pending(CHAT))

    async def test_plain_request_has_no_context(self):
        self.llm.parse_intent.return_value = AIResponse(action=AIAction.CREATE_TASK, params={"title": "Задача"})

        await self.orch.handle_text(CHAT, "Напомни купить хлеб")

        self.llm.parse_intent.assert_awaited_once_with("Напомни купить хлеб", None)
        self.assertFalse(self.orch.has_pending(CHAT))

    async def test_missing_question_uses_default(self):
        self.llm.parse_intent.return_value = clarification(question=None)

        reply = await self.orch.handle_text(CHAT, "Поставь встречу")

        self.assertEqual(reply.text, DEFAULT_QUESTION)

    async def test_reset_drops_pending(self):
        self.llm.parse_intent.return_value = clarification()
        await self.orch.handle_text(CHAT, "Поставь встречу с Иваном завтра")

        self.orch.reset(CHAT)

        self.assertFalse(self.orch.has_pending(CHAT))

    async def test_chats_are_isolated(self):
        self.llm.parse_intent.return_value = clarification()
        await self.orch.handle_text(1, "Поставь встречу с Иваном завтра")

        self.assertFalse(self.orch.has_pending(2))
        self.llm.parse_intent.return_value = AIResponse(action=AIAction.CREATE_TASK, params={})
        await self.orch.handle_text(2, "Напомни купить хлеб")

        self.llm.parse_intent.assert_awaited_with("Напомни купить хлеб", None)
        self.assertTrue(self.orch.has_pending(1))

    async def test_chat_intent(self):
        self.llm.parse_intent.return_value = AIResponse(
            action=AIAction.CHAT,
            params={"reply": "Привет! Чем могу помочь?"}
        )
        reply = await self.orch.handle_text(CHAT, "Привет")
        self.assertEqual(reply.text, "Привет! Чем могу помочь?")
        self.assertFalse(self.orch.has_pending(CHAT))

    async def test_cancel_drops_pending(self):
        self.llm.parse_intent.return_value = clarification()
        await self.orch.handle_text(CHAT, "Поставь встречу с Иваном завтра")
        self.assertTrue(self.orch.has_pending(CHAT))

        self.llm.parse_intent.return_value = AIResponse(
            action=AIAction.CHAT,
            params={"reply": "Действие отменено."}
        )
        reply = await self.orch.handle_text(CHAT, "Отмена")
        self.assertIn("отменено", reply.text)
        self.assertFalse(self.orch.has_pending(CHAT))

    async def test_schedule_without_date_defaults_to_today(self):
        self.llm.parse_intent.return_value = AIResponse(
            action=AIAction.GET_SCHEDULE,
            params={"filter_type": "all"}
        )
        reply = await self.orch.handle_text(CHAT, "Расписание")
        self.assertNotIn("None", reply.text)
        self.assertIn("сегодня", reply.text)

    async def test_schedule_meetings_filter_empty_message(self):
        self.llm.parse_intent.return_value = AIResponse(
            action=AIAction.GET_SCHEDULE,
            params={"filter_type": "meetings"}
        )
        reply = await self.orch.handle_text(CHAT, "Мои встречи")
        self.assertNotIn("None", reply.text)
        self.assertIn("нет запланированных встреч", reply.text)

    async def test_multi_action_executes_all_and_formats_reply(self):
        self.llm.parse_intent.return_value = AIResponse(
            action=AIAction.MULTI_ACTION,
            params={},
            sub_actions=[
                AIResponse(
                    action=AIAction.CREATE_MEETING,
                    params={"title": "Синхронизация", "start_date": "2026-10-19", "start_time": "14:00"}
                ),
                AIResponse(
                    action=AIAction.CREATE_TASK,
                    params={"title": "Купить чай", "due_date": "2026-10-18", "due_time": "18:00", "is_reminder": True}
                )
            ]
        )
        reply = await self.orch.handle_text(CHAT, "Поставь встречу и напомни купить чай")
        self.assertIn("1️⃣", reply.text)
        self.assertIn("2️⃣", reply.text)
        self.assertIn("Синхронизация", reply.text)
        self.assertIn("Купить чай", reply.text)

        sched = await self.db.get_schedule(CHAT, "2026-10-18", "2026-10-19")
        self.assertEqual(len(sched["meetings"]), 1)
        self.assertEqual(len(sched["tasks"]), 1)

    async def test_reschedule_dialogue_context(self):
        llm_mock = MagicMock(parse_intent=AsyncMock())
        llm_mock.parse_intent.side_effect = [
            AIResponse(action=AIAction.CREATE_MEETING, params={"title": "Встреча с Михаилом", "start_date": "2026-10-20", "start_time": "14:00"}),
            AIResponse(action=AIAction.RESCHEDULE_RECORD, params={"target": "last", "new_date": "2026-10-21"}),
            AIResponse(action=AIAction.RESCHEDULE_RECORD, params={"target": "last", "new_time": "16:30"})
        ]
        orch = DialogueOrchestrator(llm=llm_mock, db=self.db)

        r1 = await orch.handle_text(CHAT, "Добавь встречу с Михаилом завтра в 14:00")
        self.assertIn("Встреча", r1.text)
        self.assertIn("14:00", r1.text)

        r2 = await orch.handle_text(CHAT, "А перенеси ее на послезавтра")
        self.assertIn("перенесена", r2.text)
        self.assertIn("14:00", r2.text)

        r3 = await orch.handle_text(CHAT, "Перенеси ее на 16:30")
        self.assertIn("перенесена", r3.text)
        self.assertIn("16:30", r3.text)

        meetings = (await self.db.get_schedule(CHAT, "2020-01-01", "2030-01-01", filter_type="meetings"))["meetings"]
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0]["start_time"], "16:30")
        await orch.aclose()

    async def test_delete_update_complete_records(self):
        llm_mock = MagicMock(parse_intent=AsyncMock())
        llm_mock.parse_intent.side_effect = [
            AIResponse(action=AIAction.CREATE_TASK, params={"title": "Купить молоко"}),
            AIResponse(action=AIAction.UPDATE_RECORD, params={"target": "last", "new_title": "Купить миндальное молоко"}),
            AIResponse(action=AIAction.COMPLETE_RECORD, params={"target": "last"}),
            AIResponse(action=AIAction.DELETE_RECORD, params={"target": "last"}),
            AIResponse(action=AIAction.CREATE_MEETING, params={"title": "Встреча с дизайнером", "start_date": "2026-10-20", "start_time": "15:00"}),
            AIResponse(action=AIAction.DELETE_RECORD, params={"target": "meeting", "query": "дизайнером"})
        ]
        orch = DialogueOrchestrator(llm=llm_mock, db=self.db)

        r1 = await orch.handle_text(CHAT, "Поставь задачу купить молоко")
        self.assertIn("Задача добавлена", r1.text)

        r2 = await orch.handle_text(CHAT, "Переименуй задачу в Купить миндальное молоко")
        self.assertIn("переименована", r2.text)
        self.assertIn("Купить миндальное молоко", r2.text)

        r3 = await orch.handle_text(CHAT, "Отметь задачу выполненной")
        self.assertIn("отмечена как выполненная", r3.text)

        r4 = await orch.handle_text(CHAT, "Удали ее")
        self.assertIn("успешно удалена", r4.text)

        tasks = (await self.db.get_schedule(CHAT, "2020-01-01", "2030-01-01", filter_type="tasks"))["tasks"]
        self.assertEqual(len(tasks), 0)

        r5 = await orch.handle_text(CHAT, "Добавь встречу с дизайнером завтра в 15:00")
        self.assertIn("Встреча", r5.text)

        r6 = await orch.handle_text(CHAT, "Отмени встречу с дизайнером")
        self.assertIn("успешно отменена", r6.text)

        meetings = (await self.db.get_schedule(CHAT, "2020-01-01", "2030-01-01", filter_type="meetings"))["meetings"]
        self.assertEqual(len(meetings), 0)
        await orch.aclose()

    async def test_archive_view_and_filtering(self):
        empty_all = await self.orch.get_archive_view(CHAT)
        self.assertIn("Архив пуст", empty_all)

        empty_m = await self.orch.get_archive_view(CHAT, filter_type="meetings")
        self.assertIn("нет прошедших встреч", empty_m)

        empty_t = await self.orch.get_archive_view(CHAT, filter_type="tasks")
        self.assertIn("нет завершенных задач", empty_t)

        m_id = await self.db.add_meeting(CHAT, "Ретроспектива", "2026-10-10", "12:00")
        await self.db.archive_record(CHAT, "meeting", m_id)

        t_id = await self.db.add_task(CHAT, "Подготовить отчет", "2026-10-10", "18:00")
        await self.db.mark_task_completed(CHAT, t_id)

        view_all = await self.orch.get_archive_view(CHAT)
        self.assertIn("Ретроспектива", view_all)
        self.assertIn("Подготовить отчет", view_all)

        view_meetings = await self.orch.get_archive_view(CHAT, filter_type="meetings")
        self.assertIn("Ретроспектива", view_meetings)
        self.assertNotIn("Подготовить отчет", view_meetings)

        view_tasks = await self.orch.get_archive_view(CHAT, filter_type="tasks")
        self.assertIn("Подготовить отчет", view_tasks)
        self.assertNotIn("Ретроспектива", view_tasks)

    async def test_past_tense_action_reports_complete_tasks(self):
        today_str = str(datetime.datetime.now(ZoneInfo("Europe/Moscow")).date())
        llm_mock = MagicMock(parse_intent=AsyncMock())
        llm_mock.parse_intent.side_effect = [
            AIResponse(action=AIAction.COMPLETE_RECORD, params={"target": "task", "query": "пить воду"}),
            AIResponse(action=AIAction.COMPLETE_RECORD, params={"target": "task", "query": "позвонить ивану"}),
            AIResponse(action=AIAction.GET_SCHEDULE, params={"filter_type": "all", "start_date": today_str, "end_date": today_str})
        ]
        orch = DialogueOrchestrator(llm=llm_mock, db=self.db)
        await self.db.add_task(CHAT, "Пить воду до 10:00 каждый день", due_date=today_str, recurrence="daily")
        await self.db.add_task(CHAT, "Позвонить Ивану", due_date=today_str, due_time="10:00")

        r1 = await orch.handle_text(CHAT, "я выпил воды")
        self.assertIn("выполнена", r1.text.lower())
        self.assertIn("пить воду", r1.text.lower())

        r2 = await orch.handle_text(CHAT, "я позвонил ивану")
        self.assertIn("выполнен", r2.text.lower())
        self.assertIn("позвонить ивану", r2.text.lower())

        r3 = await orch.handle_text(CHAT, "расписание")
        self.assertIn("[x] Позвонить Ивану", r3.text)
        await orch.aclose()

    async def test_reschedule_with_specific_query(self):
        llm_mock = MagicMock(parse_intent=AsyncMock())
        llm_mock.parse_intent.return_value = AIResponse(action=AIAction.RESCHEDULE_RECORD, params={"target": "meeting", "query": "дизайнером", "new_time": "20:00"})
        orch = DialogueOrchestrator(llm=llm_mock, db=self.db)

        test_date = "2099-11-20"
        m1 = await self.db.add_meeting(CHAT, "Встреча с инвестором", start_date=test_date, start_time="16:30")
        m2 = await self.db.add_meeting(CHAT, "Встреча с дизайнером", start_date=test_date, start_time="16:30")

        r = await orch.handle_text(CHAT, "Перенеси встречу с дизайнером на 20:00")
        self.assertIn("успешно перенесена", r.text.lower())
        self.assertIn("дизайнером", r.text.lower())

        s = await self.db.get_schedule(CHAT, test_date, test_date, filter_type="meetings")
        times = {m["title"]: m["start_time"] for m in s["meetings"]}
        self.assertEqual(times["Встреча с дизайнером"], "20:00")
        self.assertEqual(times["Встреча с инвестором"], "16:30")
        await orch.aclose()

    async def test_reminder_relative_correction(self):
        llm_mock = MagicMock(parse_intent=AsyncMock())
        llm_mock.parse_intent.side_effect = [
            AIResponse(action=AIAction.CREATE_TASK, params={"title": "Позвонить", "due_time": "12:05", "is_reminder": True}),
            AIResponse(action=AIAction.RESCHEDULE_RECORD, params={"target": "last", "new_time": "12:10"})
        ]
        orch = DialogueOrchestrator(llm=llm_mock, db=self.db)

        r1 = await orch.handle_text(CHAT, "напомнить позвонить через 5 минут")
        self.assertIn("Напоминание", r1.text)
        self.assertIn("Позвонить", r1.text)

        r2 = await orch.handle_text(CHAT, "а нет, давай через 10 минут лучше")
        self.assertIn("Напоминание", r2.text)
        self.assertIn("перенесено", r2.text)
        self.assertIn("Позвонить", r2.text)

        await orch.aclose()


if __name__ == "__main__":
    unittest.main()



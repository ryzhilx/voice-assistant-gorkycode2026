import unittest
from unittest.mock import AsyncMock, MagicMock

from app.ai.schemas import AIAction, AIResponse
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


if __name__ == "__main__":
    unittest.main()


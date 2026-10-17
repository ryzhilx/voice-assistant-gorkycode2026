import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.ai.schemas import AIAction, AIResponse
from app.bot import handlers
from app.bot.states import Clarification


def make_message(text=None):
    msg = MagicMock()
    msg.text = text
    msg.voice = MagicMock()
    msg.answer = AsyncMock()
    return msg


def clarification_response():
    return AIResponse(
        action=AIAction.ASK_CLARIFICATION,
        params={
            "missing_slot": "time",
            "question": "На какое время поставить встречу?",
            "draft_data": {"title": "Встреча с Иваном", "start_date": "2026-10-18"},
        },
    )


class TestBotHandlers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))
        self.llm = patch.object(handlers, "llm", MagicMock(parse_intent=AsyncMock())).start()
        self.stt = patch.object(handlers, "stt", MagicMock(speech_to_text=AsyncMock())).start()
        self.addCleanup(patch.stopall)

    async def test_clarification_saves_draft_and_asks_question(self):
        self.llm.parse_intent.return_value = clarification_response()
        msg = make_message()

        await handlers.process_text(msg, self.state, "Поставь встречу с Иваном завтра")

        self.assertEqual(await self.state.get_state(), Clarification.waiting_slot.state)
        data = await self.state.get_data()
        self.assertEqual(data["awaiting_slot"], "time")
        self.assertEqual(data["draft_data"]["title"], "Встреча с Иваном")
        msg.answer.assert_awaited_once_with("На какое время поставить встречу?")
        self.llm.parse_intent.assert_awaited_once_with("Поставь встречу с Иваном завтра", None)

    async def test_answer_resumes_with_draft_and_clears_state(self):
        self.llm.parse_intent.return_value = clarification_response()
        await handlers.process_text(make_message(), self.state, "Поставь встречу с Иваном завтра")

        done = AIResponse(
            action=AIAction.CREATE_MEETING,
            params={"title": "Встреча с Иваном", "start_date": "2026-10-18", "start_time": "15:00"},
        )
        self.llm.parse_intent.return_value = done
        msg = make_message()

        await handlers.process_text(msg, self.state, "В 15:00")

        self.llm.parse_intent.assert_awaited_with(
            "В 15:00",
            {"awaiting_slot": "time", "draft_data": {"title": "Встреча с Иваном", "start_date": "2026-10-18"}},
        )
        self.assertIsNone(await self.state.get_state())
        self.assertEqual(await self.state.get_data(), {})
        self.assertIn("create_meeting", msg.answer.await_args.args[0])

    async def test_plain_text_passes_no_context(self):
        self.llm.parse_intent.return_value = AIResponse(action=AIAction.CREATE_TASK, params={"title": "Задача"})
        msg = make_message("Напомни купить хлеб")

        await handlers.on_text(msg, self.state)

        self.llm.parse_intent.assert_awaited_once_with("Напомни купить хлеб", None)
        self.assertIsNone(await self.state.get_state())

    async def test_missing_question_falls_back_to_default(self):
        self.llm.parse_intent.return_value = AIResponse(
            action=AIAction.ASK_CLARIFICATION, params={"missing_slot": "date"}
        )
        msg = make_message()

        await handlers.process_text(msg, self.state, "Поставь встречу")

        msg.answer.assert_awaited_once_with("Уточните, пожалуйста.")

    async def test_start_clears_pending_clarification(self):
        await self.state.set_state(Clarification.waiting_slot)
        await self.state.update_data(awaiting_slot="time", draft_data={"title": "x"})
        msg = make_message()

        await handlers.cmd_start(msg, self.state)

        self.assertIsNone(await self.state.get_state())
        self.assertEqual(await self.state.get_data(), {})
        msg.answer.assert_awaited_once()

    async def test_voice_is_transcribed_and_processed(self):
        self.stt.speech_to_text.return_value = "Поставь встречу с Иваном завтра"
        self.llm.parse_intent.return_value = clarification_response()
        bot = MagicMock(download=AsyncMock())
        msg = make_message()

        await handlers.on_voice(msg, bot, self.state)

        bot.download.assert_awaited_once()
        self.stt.speech_to_text.assert_awaited_once()
        self.llm.parse_intent.assert_awaited_once_with("Поставь встречу с Иваном завтра", None)
        replies = [c.args[0] for c in msg.answer.await_args_list]
        self.assertEqual(replies[0], "Распознано: «Поставь встречу с Иваном завтра»")
        self.assertEqual(replies[1], "На какое время поставить встречу?")

    async def test_voice_recognition_failure_does_not_call_llm(self):
        self.stt.speech_to_text.return_value = None
        bot = MagicMock(download=AsyncMock())
        msg = make_message()

        await handlers.on_voice(msg, bot, self.state)

        self.llm.parse_intent.assert_not_awaited()
        msg.answer.assert_awaited_once()
        self.assertIsNone(await self.state.get_state())


if __name__ == "__main__":
    unittest.main()

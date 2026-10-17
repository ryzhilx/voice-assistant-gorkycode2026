import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import handlers
from app.orchestrator.dialogue import Reply


def make_message(text=None, chat_id=7):
    msg = MagicMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.voice = MagicMock()
    msg.answer = AsyncMock()
    return msg


class TestBotHandlers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orch = patch.object(
            handlers, "orchestrator",
            MagicMock(handle_text=AsyncMock(return_value=Reply("ответ")), reset=MagicMock()),
        ).start()
        self.stt = patch.object(handlers, "stt", MagicMock(speech_to_text=AsyncMock())).start()
        self.addCleanup(patch.stopall)

    async def test_text_is_forwarded_to_orchestrator_and_reply_sent(self):
        msg = make_message("Напомни купить хлеб")

        await handlers.on_text(msg)

        self.orch.handle_text.assert_awaited_once_with(7, "Напомни купить хлеб")
        msg.answer.assert_awaited_once_with("ответ")

    async def test_start_resets_dialogue(self):
        msg = make_message()

        await handlers.cmd_start(msg)

        self.orch.reset.assert_called_once_with(7)
        msg.answer.assert_awaited_once()

    async def test_voice_is_transcribed_and_forwarded(self):
        self.stt.speech_to_text.return_value = "Поставь встречу с Иваном завтра"
        bot = MagicMock(download=AsyncMock())
        msg = make_message()

        await handlers.on_voice(msg, bot)

        bot.download.assert_awaited_once()
        self.orch.handle_text.assert_awaited_once_with(7, "Поставь встречу с Иваном завтра")
        replies = [c.args[0] for c in msg.answer.await_args_list]
        self.assertEqual(replies, ["Распознано: «Поставь встречу с Иваном завтра»", "ответ"])

    async def test_voice_recognition_failure_skips_orchestrator(self):
        self.stt.speech_to_text.return_value = None
        bot = MagicMock(download=AsyncMock())
        msg = make_message()

        await handlers.on_voice(msg, bot)

        self.orch.handle_text.assert_not_awaited()
        msg.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot import handlers
from app.bot.middleware import AccessMiddleware
from app.config import settings
from app.orchestrator.dialogue import Reply


def make_message(text=None, chat_id=7):
    msg = MagicMock()
    msg.text = text
    msg.chat.id = chat_id
    msg.voice = MagicMock()
    msg.answer = AsyncMock()
    msg.answer_voice = AsyncMock()
    return msg


class TestBotHandlers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orch = patch.object(
            handlers, "orchestrator",
            MagicMock(handle_text=AsyncMock(return_value=Reply("ответ")), reset=MagicMock()),
        ).start()
        self.stt = patch.object(
            handlers, "stt",
            MagicMock(speech_to_text=AsyncMock(), text_to_speech=AsyncMock(return_value=None))
        ).start()
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

    async def test_oversized_voice_is_rejected_before_download(self):
        msg = make_message()
        msg.voice.duration = 120
        msg.voice.file_size = 5_000_000
        bot = MagicMock(download=AsyncMock())

        await handlers.on_voice(msg, bot)

        bot.download.assert_not_awaited()
        self.stt.speech_to_text.assert_not_awaited()
        self.assertIn("слишком длинное", msg.answer.await_args.args[0])


    async def test_help_handler_sends_instructions(self):
        msg = make_message()
        await handlers.cmd_help(msg)
        msg.answer.assert_awaited_once()
        self.assertIn("Встречи", msg.answer.await_args.args[0])

    async def test_today_command_fetches_schedule(self):
        msg = make_message()
        await handlers.cmd_today(msg)
        self.orch.handle_text.assert_awaited_once_with(7, "Что у меня запланировано на сегодня?")
        msg.answer.assert_awaited_once()

    async def test_tasks_command_fetches_tasks(self):
        msg = make_message()
        await handlers.cmd_tasks(msg)
        self.orch.handle_text.assert_awaited_once_with(7, "Какие у меня активные задачи?")
        msg.answer.assert_awaited_once()

    async def test_dialogue_cancel_callback_resets_dialogue(self):
        cb = MagicMock()
        cb.from_user.id = 7
        cb.answer = AsyncMock()
        cb.message = MagicMock(edit_text=AsyncMock())

        await handlers.on_dialogue_cancel(cb)

        self.orch.reset.assert_called_once_with(7)
        cb.answer.assert_awaited_once_with("Диалог отменен")
        cb.message.edit_text.assert_awaited_once_with("Действие отменено. Чем могу помочь?")


class TestAccessMiddleware(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.middleware = AccessMiddleware()
        self.handler = AsyncMock()
        self.event = MagicMock()
        self.event.from_user.id = 42

    async def test_allowlist_blocks_unknown_user(self):
        with patch.object(settings, "allowed_user_ids", (1,)), patch.object(settings, "rate_limit_per_minute", 0):
            await self.middleware(self.handler, self.event, {})
        self.handler.assert_not_awaited()

    async def test_allowlist_allows_known_user(self):
        with patch.object(settings, "allowed_user_ids", (42,)), patch.object(settings, "rate_limit_per_minute", 0):
            await self.middleware(self.handler, self.event, {})
        self.handler.assert_awaited_once()

    async def test_rate_limit_blocks_repeated_requests(self):
        with patch.object(settings, "allowed_user_ids", ()), patch.object(settings, "rate_limit_per_minute", 1):
            await self.middleware(self.handler, self.event, {})
            await self.middleware(self.handler, self.event, {})
        self.handler.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

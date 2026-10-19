import unittest
from unittest.mock import AsyncMock, MagicMock
import datetime

from app.storage.db import Database
from app.bot.reminders import check_and_send_reminders


class TestReminderWorker(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.mock_bot = MagicMock()
        self.mock_bot.send_message = AsyncMock()

    async def test_due_task_reminder_sent(self):
        task_id = await self.db.add_task(
            user_id=123,
            title="Выпить таблетку",
            due_date="2026-10-18",
            due_time="14:00",
            is_reminder=True
        )

        fixed_now = datetime.datetime(2026, 10, 18, 14, 5)
        sent_count = await check_and_send_reminders(self.mock_bot, self.db, now=fixed_now)

        self.assertEqual(sent_count, 1)
        self.mock_bot.send_message.assert_awaited_once()
        call_kwargs = self.mock_bot.send_message.await_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], 123)
        self.assertIn("Выпить таблетку", call_kwargs["text"])
        self.assertIn("Напоминание", call_kwargs["text"])
        self.assertIsNotNone(call_kwargs["reply_markup"])

        second_run = await check_and_send_reminders(self.mock_bot, self.db, now=fixed_now)
        self.assertEqual(second_run, 0)

    async def test_future_task_not_sent(self):
        await self.db.add_task(
            user_id=123,
            title="Будущая задача",
            due_date="2026-10-18",
            due_time="16:00",
            is_reminder=True
        )

        fixed_now = datetime.datetime(2026, 10, 18, 14, 0)
        sent_count = await check_and_send_reminders(self.mock_bot, self.db, now=fixed_now)
        self.assertEqual(sent_count, 0)
        self.mock_bot.send_message.assert_not_awaited()

    async def test_completed_task_not_sent(self):
        task_id = await self.db.add_task(
            user_id=123,
            title="Уже выполненная задача",
            due_date="2026-10-18",
            due_time="10:00",
            is_reminder=True
        )
        await self.db.mark_task_completed(123, task_id)

        fixed_now = datetime.datetime(2026, 10, 18, 12, 0)
        sent_count = await check_and_send_reminders(self.mock_bot, self.db, now=fixed_now)
        self.assertEqual(sent_count, 0)
        self.mock_bot.send_message.assert_not_awaited()

    async def test_due_meeting_reminder_sent(self):
        meeting_id = await self.db.add_meeting(
            user_id=456,
            title="Синхрон с командой",
            start_date="2026-10-18",
            start_time="15:30",
            participants="Иван, Анна"
        )

        fixed_now = datetime.datetime(2026, 10, 18, 15, 30)
        sent_count = await check_and_send_reminders(self.mock_bot, self.db, now=fixed_now)

        self.assertEqual(sent_count, 1)
        self.mock_bot.send_message.assert_awaited_once()
        call_kwargs = self.mock_bot.send_message.await_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], 456)
        self.assertIn("Синхрон с командой", call_kwargs["text"])
        self.assertIn("15:30", call_kwargs["text"])
        self.assertIn("Иван, Анна", call_kwargs["text"])

        second_run = await check_and_send_reminders(self.mock_bot, self.db, now=fixed_now)
        self.assertEqual(second_run, 0)

    async def test_eastern_timezone_reminder_sent(self):
        await self.db.set_user_timezone(789, "Asia/Vladivostok")
        task_id = await self.db.add_task(
            user_id=789,
            title="Срочный отчет во Владивостоке",
            due_date="2020-01-01",
            due_time="09:00",
            is_reminder=True
        )
        sent_count = await check_and_send_reminders(self.mock_bot, self.db, now=None)
        self.assertEqual(sent_count, 1)
        self.mock_bot.send_message.assert_awaited()


if __name__ == "__main__":
    unittest.main()

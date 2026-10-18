import unittest
from app.storage.db import Database

class TestDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")

    async def test_add_and_get_tasks(self):
        task_id = await self.db.add_task(
            user_id=1,
            title="Купить хлеб",
            due_date="2026-10-18",
            due_time="10:00",
            is_reminder=True
        )
        self.assertGreater(task_id, 0)

        data = await self.db.get_schedule(user_id=1, start_date="2026-10-18", end_date="2026-10-18")
        tasks = data["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Купить хлеб")
        self.assertEqual(tasks[0]["status"], "pending")

    async def test_add_meeting_and_conflict_detection(self):
        await self.db.add_meeting(
            user_id=1,
            title="Встреча с дизайнером",
            start_date="2026-10-18",
            start_time="15:00",
            duration_minutes=60
        )

        conflict = await self.db.check_meeting_conflict(
            user_id=1,
            start_date="2026-10-18",
            start_time="15:00"
        )
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["title"], "Встреча с дизайнером")

        no_conflict = await self.db.check_meeting_conflict(
            user_id=1,
            start_date="2026-10-18",
            start_time="17:00"
        )
        self.assertIsNone(no_conflict)

    async def test_mark_task_completed(self):
        task_id = await self.db.add_task(
            user_id=1,
            title="Отправить отчет",
            due_date="2026-10-18"
        )
        ok = await self.db.mark_task_completed(user_id=1, task_id=task_id)
        self.assertTrue(ok)

        data = await self.db.get_schedule(user_id=1, start_date="2026-10-18")
        self.assertEqual(data["tasks"][0]["status"], "completed")

    async def test_get_all_records_for_search(self):
        await self.db.add_task(user_id=1, title="Задача 1")
        await self.db.add_meeting(user_id=1, title="Встреча 1", start_date="2026-10-18", start_time="10:00")

        records = await self.db.get_all_records_for_search(user_id=1)
        self.assertEqual(len(records), 2)
        types = {r["type"] for r in records}
        self.assertEqual(types, {"task", "meeting"})

    async def test_user_timezone_default_and_set(self):
        default_tz = await self.db.get_user_timezone(user_id=99)
        self.assertEqual(default_tz, "Europe/Moscow")

        await self.db.set_user_timezone(user_id=99, timezone="Asia/Yekaterinburg", username="testuser")
        updated_tz = await self.db.get_user_timezone(user_id=99)
        self.assertEqual(updated_tz, "Asia/Yekaterinburg")

    async def test_archive_past_meetings_and_get_archive(self):
        meeting_id = await self.db.add_meeting(
            user_id=10,
            title="Прошедшая встреча",
            start_date="2026-10-18",
            start_time="02:54"
        )
        await self.db.mark_meeting_reminder_sent(meeting_id)

        schedule = await self.db.get_schedule(user_id=10, start_date="2026-10-18")
        self.assertEqual(len(schedule["meetings"]), 0)

        archive = await self.db.get_archive(user_id=10)
        self.assertEqual(len(archive["meetings"]), 1)
        self.assertEqual(archive["meetings"][0]["title"], "Прошедшая встреча")

        restored = await self.db.restore_record(user_id=10, record_type="meeting", record_id=meeting_id)
        self.assertTrue(restored)

        records = await self.db.get_all_records_for_search(user_id=10, record_type="meetings")
        self.assertEqual(records[0]["status"], "active")


if __name__ == "__main__":
    unittest.main()

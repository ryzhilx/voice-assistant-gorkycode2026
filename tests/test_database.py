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

    async def test_recurring_task_schedule_expansion(self):
        await self.db.add_task(
            user_id=20,
            title="Пить витамины",
            due_date="2026-10-18",
            due_time="09:00",
            recurrence="daily"
        )
        res = await self.db.get_schedule(user_id=20, start_date="2026-10-18", end_date="2026-10-20")
        tasks = res["tasks"]
        self.assertEqual(len(tasks), 3)
        self.assertEqual([t["due_date"] for t in tasks], ["2026-10-18", "2026-10-19", "2026-10-20"])
        self.assertEqual(tasks[0]["recurrence"], "daily")

    async def test_recurring_meeting_weekdays_expansion(self):
        await self.db.add_meeting(
            user_id=21,
            title="Стендап",
            start_date="2026-10-16",
            start_time="11:00",
            recurrence="weekdays"
        )
        res = await self.db.get_schedule(user_id=21, start_date="2026-10-16", end_date="2026-10-19")
        meetings = res["meetings"]
        self.assertEqual(len(meetings), 2)
        self.assertEqual([m["start_date"] for m in meetings], ["2026-10-16", "2026-10-19"])

    async def test_recurring_meeting_conflict(self):
        await self.db.add_meeting(
            user_id=22,
            title="Планерка",
            start_date="2026-10-19",
            start_time="10:00",
            recurrence="weekly:mon"
        )
        conflict = await self.db.check_meeting_conflict(user_id=22, start_date="2026-10-26", start_time="10:00")
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["title"], "Планерка")

        no_conflict = await self.db.check_meeting_conflict(user_id=22, start_date="2026-10-27", start_time="10:00")
        self.assertIsNone(no_conflict)

    async def test_recurring_task_completion_advances_date(self):
        task_id = await self.db.add_task(
            user_id=23,
            title="Ежедневный отчет",
            due_date="2026-10-18",
            recurrence="daily"
        )
        ok = await self.db.mark_task_completed(user_id=23, task_id=task_id)
        self.assertTrue(ok)

        schedule = await self.db.get_schedule(user_id=23, start_date="2026-10-19", end_date="2026-10-19")
        self.assertEqual(len(schedule["tasks"]), 1)
        self.assertEqual(schedule["tasks"][0]["status"], "pending")

    def test_calculate_next_occurrence(self):
        d1 = Database.calculate_next_occurrence("2026-10-18", "daily")
        self.assertEqual(d1, "2026-10-19")

        d2 = Database.calculate_next_occurrence("2026-10-16", "weekdays")
        self.assertEqual(d2, "2026-10-19")

        d3 = Database.calculate_next_occurrence("2026-10-19", "weekly:mon")
        self.assertEqual(d3, "2026-10-26")

        d4 = Database.calculate_next_occurrence("2026-10-18", "monthly")
        self.assertEqual(d4, "2026-11-18")


if __name__ == "__main__":
    unittest.main()

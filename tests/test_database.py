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

        task_id = await self.db.add_task(
            user_id=10,
            title="Купить молоко",
            due_date=None
        )
        await self.db.mark_task_completed(user_id=10, task_id=task_id)

        schedule = await self.db.get_schedule(user_id=10, start_date="2026-10-18")
        self.assertEqual(len(schedule["meetings"]), 0)

        archive_all = await self.db.get_archive(user_id=10)
        self.assertEqual(len(archive_all["meetings"]), 1)
        self.assertEqual(archive_all["meetings"][0]["title"], "Прошедшая встреча")
        self.assertEqual(len(archive_all["tasks"]), 1)
        self.assertEqual(archive_all["tasks"][0]["title"], "Купить молоко")

        archive_meetings = await self.db.get_archive(user_id=10, filter_type="meetings")
        self.assertEqual(len(archive_meetings["meetings"]), 1)
        self.assertEqual(len(archive_meetings["tasks"]), 0)

        archive_tasks = await self.db.get_archive(user_id=10, filter_type="tasks")
        self.assertEqual(len(archive_tasks["meetings"]), 0)
        self.assertEqual(len(archive_tasks["tasks"]), 1)

        task_id2 = await self.db.add_task(user_id=10, title="Помыть машину", due_date=None)
        await self.db.mark_task_completed(user_id=10, task_id=task_id2)

        archived_count = await self.db.archive_past_records(user_id=10, current_date="2026-10-19", current_time="12:00")
        self.assertGreaterEqual(archived_count, 1)

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
        ok = await self.db.mark_task_completed(user_id=23, task_id=task_id, current_date="2026-10-18")
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

        d5 = Database.calculate_next_occurrence("2026-10-23", "weekends")
        self.assertEqual(d5, "2026-10-24")

    async def test_recurring_meeting_retains_visibility_after_advance(self):
        mid = await self.db.add_meeting(
            user_id=24,
            title="Планерка",
            start_date="2026-10-19",
            start_time="10:00",
            recurrence="weekly:mon"
        )
        s1 = await self.db.get_schedule(user_id=24, start_date="2026-10-19", end_date="2026-10-19")
        self.assertEqual(len(s1["meetings"]), 1)

        await self.db.advance_recurring_meeting(mid, "2026-10-26")

        s2 = await self.db.get_schedule(user_id=24, start_date="2026-10-19", end_date="2026-10-19")
        self.assertEqual(len(s2["meetings"]), 1)

        c = await self.db.check_meeting_conflict(user_id=24, start_date="2026-10-19", start_time="10:00")
        self.assertIsNotNone(c)

    async def test_recurring_task_no_double_advance_after_reminder(self):
        tid = await self.db.add_task(
            user_id=25,
            title="Пить витамины",
            due_date="2026-10-19",
            due_time="09:00",
            recurrence="daily"
        )
        await self.db.advance_recurring_task(tid, "2026-10-20")
        await self.db.mark_task_completed(user_id=25, task_id=tid, current_date="2026-10-19")

        row = self.db._get_connection().execute("SELECT due_date FROM tasks WHERE id = ?", (tid,)).fetchone()
        self.assertEqual(row["due_date"], "2026-10-20")

    async def test_weekends_recurrence_expansion(self):
        await self.db.add_meeting(
            user_id=26,
            title="Пробежка",
            start_date="2026-10-24",
            start_time="10:00",
            recurrence="weekends"
        )
        s_sat = await self.db.get_schedule(user_id=26, start_date="2026-10-24", end_date="2026-10-24")
        self.assertEqual(len(s_sat["meetings"]), 1)
        s_sun = await self.db.get_schedule(user_id=26, start_date="2026-10-25", end_date="2026-10-25")
        self.assertEqual(len(s_sun["meetings"]), 1)
        s_mon = await self.db.get_schedule(user_id=26, start_date="2026-10-26", end_date="2026-10-26")
        self.assertEqual(len(s_mon["meetings"]), 0)

    async def test_conflict_detection_ignores_archived(self):
        mid = await self.db.add_meeting(
            user_id=30,
            title="Старая встреча",
            start_date="2026-10-18",
            start_time="11:00",
            duration_minutes=60
        )
        await self.db.archive_past_records(user_id=30, current_date="2026-10-19", current_time="10:00")
        conflict = await self.db.check_meeting_conflict(user_id=30, start_date="2026-10-18", start_time="11:00")
        self.assertIsNone(conflict)

    async def test_conflict_detection_interval_overlap(self):
        await self.db.add_meeting(
            user_id=31,
            title="Встреча 1",
            start_date="2026-10-20",
            start_time="14:00",
            duration_minutes=60
        )
        c1 = await self.db.check_meeting_conflict(user_id=31, start_date="2026-10-20", start_time="14:30", duration_minutes=60)
        self.assertIsNotNone(c1)
        self.assertEqual(c1["title"], "Встреча 1")

        c2 = await self.db.check_meeting_conflict(user_id=31, start_date="2026-10-20", start_time="15:00", duration_minutes=60)
        self.assertIsNone(c2)

    async def test_mark_task_completed_overdue_advances_to_current(self):
        tid = await self.db.add_task(
            user_id=32,
            title="Ежедневная зарядка",
            due_date="2026-10-10",
            recurrence="daily"
        )
        await self.db.set_user_timezone(32, "Europe/Moscow")
        ok = await self.db.mark_task_completed(user_id=32, task_id=tid)
        self.assertTrue(ok)
        row = self.db._get_connection().execute("SELECT due_date FROM tasks WHERE id = ?", (tid,)).fetchone()
        import datetime
        try:
            from zoneinfo import ZoneInfo
            today_str = datetime.datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
        except Exception:
            today_str = datetime.date.today().isoformat()
        self.assertGreaterEqual(row["due_date"], today_str)

    async def test_meeting_duration_not_archived_until_finished(self):
        mid = await self.db.add_meeting(
            user_id=33,
            title="Длинная встреча",
            start_date="2099-10-19",
            start_time="16:00",
            duration_minutes=60
        )
        await self.db.mark_meeting_reminder_sent(mid)
        await self.db.archive_past_records(user_id=33, current_date="2099-10-19", current_time="16:30")
        s = await self.db.get_schedule(user_id=33, start_date="2099-10-19", end_date="2099-10-19")
        self.assertEqual(len(s["meetings"]), 1)

        await self.db.archive_past_records(user_id=33, current_date="2099-10-19", current_time="17:05")
        s2 = await self.db.get_schedule(user_id=33, start_date="2099-10-19", end_date="2099-10-19")
        self.assertEqual(len(s2["meetings"]), 0)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from unittest.mock import patch

from app.agent.schemas import ToolDefinition, ToolParameter
from app.agent.tools.manage import DeleteRecordTool, UpdateRecordTitleTool
from app.agent.tools.meeting import CreateMeetingTool
from app.agent.tools.task import CreateTaskTool
from app.agent.tools.validation import ToolValidationError, normalize_recurrence
from app.ai.embeddings import SemanticSearchEngine
from app.config import settings, validate_settings
from app.orchestrator.formatters import format_archive_view
from app.storage.db import Database

USER = 501


class TestRecordTargets(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.search = SemanticSearchEngine()

    async def test_delete_by_query_with_singular_target_deletes_matching_record(self):
        await self.db.add_task(USER, "Купить молоко", due_date="2026-10-28", due_time="10:00")
        await self.db.add_task(USER, "Помыть машину", due_date="2026-10-28", due_time="11:00")

        tool = DeleteRecordTool(self.db, self.search, {})
        result = await tool.execute(USER, target="task", query="молоко")

        self.assertTrue(result.success)
        titles = [record["title"] for record in await self.db.get_all_records_for_search(USER, "tasks")]
        self.assertEqual(titles, ["Помыть машину"])

    async def test_update_title_with_singular_target_updates_matching_record(self):
        await self.db.add_task(USER, "Купить молоко", due_date="2026-10-28", due_time="10:00")
        await self.db.add_task(USER, "Помыть машину", due_date="2026-10-28", due_time="11:00")

        tool = UpdateRecordTitleTool(self.db, self.search, {})
        result = await tool.execute(USER, target="task", query="молоко", new_title="Купить кефир")

        self.assertTrue(result.success)
        titles = {record["title"] for record in await self.db.get_all_records_for_search(USER, "tasks")}
        self.assertEqual(titles, {"Купить кефир", "Помыть машину"})


class TestToolValidation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.search = SemanticSearchEngine()
        self.task_tool = CreateTaskTool(self.db, self.search, {})
        self.meeting_tool = CreateMeetingTool(self.db, self.search, {})

    async def test_reminder_without_time_is_rejected(self):
        result = await self.task_tool.execute(USER, title="Позвонить врачу", is_reminder=True)
        self.assertFalse(result.success)
        self.assertIn("время", result.output.lower())
        self.assertEqual(await self.db.get_all_records_for_search(USER, "tasks"), [])

    async def test_reminder_with_time_but_without_date_gets_today(self):
        result = await self.task_tool.execute(
            USER,
            title="Позвонить врачу",
            due_time="09:30",
            is_reminder=True,
        )
        self.assertTrue(result.success)
        records = await self.db.get_all_records_for_search(USER, "tasks")
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0]["date"])

    async def test_invalid_date_is_rejected(self):
        result = await self.task_tool.execute(
            USER,
            title="Позвонить врачу",
            due_date="завтра",
            due_time="09:30",
            is_reminder=True,
        )
        self.assertFalse(result.success)
        self.assertIn("YYYY-MM-DD", result.output)

    async def test_russian_recurrence_is_normalized(self):
        self.assertEqual(normalize_recurrence("каждый понедельник"), "weekly:mon")
        self.assertEqual(normalize_recurrence("ежедневно"), "daily")
        with self.assertRaises(ToolValidationError):
            normalize_recurrence("иногда")

    async def test_meeting_conflict_uses_new_meeting_duration(self):
        first = await self.meeting_tool.execute(
            USER,
            title="Существующая встреча",
            start_date="2026-11-01",
            start_time="14:00",
            duration_minutes=60,
        )
        self.assertTrue(first.success)

        second = await self.meeting_tool.execute(
            USER,
            title="Длинная встреча",
            start_date="2026-11-01",
            start_time="13:00",
            duration_minutes=90,
        )
        self.assertTrue(second.success)
        self.assertIn("Внимание", second.output)

    async def test_invalid_meeting_time_is_rejected(self):
        result = await self.meeting_tool.execute(
            USER,
            title="Встреча",
            start_date="2026-11-01",
            start_time="25:00",
        )
        self.assertFalse(result.success)


class TestArchiveStatus(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")

    async def test_uncompleted_expired_reminder_is_not_marked_done(self):
        task_id = await self.db.add_task(
            USER,
            "Просроченное напоминание",
            due_date="2020-01-01",
            due_time="09:00",
            is_reminder=True,
        )
        await self.db.mark_task_reminder_sent(task_id)
        await self.db.archive_past_records(USER, current_date="2026-10-27", current_time="12:00")

        view = await format_archive_view(self.db, USER)
        self.assertIn("[ ] Просроченное напоминание", view)
        self.assertNotIn("[x] Просроченное напоминание", view)

    async def test_completed_task_keeps_completed_marker(self):
        task_id = await self.db.add_task(USER, "Сдать отчет", due_date="2026-10-20")
        await self.db.mark_task_completed(USER, task_id)
        await self.db.archive_past_records(USER, current_date="2026-10-27", current_time="12:00")

        view = await format_archive_view(self.db, USER)
        self.assertIn("[x] Сдать отчет", view)


class TestStorageAndSchema(unittest.IsolatedAsyncioTestCase):
    async def test_file_database_uses_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "assistant.db")
            db = Database(path)
            conn = db._get_connection()
            try:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(mode.lower(), "wal")

    def test_tool_schema_matches_yandex_format(self):
        definition = ToolDefinition(
            name="demo",
            description="demo",
            parameters={"value": ToolParameter(type="string", description="value", required=True)},
        )
        schema = definition.to_json_schema()
        self.assertIn("function", schema)
        self.assertNotIn("type", schema)
        self.assertEqual(schema["function"]["parameters"]["required"], ["value"])


class TestHybridSearch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = SemanticSearchEngine()
        self.records = [
            {"id": 1, "title": "Согласовать контракт с поставщиком", "type": "task"},
            {"id": 2, "title": "Юридический документ", "type": "task"},
        ]

    async def test_remote_rerank_can_beat_local_synonym_match(self):
        self.engine.yandex_api_key = "test-key"
        self.engine.yandex_folder_id = "test-folder"

        async def fake_embedding(text, model="text-search-query"):
            vectors = {
                "договор": [1.0, 0.0],
                "Согласовать контракт с поставщиком": [0.0, 1.0],
                "Юридический документ": [1.0, 0.0],
            }
            return vectors.get(text)

        self.engine.get_remote_embedding = fake_embedding
        ranked = await self.engine.rank_records_async("договор", self.records, top_k=2)

        self.assertEqual(ranked[0]["id"], 2)

    async def test_without_credentials_uses_local_ranking(self):
        self.engine.yandex_api_key = ""
        self.engine.yandex_folder_id = ""
        ranked = await self.engine.rank_records_async("договор", self.records, top_k=1)
        self.assertEqual(ranked[0]["id"], 1)


class TestConfig(unittest.TestCase):
    def test_missing_required_settings_are_reported(self):
        with patch.object(settings, "telegram_bot_token", ""), \
             patch.object(settings, "yandex_api_key", ""), \
             patch.object(settings, "yandex_folder_id", ""):
            missing = validate_settings()
        self.assertEqual(set(missing), {"TELEGRAM_BOT_TOKEN", "YANDEX_API_KEY", "YANDEX_FOLDER_ID"})


if __name__ == "__main__":
    unittest.main()

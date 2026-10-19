import csv
import os
import time
import unittest
from typing import List, Dict, Any

from unittest.mock import AsyncMock
from app.storage.db import Database
from app.ai.embeddings import SemanticSearchEngine
from app.ai.llm_client import LLMOrchestrator
from app.ai.schemas import AIAction, AIResponse
from app.orchestrator.dialogue import DialogueOrchestrator

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "voice_assistant_events_1000_77e927b5d2.csv")

class TestDataset1000(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.search_engine = SemanticSearchEngine()
        self.llm = LLMOrchestrator()
        self.llm.yandex_api_key = None
        self.llm.yandex_folder_id = None
        self.orch = DialogueOrchestrator(
            llm=self.llm,
            db=self.db,
            search_engine=self.search_engine
        )
        self.user_id = 99999

    async def asyncTearDown(self):
        await self.search_engine.aclose()
        await self.llm.aclose()
        await self.orch.aclose()

    def _load_csv(self) -> List[Dict[str, str]]:
        if not os.path.exists(CSV_PATH):
            self.skipTest("Dataset CSV not found")
        with open(CSV_PATH, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    async def _populate_db(self, rows: List[Dict[str, str]]):
        meeting_keywords = ["встреч", "созвон", "планёрк", "планерк", "демо", "митинг", "синк"]
        for r in rows:
            text = r["text"].strip()
            date_val = r["date"].strip()
            time_val = r["time"].strip()
            low = text.lower()
            if any(k in low for k in meeting_keywords):
                await self.db.add_meeting(
                    user_id=self.user_id,
                    title=text,
                    start_date=date_val,
                    start_time=time_val
                )
            else:
                is_rem = any(k in low for k in ["напомни", "позвони"])
                await self.db.add_task(
                    user_id=self.user_id,
                    title=text,
                    due_date=date_val,
                    due_time=time_val,
                    is_reminder=is_rem
                )

    async def test_dataset_bulk_ingestion(self):
        rows = self._load_csv()
        self.assertEqual(len(rows), 1000)

        t0 = time.perf_counter()
        await self._populate_db(rows)
        duration = time.perf_counter() - t0

        records = await self.db.get_all_records_for_search(self.user_id, "all")
        self.assertEqual(len(records), 1000)
        self.assertLess(duration, 3.0)

    async def test_dataset_schedule_retrieval(self):
        rows = self._load_csv()
        await self._populate_db(rows)

        t0 = time.perf_counter()
        sched_day = await self.db.get_schedule(self.user_id, "2024-01-26", "2024-01-26", include_archived=True)
        day_latency = time.perf_counter() - t0

        total_day_events = len(sched_day["tasks"]) + len(sched_day["meetings"])
        self.assertEqual(total_day_events, 3)
        self.assertLess(day_latency, 0.05)

        t1 = time.perf_counter()
        sched_active_2026 = await self.db.get_schedule(self.user_id, "2026-01-01", "2026-12-31")
        year_latency = time.perf_counter() - t1

        total_active_events = len(sched_active_2026["tasks"]) + len(sched_active_2026["meetings"])
        self.assertGreater(total_active_events, 100)
        self.assertLess(year_latency, 0.1)

    async def test_dataset_semantic_search_accuracy(self):
        rows = self._load_csv()
        await self._populate_db(rows)

        records = await self.db.get_all_records_for_search(self.user_id, "all")

        test_cases = [
            ("CRM", "crm"),
            ("договор", "договор"),
            ("смета", "смет"),
            ("хакатон", "хакатон"),
            ("презентация", "презентаци")
        ]

        for query, expected_sub in test_cases:
            matches = self.search_engine.rank_records(query, records, top_k=5)
            self.assertTrue(len(matches) > 0, f"Query '{query}' produced no results")
            top_titles = " ".join(m["title"] for m in matches).lower()
            self.assertIn(expected_sub.lower(), top_titles, f"Query '{query}' did not match '{expected_sub}' in {top_titles}")

    async def test_dataset_dialogue_search_and_reschedule(self):
        rows = self._load_csv()
        await self._populate_db(rows)

        self.llm.parse_intent = AsyncMock(side_effect=[
            AIResponse(action=AIAction.SEARCH_RECORDS, params={"query": "хакатон"}),
            AIResponse(action=AIAction.RESCHEDULE_RECORD, params={"target": "last", "new_date": "2026-11-20", "new_time": "18:00"})
        ])

        reply1 = await self.orch.handle_text(self.user_id, "Найди событие по хакатону")
        self.assertIn("хакатон", reply1.text.lower())
        top_id = self.orch._last_event[self.user_id]["id"]
        top_type = self.orch._last_event[self.user_id]["type"]

        reply2 = await self.orch.handle_text(self.user_id, "А перенеси ее на 2026-11-20 в 18:00")
        self.assertIn("успешно перенесена", reply2.text.lower())

        records = await self.db.get_all_records_for_search(self.user_id, "all")
        matched = [r for r in records if r["id"] == top_id and r["type"] == top_type]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["date"], "2026-11-20")
        self.assertEqual(matched[0]["time"], "18:00")

    async def test_dataset_conflict_detection(self):
        rows = self._load_csv()
        await self._populate_db(rows)

        meetings = (await self.db.get_schedule(self.user_id, "2024-01-01", "2027-12-31", filter_type="meetings", include_archived=True))["meetings"]
        self.assertTrue(len(meetings) > 0)
        first_m = meetings[0]

        conflict = await self.db.check_meeting_conflict(
            user_id=self.user_id,
            start_date=first_m["start_date"],
            start_time=first_m["start_time"]
        )
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["id"], first_m["id"])

if __name__ == "__main__":
    unittest.main()

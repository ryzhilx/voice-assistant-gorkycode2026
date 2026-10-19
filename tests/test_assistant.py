import unittest
from app.config import settings
from app.ai.embeddings import SemanticSearchEngine
from app.speech.speechkit import YandexSpeechKitService
from app.storage.db import Database
from app.agent.agent import ToolCallingAgent

@unittest.skipUnless(settings.yandex_api_key and settings.yandex_folder_id, "Yandex credentials not configured")
class TestAgentLive(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.agent = ToolCallingAgent(db=self.db)

    async def asyncTearDown(self):
        await self.agent.aclose()

    async def test_live_agent_create_task(self):
        reply = await self.agent.run(100, "Напомни мне завтра в 10 утра позвонить Ивану")
        self.assertTrue("Иван" in reply or "напоминание" in reply.lower() or "задач" in reply.lower())
        sched = await self.db.get_schedule(100, "2020-01-01", "2030-01-01", filter_type="tasks")
        self.assertEqual(len(sched["tasks"]), 1)

    async def test_live_agent_create_meeting(self):
        reply = await self.agent.run(100, "Добавь встречу с командой завтра в 15:00")
        self.assertTrue("встреча" in reply.lower() or "команд" in reply.lower())
        sched = await self.db.get_schedule(100, "2020-01-01", "2030-01-01", filter_type="meetings")
        self.assertEqual(len(sched["meetings"]), 1)

class TestSemanticSearch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = SemanticSearchEngine()

    async def asyncTearDown(self):
        await self.engine.aclose()

    async def test_local_similarity(self):
        records = [
            {"id": 1, "title": "Согласовать контракт с поставщиком", "type": "task"},
            {"id": 2, "title": "Подготовить отчет по продажам", "type": "task"},
            {"id": 3, "title": "Встреча с командой разработки", "type": "meeting"}
        ]
        results = self.engine.rank_records("договор", records, top_k=1)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], 1)

    async def test_tz_query_matching(self):
        records = [
            {"id": 1, "title": "Согласовать контракт с поставщиком", "type": "task"},
            {"id": 2, "title": "Купить продукты домой", "type": "task"},
            {"id": 3, "title": "Подготовить презентацию для демо", "type": "task"}
        ]
        ranked = self.engine.rank_records("договору", records, top_k=1)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], 1)

    async def test_inflected_forms_search(self):
        records = [
            {"id": 1, "title": "Сделать презентацию со слайдами", "type": "task"},
            {"id": 2, "title": "Записаться к врачу", "type": "task"}
        ]
        ranked = self.engine.rank_records("слайды", records, top_k=1)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], 1)

        ranked2 = self.engine.rank_records("со слайдами", records, top_k=1)
        self.assertEqual(len(ranked2), 1)
        self.assertEqual(ranked2[0]["id"], 1)

    def test_clean_text_for_tts(self):
        raw = "📦 Расписание (*сегодня*):\n• [x] Купить молоко\n• [ ] Написать отчет (🔄 ежедневно) ✅"
        cleaned = YandexSpeechKitService.clean_text_for_tts(raw)
        self.assertNotIn("📦", cleaned)
        self.assertNotIn("✅", cleaned)
        self.assertNotIn("*", cleaned)
        self.assertNotIn("[x]", cleaned)
        self.assertNotIn("[ ]", cleaned)
        self.assertIn("Выполнено: Купить молоко", cleaned)
        self.assertIn("Задача: Написать отчет", cleaned)
        self.assertIn("повторяется ежедневно", cleaned)

@unittest.skipUnless(settings.yandex_api_key and settings.yandex_folder_id, "Yandex credentials not configured")
class TestYandexCloudLive(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.speech = YandexSpeechKitService()

    async def asyncTearDown(self):
        await self.speech.aclose()

    async def test_speechkit_roundtrip(self):
        audio = await self.speech.text_to_speech("Тест голосового ассистента")
        self.assertIsNotNone(audio)
        self.assertGreater(len(audio), 1000)

        text = await self.speech.speech_to_text(audio)
        self.assertIsNotNone(text)
        self.assertIn("тест", text.lower())

if __name__ == "__main__":
    unittest.main()

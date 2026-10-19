import unittest
from unittest.mock import AsyncMock

from app.agent.agent import ToolCallingAgent
from app.agent.schemas import ToolCall
from app.ai.llm_client import LLMOrchestrator
from app.orchestrator.dialogue import DialogueOrchestrator
from app.storage.db import Database

CHAT = 777

class TestToolCallingAgent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.llm = LLMOrchestrator()
        self.llm.yandex_api_key = None
        self.llm.yandex_folder_id = None
        self.agent = ToolCallingAgent(
            db=self.db,
            llm=self.llm,
            yandex_api_key=None,
            yandex_folder_id=None
        )

        async def _mock_llm(chat_id, text, tz):
            low = text.lower()
            if "напомни купить молоко" in low:
                return [ToolCall(name="create_task", arguments={"title": "Купить молоко", "due_date": "2026-10-20", "due_time": "10:00", "is_reminder": True})], None
            if "инвестором" in low:
                return [ToolCall(name="create_meeting", arguments={"title": "Встреча с инвестором", "start_date": "2026-10-20", "start_time": "14:00"})], None
            if "дизайнером" in low:
                return [ToolCall(name="create_meeting", arguments={"title": "Встреча с дизайнером", "start_date": "2026-10-20", "start_time": "14:00"})], None
            if "напомнить позвонить через 5 минут" in low:
                return [ToolCall(name="create_task", arguments={"title": "Позвонить", "due_time": "12:05", "is_reminder": True})], None
            if "давай через 10 минут" in low:
                return [ToolCall(name="reschedule_record", arguments={"target": "last", "new_time": "12:10"})], None
            if "поставь задачу сдать отчет" in low:
                return [ToolCall(name="create_task", arguments={"title": "Сдать отчет", "due_date": "2026-10-20"})], None
            if "отметь задачу сдать отчет выполненной" in low:
                return [ToolCall(name="complete_task", arguments={"query": "сдать отчет"})], None
            if "помыть машину" in low:
                return [ToolCall(name="create_task", arguments={"title": "Помыть машину"})], None
            if "удали ее" in low:
                return [ToolCall(name="delete_record", arguments={"target": "last"})], None
            if "конференции" in low:
                return [ToolCall(name="create_task", arguments={"title": "Подготовить презентацию для конференции"})], None
            if "найди задачу про презентацию" in low:
                return [ToolCall(name="search_records", arguments={"query": "презентацию", "target": "tasks"})], None
            if "позвонить врачу" in low:
                return [ToolCall(name="create_task", arguments={"title": "Позвонить врачу", "due_time": "09:00"})], None
            if "привет" in low:
                return None, "Привет! Чем могу помочь?"
            if "добавь встречу" in low:
                return None, "На какую дату и время вы хотите запланировать встречу?"
            return None, None

        self.agent._call_llm = AsyncMock(side_effect=_mock_llm)

    async def asyncTearDown(self):
        await self.agent.aclose()

    async def test_agent_create_task_execution(self):
        reply = await self.agent.run(CHAT, "Напомни купить молоко завтра в 10:00")
        self.assertIn("Напоминание", reply)
        self.assertIn("Купить молоко", reply)
        self.assertIn("10:00", reply)

        sched = await self.db.get_schedule(CHAT, "2020-01-01", "2030-01-01", filter_type="tasks")
        self.assertEqual(len(sched["tasks"]), 1)
        self.assertEqual(sched["tasks"][0]["title"], "Купить молоко")

    async def test_agent_create_meeting_with_conflict(self):
        r1 = await self.agent.run(CHAT, "Встреча с инвестором завтра в 14:00")
        self.assertIn("Встреча", r1)
        self.assertIn("14:00", r1)

        r2 = await self.agent.run(CHAT, "Встреча с дизайнером завтра в 14:00")
        self.assertIn("Внимание", r2)
        self.assertIn("инвестором", r2)

    async def test_agent_conversational_correction_reschedule(self):
        r1 = await self.agent.run(CHAT, "напомнить позвонить через 5 минут")
        self.assertIn("Напоминание", r1)
        self.assertIn("Позвонить", r1)

        r2 = await self.agent.run(CHAT, "а нет, давай через 10 минут лучше")
        self.assertIn("Напоминание", r2)
        self.assertIn("перенесено", r2)
        self.assertIn("Позвонить", r2)

    async def test_agent_complete_task(self):
        await self.agent.run(CHAT, "Поставь задачу сдать отчет")
        r = await self.agent.run(CHAT, "Отметь задачу сдать отчет выполненной")
        self.assertIn("выполнен", r.lower())
        self.assertIn("сдать отчет", r.lower())

        sched = await self.db.get_schedule(CHAT, "2020-01-01", "2030-01-01", filter_type="tasks", include_archived=True)
        self.assertEqual(sched["tasks"][0]["status"], "completed")

    async def test_agent_delete_record(self):
        await self.agent.run(CHAT, "Поставь задачу помыть машину")
        r = await self.agent.run(CHAT, "Удали ее")
        self.assertIn("удалена", r)

        sched = await self.db.get_schedule(CHAT, "2020-01-01", "2030-01-01", filter_type="tasks")
        self.assertEqual(len(sched["tasks"]), 0)

    async def test_agent_search_records(self):
        await self.agent.run(CHAT, "Поставь задачу подготовить презентацию для конференции")
        r = await self.agent.run(CHAT, "Найди задачу про презентацию")
        self.assertIn("презентацию", r)

    async def test_agent_chat_clarification(self):
        r = await self.agent.run(CHAT, "Привет")
        self.assertIn("Привет", r)

        r2 = await self.agent.run(CHAT, "Добавь встречу")
        self.assertIn("дату и время", r2)

    async def test_dialogue_orchestrator_integration_with_agent(self):
        orch = DialogueOrchestrator(db=self.db, agent=self.agent)
        res = await orch.handle_text(CHAT, "Поставь задачу позвонить врачу завтра в 09:00")
        self.assertIn("Задача добавлена", res.text)
        self.assertIn("позвонить врачу", res.text.lower())
        await orch.aclose()


if __name__ == "__main__":
    unittest.main()

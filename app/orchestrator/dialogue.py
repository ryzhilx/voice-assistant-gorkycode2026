import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from app.ai.llm_client import LLMOrchestrator
from app.ai.embeddings import SemanticSearchEngine
from app.ai.schemas import AIAction, AIResponse
from app.storage.db import Database
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_QUESTION = "Уточните, пожалуйста."

@dataclass
class Reply:
    text: str

@dataclass
class PendingClarification:
    slot: Optional[str]
    draft: Dict[str, Any]

class DialogueOrchestrator:
    def __init__(
        self,
        llm: Optional[LLMOrchestrator] = None,
        db: Optional[Database] = None,
        search_engine: Optional[SemanticSearchEngine] = None
    ):
        self.llm = llm or LLMOrchestrator()
        self.db = db or Database(settings.database_path)
        self.search_engine = search_engine or SemanticSearchEngine()
        self._pending: Dict[int, PendingClarification] = {}

    def has_pending(self, chat_id: int) -> bool:
        return chat_id in self._pending

    def reset(self, chat_id: int) -> None:
        self._pending.pop(chat_id, None)

    async def handle_text(self, chat_id: int, text: str) -> Reply:
        pending = self._pending.get(chat_id)
        context = {"awaiting_slot": pending.slot, "draft_data": pending.draft} if pending else None

        result = await self.llm.parse_intent(text, context)
        return await self._dispatch(chat_id, result)

    async def _dispatch(self, chat_id: int, result: AIResponse) -> Reply:
        if result.action == AIAction.ASK_CLARIFICATION:
            self._pending[chat_id] = PendingClarification(
                slot=result.params.get("missing_slot"),
                draft=result.params.get("draft_data", {}),
            )
            return Reply(result.params.get("question", DEFAULT_QUESTION))

        self.reset(chat_id)

        if result.action == AIAction.CHAT:
            reply_text = result.params.get("reply") or result.user_reply or "Чем я могу вам помочь?"
            return Reply(reply_text)

        if result.action == AIAction.CREATE_TASK:
            title = result.params.get("title", "Задача")
            due_date = result.params.get("due_date")
            due_time = result.params.get("due_time")
            is_reminder = bool(result.params.get("is_reminder", False))

            await self.db.add_task(
                user_id=chat_id,
                title=title,
                due_date=due_date,
                due_time=due_time,
                is_reminder=is_reminder
            )

            date_info = f" на {due_date}" if due_date else ""
            time_info = f" в {due_time}" if due_time else ""
            prefix = "Напоминание установлено" if is_reminder else "Задача добавлена"
            return Reply(f"{prefix}: «{title}»{date_info}{time_info}.")

        if result.action == AIAction.CREATE_MEETING:
            title = result.params.get("title", "Встреча")
            start_date = result.params.get("start_date")
            start_time = result.params.get("start_time")
            duration = int(result.params.get("duration_minutes", 60))
            participants = result.params.get("participants")

            conflict = await self.db.check_meeting_conflict(chat_id, start_date, start_time)
            await self.db.add_meeting(
                user_id=chat_id,
                title=title,
                start_date=start_date,
                start_time=start_time,
                duration_minutes=duration,
                participants=participants
            )

            response_text = f"Встреча «{title}» назначена на {start_date} в {start_time}."
            if conflict:
                response_text += f"\nВнимание: в это же время уже стоит «{conflict.get('title')}»."
            return Reply(response_text)

        if result.action == AIAction.GET_SCHEDULE:
            start_date = result.params.get("start_date")
            end_date = result.params.get("end_date") or start_date
            filter_type = result.params.get("filter_type", "all")

            data = await self.db.get_schedule(chat_id, start_date, end_date, filter_type)
            tasks = data.get("tasks", [])
            meetings = data.get("meetings", [])

            if not tasks and not meetings:
                period = start_date if start_date == end_date else f"с {start_date} по {end_date}"
                return Reply(f"На {period} ничего не запланировано.")

            lines: List[str] = []
            period_str = start_date if start_date == end_date else f"{start_date} — {end_date}"
            lines.append(f"Расписание ({period_str}):")

            if meetings:
                lines.append("\nВстречи:")
                for m in meetings:
                    t = m.get("start_time") or ""
                    title = m.get("title")
                    lines.append(f"- {t} {title}")

            if tasks:
                lines.append("\nЗадачи:")
                for t in tasks:
                    status = "[x]" if t.get("status") == "completed" else "[ ]"
                    tm = f" (до {t.get('due_time')})" if t.get("due_time") else ""
                    lines.append(f"{status} {t.get('title')}{tm}")

            return Reply("\n".join(lines))

        if result.action == AIAction.SEARCH_RECORDS:
            query = result.params.get("query", "").strip()
            record_type = result.params.get("record_type", "all")

            records = await self.db.get_all_records_for_search(chat_id, record_type)
            if not records:
                return Reply(f"По запросу «{query}» ничего не найдено.")

            matches = self.search_engine.rank_records(query, records, top_k=3)
            if not matches:
                return Reply(f"По запросу «{query}» ничего не найдено.")

            lines = [f"Найдено по запросу «{query}»:"]
            for m in matches:
                kind = "Встреча" if m.get("type") == "meeting" else "Задача"
                date_str = f" ({m.get('date')})" if m.get("date") else ""
                lines.append(f"- [{kind}] {m.get('title')}{date_str}")

            return Reply("\n".join(lines))

        logger.info("Unknown action=%s params=%s", result.action.value, result.params)
        return Reply("Запрос принят, но действие не определено.")

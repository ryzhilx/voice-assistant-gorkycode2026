import datetime
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
        self._history: Dict[int, List[Dict[str, str]]] = {}
        self._last_event: Dict[int, Dict[str, Any]] = {}

    def has_pending(self, chat_id: int) -> bool:
        return chat_id in self._pending

    def reset(self, chat_id: int) -> None:
        self._pending.pop(chat_id, None)
        self._history.pop(chat_id, None)

    async def handle_text(self, chat_id: int, text: str) -> Reply:
        if hasattr(self.llm, "set_current_timezone") and callable(getattr(self.llm, "set_current_timezone")):
            try:
                tz = await self.db.get_user_timezone(chat_id)
                self.llm.set_current_timezone(tz)
            except Exception:
                pass

        pending = self._pending.get(chat_id)
        context = {"awaiting_slot": pending.slot, "draft_data": pending.draft} if pending else None

        result = await self.llm.parse_intent(text, context)
        reply = await self._dispatch(chat_id, result)

        if chat_id not in self._history:
            self._history[chat_id] = []
        self._history[chat_id].append({"role": "user", "text": text})
        self._history[chat_id].append({"role": "assistant", "text": reply.text})
        if len(self._history[chat_id]) > 6:
            self._history[chat_id] = self._history[chat_id][-6:]

        return reply

    async def _dispatch(self, chat_id: int, result: AIResponse) -> Reply:
        if result.action == AIAction.ASK_CLARIFICATION:
            prev_draft = self._pending[chat_id].draft if chat_id in self._pending else {}
            new_draft = {**prev_draft, **result.params.get("draft_data", {})}
            self._pending[chat_id] = PendingClarification(
                slot=result.params.get("missing_slot"),
                draft=new_draft,
            )
            reply = Reply(result.params.get("question", DEFAULT_QUESTION))
            return reply

        self.reset(chat_id)

        if result.action == AIAction.MULTI_ACTION or result.sub_actions:
            sub_actions = result.sub_actions or []
            replies = []
            for idx, sub in enumerate(sub_actions, 1):
                sub_reply = await self._execute_single_action(chat_id, sub.action, sub.params, sub.user_reply)
                replies.append(f"{idx}️⃣ {sub_reply.text}")
            return Reply("\n\n".join(replies))

        return await self._execute_single_action(chat_id, result.action, result.params, result.user_reply)

    async def _execute_single_action(
        self,
        chat_id: int,
        action: AIAction,
        params: Dict[str, Any],
        user_reply: Optional[str] = None
    ) -> Reply:
        if action == AIAction.CHAT:
            reply_text = params.get("reply") or user_reply or "Чем я могу вам помочь?"
            return Reply(reply_text)

        if action == AIAction.CREATE_TASK:
            title = params.get("title", "Задача")
            due_date = params.get("due_date")
            due_time = params.get("due_time")
            is_reminder = bool(params.get("is_reminder", False))

            task_id = await self.db.add_task(
                user_id=chat_id,
                title=title,
                due_date=due_date,
                due_time=due_time,
                is_reminder=is_reminder
            )
            self._last_event[chat_id] = {
                "id": task_id,
                "title": title,
                "date": due_date,
                "time": due_time,
                "type": "task",
                "is_reminder": is_reminder
            }

            date_info = f" на {due_date}" if due_date else ""
            time_info = f" в {due_time}" if due_time else ""
            prefix = "Напоминание установлено" if is_reminder else "Задача добавлена"
            if title.strip().lower() in ["задача", "напоминание", "task"]:
                return Reply(f"{prefix}{date_info}{time_info}.")
            return Reply(f"{prefix}: «{title}»{date_info}{time_info}.")

        if action == AIAction.CREATE_MEETING:
            title = params.get("title", "Встреча")
            start_date = params.get("start_date")
            start_time = params.get("start_time")
            duration = int(params.get("duration_minutes", 60))
            participants = params.get("participants")

            conflict = await self.db.check_meeting_conflict(chat_id, start_date, start_time)
            meeting_id = await self.db.add_meeting(
                user_id=chat_id,
                title=title,
                start_date=start_date,
                start_time=start_time,
                duration_minutes=duration,
                participants=participants
            )
            self._last_event[chat_id] = {
                "id": meeting_id,
                "title": title,
                "date": start_date,
                "time": start_time,
                "type": "meeting"
            }

            if title.strip().lower() in ["встреча", "созвон", "meeting"]:
                response_text = f"Встреча назначена на {start_date} в {start_time}."
            else:
                response_text = f"Встреча «{title}» назначена на {start_date} в {start_time}."
            if conflict:
                response_text += f"\nВнимание: в это же время уже стоит «{conflict.get('title')}»."
            return Reply(response_text)

        if action == AIAction.GET_SCHEDULE:
            tz_str = await self.db.get_user_timezone(chat_id)
            try:
                from zoneinfo import ZoneInfo
                now_date = datetime.datetime.now(ZoneInfo(tz_str)).date()
            except Exception:
                now_date = datetime.datetime.now().date()
            now_str = str(now_date)
            start_date = params.get("start_date") or now_str
            end_date = params.get("end_date") or start_date
            filter_type = params.get("filter_type", "all")

            data = await self.db.get_schedule(chat_id, start_date, end_date, filter_type)
            tasks = data.get("tasks", [])
            meetings = data.get("meetings", [])

            if not tasks and not meetings:
                if start_date == now_str and end_date == now_str:
                    period_text = f"сегодня ({start_date})"
                elif start_date == end_date:
                    period_text = start_date
                else:
                    period_text = f"период с {start_date} по {end_date}"

                target = "нет активных встреч и задач (прошедшие события перемещены в архив)"
                if filter_type == "meetings":
                    target = "нет запланированных встреч"
                elif filter_type == "tasks":
                    target = "нет активных задач"

                return Reply(f"На {period_text} {target}.")

            lines: List[str] = []
            if start_date == now_str and end_date == now_str:
                period_str = f"сегодня, {start_date}"
            elif start_date == end_date:
                period_str = start_date
            else:
                period_str = f"{start_date} — {end_date}"
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

        if action == AIAction.GET_ARCHIVE or (action == AIAction.GET_SCHEDULE and params.get("filter_type") == "archive"):
            text_view = await self.get_archive_view(chat_id)
            return Reply(text_view)

        if action == AIAction.SEARCH_RECORDS:
            query = params.get("query", "").strip()
            record_type = params.get("record_type", "all")

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
                archived_tag = " [Архив]" if m.get("status") == "archived" else ""
                lines.append(f"- [{kind}]{archived_tag} {m.get('title')}{date_str}")

            if matches:
                top_m = matches[0]
                self._last_event[chat_id] = {
                    "id": top_m.get("id"),
                    "title": top_m.get("title"),
                    "date": top_m.get("date"),
                    "time": top_m.get("time"),
                    "type": top_m.get("type")
                }

            return Reply("\n".join(lines))

        if action == AIAction.RESCHEDULE_RECORD:
            target = params.get("target", "last")
            new_date = params.get("new_date")
            new_time = params.get("new_time")

            if not new_date and not new_time:
                self._pending[chat_id] = PendingClarification(
                    slot="time",
                    draft={"action": "reschedule_record", "target": target}
                )
                return Reply("На какую дату или время перенести?")

            record = self._last_event.get(chat_id)
            if not record or (target in ("meeting", "task") and record.get("type") != target):
                db_record = await self.db.get_latest_record(chat_id, target)
                if db_record:
                    record = db_record

            if not record:
                return Reply("Не удалось найти предыдущую запись для переноса. Уточните, какую именно встречу или задачу вы хотите перенести.")

            rec_type = record.get("type", "meeting")
            title = record.get("title", "Запись")
            rec_id = record.get("id")

            if rec_type == "meeting":
                cur_date = record.get("date") or record.get("start_date")
                cur_time = record.get("time") or record.get("start_time")
                target_date = new_date or cur_date
                target_time = new_time or cur_time

                if not target_date or not target_time:
                    self._pending[chat_id] = PendingClarification(
                        slot="time" if not target_time else "date",
                        draft={"action": "reschedule_record", "target": "meeting", "new_date": target_date, "new_time": target_time}
                    )
                    return Reply("Уточните дату и время переноса.")

                conflict = await self.db.check_meeting_conflict(chat_id, target_date, target_time, exclude_id=rec_id)
                await self.db.update_meeting_time(chat_id, rec_id, target_date, target_time)

                self._last_event[chat_id] = {
                    "id": rec_id,
                    "title": title,
                    "date": target_date,
                    "time": target_time,
                    "type": "meeting"
                }

                conflict_note = f"\nВнимание: в это же время уже стоит «{conflict.get('title')}»." if conflict else ""
                return Reply(f"Встреча «{title}» успешно перенесена на {target_date} в {target_time}.{conflict_note}")

            else:
                cur_date = record.get("date") or record.get("due_date")
                cur_time = record.get("time") or record.get("due_time")
                target_date = new_date or cur_date
                target_time = new_time or cur_time

                await self.db.update_task_time(chat_id, rec_id, target_date, target_time)

                self._last_event[chat_id] = {
                    "id": rec_id,
                    "title": title,
                    "date": target_date,
                    "time": target_time,
                    "type": "task"
                }

                date_part = f" на {target_date}" if target_date else ""
                time_part = f" в {target_time}" if target_time else ""
                return Reply(f"Задача «{title}» успешно перенесена{date_part}{time_part}.")

        if action == AIAction.COMPLETE_RECORD:
            query = params.get("query")
            record = None
            if query:
                records = await self.db.get_all_records_for_search(chat_id, "tasks")
                if records:
                    matches = self.search_engine.rank_records(query, records, top_k=1)
                    if matches:
                        record = matches[0]

            if not record:
                record = self._last_event.get(chat_id)
                if not record or record.get("type") != "task":
                    record = await self.db.get_latest_record(chat_id, "task")

            if not record or record.get("type") != "task":
                return Reply("Не удалось найти задачу для отметки выполненной. Уточните название задачи.")

            rec_id = record["id"]
            title = record.get("title", "Задача")
            success = await self.db.mark_task_completed(chat_id, rec_id)
            if success:
                self._last_event[chat_id] = {**record, "status": "completed"}
                return Reply(f"Задача «{title}» отмечена как выполненная! ✅")
            return Reply(f"Не удалось обновить статус задачи «{title}».")

        if action == AIAction.DELETE_RECORD:
            target = params.get("target", "last")
            query = params.get("query")
            record = None

            if query:
                records = await self.db.get_all_records_for_search(chat_id, target if target in ("meeting", "task") else "all")
                if records:
                    matches = self.search_engine.rank_records(query, records, top_k=1)
                    if matches:
                        record = matches[0]

            if not record:
                record = self._last_event.get(chat_id)
                if not record or (target in ("meeting", "task") and record.get("type") != target):
                    record = await self.db.get_latest_record(chat_id, target)

            if not record:
                return Reply("Не удалось найти запись для удаления. Уточните название задачи или встречи.")

            rec_type = record.get("type", "task")
            rec_id = record["id"]
            title = record.get("title", "Запись")

            success = await self.db.delete_record(chat_id, rec_type, rec_id)
            if success:
                if self._last_event.get(chat_id, {}).get("id") == rec_id:
                    self._last_event.pop(chat_id, None)
                if rec_type == "meeting":
                    return Reply(f"Встреча «{title}» успешно отменена и удалена. 🗑️")
                return Reply(f"Задача «{title}» успешно удалена. 🗑️")
            return Reply(f"Не удалось удалить запись «{title}».")

        if action == AIAction.UPDATE_RECORD:
            target = params.get("target", "last")
            new_title = params.get("new_title", "").strip()
            query = params.get("query")

            if not new_title:
                return Reply("Укажите новое название для задачи или встречи.")

            record = None
            if query:
                records = await self.db.get_all_records_for_search(chat_id, target if target in ("meeting", "task") else "all")
                if records:
                    matches = self.search_engine.rank_records(query, records, top_k=1)
                    if matches:
                        record = matches[0]

            if not record:
                record = self._last_event.get(chat_id)
                if not record or (target in ("meeting", "task") and record.get("type") != target):
                    record = await self.db.get_latest_record(chat_id, target)

            if not record:
                return Reply("Не удалось найти запись для изменения. Уточните название задачи или встречи.")

            rec_type = record.get("type", "task")
            rec_id = record["id"]
            old_title = record.get("title", "")

            success = await self.db.update_record_title(chat_id, rec_type, rec_id, new_title)
            if success:
                self._last_event[chat_id] = {**record, "title": new_title}
                kind = "Встреча" if rec_type == "meeting" else "Задача"
                return Reply(f"{kind} «{old_title}» переименована в «{new_title}». ✏️")
            return Reply(f"Не удалось обновить запись «{old_title}».")

        if action == AIAction.ASK_CLARIFICATION:
            prev_draft = self._pending[chat_id].draft if chat_id in self._pending else {}
            new_draft = {**prev_draft, **params.get("draft_data", {})}
            self._pending[chat_id] = PendingClarification(
                slot=params.get("missing_slot"),
                draft=new_draft,
            )
            return Reply(params.get("question", DEFAULT_QUESTION))

        logger.info("Unknown action=%s params=%s", action.value, params)
        return Reply("Запрос принят, но действие не определено.")

    async def get_archive_view(self, chat_id: int) -> str:
        data = await self.db.get_archive(chat_id, limit=15)
        meetings = data.get("meetings", [])
        tasks = data.get("tasks", [])

        if not meetings and not tasks:
            return "📦 Архив пуст. Прошедшие встречи и завершенные задачи сохраняются здесь."

        lines = ["📦 Архив событий:"]
        if meetings:
            lines.append("\nПрошедшие встречи:")
            for m in meetings:
                d = m.get("start_date") or ""
                t = m.get("start_time") or ""
                title = m.get("title")
                lines.append(f"• {d} {t} — {title}")

        if tasks:
            lines.append("\nАрхивные задачи:")
            for t in tasks:
                status = "[x]" if t.get("status") in ("completed", "archived") else "[ ]"
                d_str = f" ({t.get('due_date')})" if t.get("due_date") else ""
                lines.append(f"• {status} {t.get('title')}{d_str}")

        return "\n".join(lines)

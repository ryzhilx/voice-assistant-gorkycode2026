from typing import Any, Dict
from app.agent.schemas import ToolDefinition, ToolExecutionResult, ToolParameter
from app.agent.tools.base import BaseTool
from app.agent.tools.validation import (
    ToolValidationError,
    normalize_date,
    normalize_target,
    normalize_time,
)

class RescheduleRecordTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="reschedule_record",
            description="Переносит или меняет дату/время существующей встречи, задачи или недавнего напоминания.",
            parameters={
                "new_time": ToolParameter(
                    type="string",
                    description="Новое время в формате 24h HH:MM."
                ),
                "new_date": ToolParameter(
                    type="string",
                    description="Новая дата в формате YYYY-MM-DD."
                ),
                "target": ToolParameter(
                    type="string",
                    description="Тип переноса: last (последнее созданное/упомянутое событие), meeting, task.",
                    enum=["last", "meeting", "task"]
                ),
                "query": ToolParameter(
                    type="string",
                    description="Название или ключевые слова записи, если переносится конкретное событие."
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        try:
            target = normalize_target(kwargs.get("target"), "last")
            new_date = normalize_date(kwargs.get("new_date"))
            new_time = normalize_time(kwargs.get("new_time"))
        except ToolValidationError as exc:
            return ToolExecutionResult(tool_name="reschedule_record", success=False, output=str(exc))
        query = str(kwargs.get("query") or "").strip()

        if not new_date and not new_time:
            return ToolExecutionResult(
                tool_name="reschedule_record",
                success=False,
                output="Уточните, на какую именно дату или время вы хотите перенести запись?"
            )

        record = None
        if query:
            records = await self.db.get_all_records_for_search(chat_id, target if target in ("meeting", "task") else "all")
            if records:
                active_recs = [r for r in records if r.get("status") not in ("completed", "archived")]
                cands = active_recs if active_recs else records
                matches = await self.search_engine.rank_records_async(query, cands, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = self.last_event_store.get(chat_id)
            if not record or (target in ("meeting", "task") and record.get("type") != target):
                db_record = await self.db.get_latest_record(chat_id, target)
                if db_record:
                    record = db_record

        if not record:
            return ToolExecutionResult(
                tool_name="reschedule_record",
                success=False,
                output="Не удалось найти предыдущую запись для переноса. Уточните название встречи или задачи."
            )

        rec_type = record.get("type", "meeting")
        title = record.get("title", "Запись")
        rec_id = record.get("id")

        if rec_type == "meeting":
            cur_date = record.get("date") or record.get("start_date")
            cur_time = record.get("time") or record.get("start_time")
            target_date = new_date or cur_date
            target_time = new_time or cur_time

            rec_val = record.get("recurrence")
            duration = int(record.get("duration_minutes") or 60)
            conflict = await self.db.check_meeting_conflict(
                chat_id,
                target_date,
                target_time,
                exclude_id=rec_id,
                recurrence=rec_val,
                duration_minutes=duration,
            )
            await self.db.update_meeting_time(chat_id, rec_id, target_date, target_time)

            self.last_event_store[chat_id] = {
                "id": rec_id,
                "title": title,
                "date": target_date,
                "time": target_time,
                "type": "meeting",
                "recurrence": rec_val,
                "duration_minutes": duration,
                "participants": record.get("participants")
            }

            conflict_note = f"\nВнимание: в это же время уже стоит «{conflict.get('title')}»." if conflict else ""
            return ToolExecutionResult(
                tool_name="reschedule_record",
                success=True,
                output=f"Встреча «{title}» успешно перенесена на {target_date} в {target_time}.{conflict_note}",
                data={"id": rec_id, "new_date": target_date, "new_time": target_time}
            )

        cur_date = record.get("date") or record.get("due_date")
        cur_time = record.get("time") or record.get("due_time")
        target_date = new_date or cur_date
        target_time = new_time or cur_time

        await self.db.update_task_time(chat_id, rec_id, target_date, target_time)

        self.last_event_store[chat_id] = {
            "id": rec_id,
            "title": title,
            "date": target_date,
            "time": target_time,
            "type": "task"
        }

        date_part = f" на {target_date}" if target_date else ""
        time_part = f" в {target_time}" if target_time else ""
        label = "Напоминание" if record.get("is_reminder") else "Задача"
        res_verb = "перенесено" if record.get("is_reminder") else "перенесена"

        return ToolExecutionResult(
            tool_name="reschedule_record",
            success=True,
            output=f"{label} «{title}» успешно {res_verb}{date_part}{time_part}.",
            data={"id": rec_id, "new_date": target_date, "new_time": target_time}
        )

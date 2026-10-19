import datetime
from typing import Any, Dict
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.formatters import format_recurrence
from app.orchestrator.handlers.base import BaseActionHandler
from app.storage.db import Database

class CreateTaskHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        title = params.get("title", "Задача")
        due_date = params.get("due_date")
        due_time = params.get("due_time")
        is_reminder = bool(params.get("is_reminder", False))
        recurrence = params.get("recurrence")

        task_id = await ctx.db.add_task(
            user_id=ctx.chat_id,
            title=title,
            due_date=due_date,
            due_time=due_time,
            is_reminder=is_reminder,
            recurrence=recurrence
        )
        ctx.last_event[ctx.chat_id] = {
            "id": task_id,
            "title": title,
            "date": due_date,
            "time": due_time,
            "type": "task",
            "is_reminder": is_reminder,
            "recurrence": recurrence
        }

        date_info = f" на {due_date}" if due_date else ""
        time_info = f" в {due_time}" if due_time else ""
        rec_badge = f" (🔄 {format_recurrence(recurrence)})" if recurrence else ""
        prefix = "Напоминание установлено" if is_reminder else "Задача добавлена"
        if title.strip().lower() in ["задача", "напоминание", "task"]:
            return Reply(f"{prefix}{date_info}{time_info}{rec_badge}.")
        return Reply(f"{prefix}: «{title}»{date_info}{time_info}{rec_badge}.")

class CompleteRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        query = params.get("query")
        record = None
        if query:
            records = await ctx.db.get_all_records_for_search(ctx.chat_id, "tasks")
            if records:
                pending_records = [r for r in records if r.get("status") not in ("completed", "archived")]
                candidates = pending_records if pending_records else records
                matches = ctx.search_engine.rank_records(query, candidates, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = ctx.last_event.get(ctx.chat_id)
            if not record or record.get("type") != "task":
                record = await ctx.db.get_latest_record(ctx.chat_id, "task")

        if not record or record.get("type") != "task":
            return Reply("Не удалось найти задачу для отметки выполненной. Уточните название задачи.")

        rec_id = record["id"]
        title = record.get("title", "Задача")
        recurrence = record.get("recurrence")
        success = await ctx.db.mark_task_completed(ctx.chat_id, rec_id)
        if success:
            if recurrence:
                today_str = datetime.date.today().isoformat()
                next_d = Database.calculate_next_occurrence(record.get("date") or today_str, recurrence, from_date=today_str)
                ctx.last_event[ctx.chat_id] = {**record, "date": next_d, "status": "pending"}
                return Reply(f"Задача «{title}» выполнена! Следующее повторение запланировано на {next_d}. ✅")
            ctx.last_event[ctx.chat_id] = {**record, "status": "completed"}
            return Reply(f"Задача «{title}» отмечена как выполненная! ✅")
        return Reply(f"Не удалось обновить статус задачи «{title}».")

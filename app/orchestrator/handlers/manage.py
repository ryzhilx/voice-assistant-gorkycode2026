from typing import Any, Dict
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class DeleteRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        target = params.get("target", "last")
        query = params.get("query")
        record = None

        if query:
            records = await ctx.db.get_all_records_for_search(ctx.chat_id, target if target in ("meeting", "task") else "all")
            if records:
                matches = ctx.search_engine.rank_records(query, records, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = ctx.last_event.get(ctx.chat_id)
            if not record or (target in ("meeting", "task") and record.get("type") != target):
                record = await ctx.db.get_latest_record(ctx.chat_id, target)

        if not record:
            return Reply("Не удалось найти запись для удаления. Уточните название задачи или встречи.")

        rec_type = record.get("type", "task")
        rec_id = record["id"]
        title = record.get("title", "Запись")

        success = await ctx.db.delete_record(ctx.chat_id, rec_type, rec_id)
        if success:
            if ctx.last_event.get(ctx.chat_id, {}).get("id") == rec_id:
                ctx.last_event.pop(ctx.chat_id, None)
            if rec_type == "meeting":
                return Reply(f"Встреча «{title}» успешно отменена и удалена. 🗑️")
            return Reply(f"Задача «{title}» успешно удалена. 🗑️")
        return Reply(f"Не удалось удалить запись «{title}».")

class UpdateRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        target = params.get("target", "last")
        new_title = params.get("new_title", "").strip()
        query = params.get("query")

        if not new_title:
            return Reply("Укажите новое название для задачи или встречи.")

        record = None
        if query:
            records = await ctx.db.get_all_records_for_search(ctx.chat_id, target if target in ("meeting", "task") else "all")
            if records:
                matches = ctx.search_engine.rank_records(query, records, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = ctx.last_event.get(ctx.chat_id)
            if not record or (target in ("meeting", "task") and record.get("type") != target):
                record = await ctx.db.get_latest_record(ctx.chat_id, target)

        if not record:
            return Reply("Не удалось найти запись для изменения. Уточните название задачи или встречи.")

        rec_type = record.get("type", "task")
        rec_id = record["id"]
        old_title = record.get("title", "")

        success = await ctx.db.update_record_title(ctx.chat_id, rec_type, rec_id, new_title)
        if success:
            ctx.last_event[ctx.chat_id] = {**record, "title": new_title}
            kind = "Встреча" if rec_type == "meeting" else "Задача"
            return Reply(f"{kind} «{old_title}» переименована в «{new_title}». ✏️")
        return Reply(f"Не удалось обновить запись «{old_title}».")

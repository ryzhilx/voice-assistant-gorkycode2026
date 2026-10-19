from typing import Any, Dict
from app.orchestrator.context import HandlerContext, PendingClarification, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class RescheduleRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        target = params.get("target", "last")
        new_date = params.get("new_date")
        new_time = params.get("new_time")
        query = params.get("query")

        if not new_date and not new_time:
            draft_d = {"action": "reschedule_record", "target": target}
            if query:
                draft_d["query"] = query
            ctx.pending[ctx.chat_id] = PendingClarification(
                slot="time",
                draft=draft_d
            )
            return Reply("На какую дату или время перенести?")

        record = None
        if query:
            records = await ctx.db.get_all_records_for_search(ctx.chat_id, target if target in ("meeting", "task") else "all")
            if records:
                active_recs = [r for r in records if r.get("status") not in ("completed", "archived")]
                cands = active_recs if active_recs else records
                matches = ctx.search_engine.rank_records(query, cands, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = ctx.last_event.get(ctx.chat_id)
            if not record or (target in ("meeting", "task") and record.get("type") != target):
                db_record = await ctx.db.get_latest_record(ctx.chat_id, target)
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
                ctx.pending[ctx.chat_id] = PendingClarification(
                    slot="time" if not target_time else "date",
                    draft={"action": "reschedule_record", "target": "meeting", "new_date": target_date, "new_time": target_time}
                )
                return Reply("Уточните дату и время переноса.")

            rec_val = record.get("recurrence")
            conflict = await ctx.db.check_meeting_conflict(ctx.chat_id, target_date, target_time, exclude_id=rec_id, recurrence=rec_val)
            await ctx.db.update_meeting_time(ctx.chat_id, rec_id, target_date, target_time)

            ctx.last_event[ctx.chat_id] = {
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

            await ctx.db.update_task_time(ctx.chat_id, rec_id, target_date, target_time)

            ctx.last_event[ctx.chat_id] = {
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
            return Reply(f"{label} «{title}» успешно {res_verb}{date_part}{time_part}.")

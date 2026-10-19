from typing import Any, Dict
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.formatters import format_recurrence
from app.orchestrator.handlers.base import BaseActionHandler

class CreateMeetingHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        title = params.get("title", "Встреча")
        start_date = params.get("start_date")
        start_time = params.get("start_time")
        duration = int(params.get("duration_minutes", 60))
        participants = params.get("participants")
        recurrence = params.get("recurrence")

        conflict = await ctx.db.check_meeting_conflict(ctx.chat_id, start_date, start_time, recurrence=recurrence)
        meeting_id = await ctx.db.add_meeting(
            user_id=ctx.chat_id,
            title=title,
            start_date=start_date,
            start_time=start_time,
            duration_minutes=duration,
            participants=participants,
            recurrence=recurrence
        )
        ctx.last_event[ctx.chat_id] = {
            "id": meeting_id,
            "title": title,
            "date": start_date,
            "time": start_time,
            "type": "meeting",
            "recurrence": recurrence
        }

        rec_badge = f" (🔄 {format_recurrence(recurrence)})" if recurrence else ""
        if title.strip().lower() in ["встреча", "созвон", "meeting"]:
            response_text = f"Встреча назначена на {start_date} в {start_time}{rec_badge}."
        else:
            response_text = f"Встреча «{title}» назначена на {start_date} в {start_time}{rec_badge}."
        if conflict:
            response_text += f"\nВнимание: в это же время уже стоит «{conflict.get('title')}»."
        return Reply(response_text)

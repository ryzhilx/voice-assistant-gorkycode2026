import datetime
from typing import Any, Dict, List
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.formatters import format_recurrence
from app.orchestrator.handlers.base import BaseActionHandler
from app.storage.db import Database

async def format_archive_view(db: Database, chat_id: int, filter_type: str = "all") -> str:
    if filter_type not in ("all", "meetings", "tasks"):
        filter_type = "all"
    data = await db.get_archive(chat_id, filter_type=filter_type, limit=15)
    meetings = data.get("meetings", [])
    tasks = data.get("tasks", [])

    if not meetings and not tasks:
        if filter_type == "meetings":
            return "📦 В архиве нет прошедших встреч."
        if filter_type == "tasks":
            return "📦 В архиве нет завершенных задач."
        return "📦 Архив пуст. Прошедшие встречи и завершенные задачи сохраняются здесь."

    header = "📦 Архив событий:"
    if filter_type == "meetings":
        header = "📦 Архив встреч:"
    elif filter_type == "tasks":
        header = "📦 Архив задач:"

    lines = [header]
    if meetings:
        if filter_type == "all":
            lines.append("\nПрошедшие встречи:")
        for m in meetings:
            d = m.get("start_date") or ""
            t = m.get("start_time") or ""
            title = m.get("title")
            lines.append(f"• {d} {t} — {title}")

    if tasks:
        if filter_type == "all":
            lines.append("\nАрхивные задачи:")
        for t in tasks:
            status = "[x]" if t.get("status") in ("completed", "archived") else "[ ]"
            d_str = f" ({t.get('due_date')})" if t.get("due_date") else ""
            lines.append(f"• {status} {t.get('title')}{d_str}")

    return "\n".join(lines)

class GetScheduleHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        f_type = params.get("filter_type", "all")
        if f_type == "archive":
            text_view = await format_archive_view(ctx.db, ctx.chat_id, filter_type="all")
            return Reply(text_view)

        tz_str = await ctx.db.get_user_timezone(ctx.chat_id)
        try:
            from zoneinfo import ZoneInfo
            now_date = datetime.datetime.now(ZoneInfo(tz_str)).date()
        except Exception:
            now_date = datetime.datetime.now().date()
        now_str = str(now_date)
        start_date = params.get("start_date") or now_str
        end_date = params.get("end_date") or start_date
        filter_type = f_type

        data = await ctx.db.get_schedule(ctx.chat_id, start_date, end_date, filter_type)
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
                rec_badge = f" (🔄 {format_recurrence(m.get('recurrence'))})" if m.get("recurrence") else ""
                lines.append(f"- {t} {title}{rec_badge}")

        if tasks:
            lines.append("\nЗадачи:")
            for t in tasks:
                status = "[x]" if t.get("status") == "completed" else "[ ]"
                tm = f" (до {t.get('due_time')})" if t.get("due_time") else ""
                rec_badge = f" (🔄 {format_recurrence(t.get('recurrence'))})" if t.get("recurrence") else ""
                lines.append(f"{status} {t.get('title')}{tm}{rec_badge}")

        return Reply("\n".join(lines))

class GetArchiveHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        f_type = params.get("filter_type", "all")
        if f_type == "archive":
            f_type = "all"
        text_view = await format_archive_view(ctx.db, ctx.chat_id, filter_type=f_type)
        return Reply(text_view)

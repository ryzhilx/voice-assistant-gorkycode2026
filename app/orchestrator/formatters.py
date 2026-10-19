from typing import Optional
from app.storage.db import Database

def format_recurrence(recurrence: Optional[str]) -> str:
    if not recurrence:
        return ""
    mapping = {
        "daily": "ежедневно",
        "weekdays": "по будням",
        "weekends": "по выходным",
        "weekly": "еженедельно",
        "weekly:mon": "каждый понедельник",
        "weekly:tue": "каждый вторник",
        "weekly:wed": "каждую среду",
        "weekly:thu": "каждый четверг",
        "weekly:fri": "каждую пятницу",
        "weekly:sat": "каждую субботу",
        "weekly:sun": "каждое воскресенье",
        "monthly": "ежемесячно"
    }
    return mapping.get(recurrence, recurrence)

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

from typing import Optional

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

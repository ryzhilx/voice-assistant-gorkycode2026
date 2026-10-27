import datetime as dt
import re
from typing import Any, Optional
from zoneinfo import ZoneInfo


class ToolValidationError(ValueError):
    pass


RECURRENCE_VALUES = {
    "daily",
    "weekdays",
    "weekends",
    "weekly",
    "weekly:mon",
    "weekly:tue",
    "weekly:wed",
    "weekly:thu",
    "weekly:fri",
    "weekly:sat",
    "weekly:sun",
    "monthly",
}

RECURRENCE_ALIASES = {
    "ежедневно": "daily",
    "каждый день": "daily",
    "каждодневно": "daily",
    "по будням": "weekdays",
    "будни": "weekdays",
    "по выходным": "weekends",
    "выходные": "weekends",
    "еженедельно": "weekly",
    "каждую неделю": "weekly",
    "ежемесячно": "monthly",
    "каждый месяц": "monthly",
}

DAY_ALIASES = {
    "mon": "mon",
    "monday": "mon",
    "пн": "mon",
    "понедельник": "mon",
    "каждый понедельник": "mon",
    "по понедельникам": "mon",
    "tue": "tue",
    "tuesday": "tue",
    "вт": "tue",
    "вторник": "tue",
    "каждый вторник": "tue",
    "по вторникам": "tue",
    "wed": "wed",
    "wednesday": "wed",
    "ср": "wed",
    "среда": "wed",
    "каждую среду": "wed",
    "по средам": "wed",
    "thu": "thu",
    "thursday": "thu",
    "чт": "thu",
    "четверг": "thu",
    "каждый четверг": "thu",
    "по четвергам": "thu",
    "fri": "fri",
    "friday": "fri",
    "пт": "fri",
    "пятница": "fri",
    "каждую пятницу": "fri",
    "по пятницам": "fri",
    "sat": "sat",
    "saturday": "sat",
    "сб": "sat",
    "суббота": "sat",
    "каждую субботу": "sat",
    "по субботам": "sat",
    "sun": "sun",
    "sunday": "sun",
    "вс": "sun",
    "воскресенье": "sun",
    "каждое воскресенье": "sun",
    "по воскресеньям": "sun",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("ё", "е"))


def normalize_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = _clean(value)
    if raw in {"true", "1", "yes", "да", "истина"}:
        return True
    if raw in {"false", "0", "no", "нет", "ложь"}:
        return False
    return default


def normalize_title(value: Any, default: str) -> str:
    title = str(value or "").strip()
    return title or default


def normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()

    raw = str(value).strip()
    if not raw:
        return None

    candidate = raw.split("T", 1)[0].split(" ", 1)[0]
    try:
        return dt.date.fromisoformat(candidate).isoformat()
    except ValueError:
        pass

    for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue

    raise ToolValidationError("Дата должна быть в формате YYYY-MM-DD.")


def normalize_time(value: Any) -> Optional[str]:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    if "T" in raw:
        raw = raw.split("T", 1)[1]
    elif " " in raw:
        raw = raw.split(" ", 1)[1]

    raw = raw.split("+", 1)[0].rstrip("Z")
    raw = raw.replace(".", ":")
    match = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$", raw)
    if not match:
        raise ToolValidationError("Время должно быть в формате HH:MM.")

    hours = int(match.group(1))
    minutes = int(match.group(2))
    if hours > 23 or minutes > 59:
        raise ToolValidationError("Время должно быть в диапазоне 00:00–23:59.")

    return f"{hours:02d}:{minutes:02d}"


def normalize_duration(value: Any, default: int = 60) -> int:
    if value is None or value == "":
        return default
    try:
        duration = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolValidationError("Длительность встречи должна быть числом минут.") from exc
    if duration < 1 or duration > 24 * 60:
        raise ToolValidationError("Длительность встречи должна быть от 1 до 1440 минут.")
    return duration


def normalize_recurrence(value: Any) -> Optional[str]:
    if value is None:
        return None

    raw = _clean(value)
    if not raw:
        return None

    if raw in RECURRENCE_VALUES:
        return raw

    if raw in RECURRENCE_ALIASES:
        return RECURRENCE_ALIASES[raw]

    if raw.startswith("weekly:"):
        day = raw.split(":", 1)[1].strip()
        if day in DAY_ALIASES:
            return f"weekly:{DAY_ALIASES[day]}"
        if day.isdigit() and 0 <= int(day) <= 6:
            return f"weekly:{['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][int(day)]}"

    if raw in DAY_ALIASES:
        return f"weekly:{DAY_ALIASES[raw]}"

    raise ToolValidationError(
        "Периодичность должна быть одной из: daily, weekdays, weekends, weekly, weekly:mon…weekly:sun, monthly."
    )


def normalize_filter(value: Any, allowed: set, default: str = "all") -> str:
    if value is None:
        return default
    raw = _clean(value)
    if not raw:
        return default

    aliases = {
        "все": "all",
        "всё": "all",
        "встречи": "meetings",
        "встреч": "meetings",
        "задачи": "tasks",
        "задач": "tasks",
        "meeting": "meetings",
        "task": "tasks",
    }
    mapped = aliases.get(raw, raw)
    if mapped not in allowed:
        raise ToolValidationError(f"Недопустимый фильтр: {value}.")
    return mapped


def normalize_target(value: Any, default: str = "last") -> str:
    if value is None:
        return default
    raw = _clean(value)
    if not raw:
        return default
    aliases = {
        "last": "last",
        "последняя": "last",
        "последнее": "last",
        "последнюю": "last",
        "задача": "task",
        "задачу": "task",
        "встреча": "meeting",
        "встречу": "meeting",
        "task": "task",
        "meeting": "meeting",
    }
    mapped = aliases.get(raw, raw)
    if mapped not in ("last", "task", "meeting"):
        raise ToolValidationError("Тип записи должен быть last, task или meeting.")
    return mapped


def today_in_timezone(timezone: str) -> str:
    try:
        return dt.datetime.now(ZoneInfo(timezone)).date().isoformat()
    except Exception:
        return dt.date.today().isoformat()

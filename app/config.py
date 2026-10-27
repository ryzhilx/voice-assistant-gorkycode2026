import os
from dataclasses import dataclass, field
from typing import List, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_user_ids(name: str) -> Tuple[int, ...]:
    raw = os.getenv(name, "")
    result: List[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return tuple(result)


def _valid_timezone(name: str, default: str = "Europe/Moscow") -> str:
    value = os.getenv(name, default)
    try:
        ZoneInfo(value)
        return value
    except Exception:
        return default


@dataclass
class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    yandex_api_key: str = os.getenv("YANDEX_API_KEY", "")
    yandex_folder_id: str = os.getenv("YANDEX_FOLDER_ID", "")
    app_timezone: str = field(default_factory=lambda: _valid_timezone("APP_TIMEZONE"))
    database_path: str = os.getenv("DATABASE_PATH", "assistant.db")
    allowed_user_ids: Tuple[int, ...] = field(default_factory=lambda: _env_user_ids("ALLOWED_USER_IDS"))
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 20))
    max_voice_duration_seconds: int = field(default_factory=lambda: _env_int("MAX_VOICE_DURATION_SECONDS", 30))
    max_voice_size_bytes: int = field(default_factory=lambda: _env_int("MAX_VOICE_SIZE_BYTES", 1_000_000))


settings = Settings()


def validate_settings() -> List[str]:
    missing: List[str] = []
    if not settings.telegram_bot_token or settings.telegram_bot_token == "mock_token":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not settings.yandex_api_key:
        missing.append("YANDEX_API_KEY")
    if not settings.yandex_folder_id:
        missing.append("YANDEX_FOLDER_ID")
    return missing

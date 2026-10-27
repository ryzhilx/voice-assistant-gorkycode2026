import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings


class AccessMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._events: Dict[int, Deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None) or data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        user_id = user.id
        if settings.allowed_user_ids and user_id not in settings.allowed_user_ids:
            await self._deny(event, "Доступ к боту ограничен.")
            return None

        if settings.rate_limit_per_minute > 0:
            now = time.monotonic()
            events = self._events[user_id]
            while events and now - events[0] > 60:
                events.popleft()
            if len(events) >= settings.rate_limit_per_minute:
                await self._deny(event, "Слишком много запросов. Попробуйте через минуту.")
                return None
            events.append(now)

        return await handler(event, data)

    async def _deny(self, event: TelegramObject, text: str) -> None:
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(text)

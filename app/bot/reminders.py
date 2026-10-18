import asyncio
import datetime
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.config import settings
from app.storage.db import Database

logger = logging.getLogger(__name__)


async def check_and_send_reminders(bot: Bot, db: Database, now: Optional[datetime.datetime] = None) -> int:
    current_dt = now or datetime.datetime.now()
    current_date = current_dt.strftime("%Y-%m-%d")
    current_time = current_dt.strftime("%H:%M")

    due_tasks = await db.get_due_tasks(current_date, current_time)
    due_meetings = await db.get_due_meetings(current_date, current_time)

    count = 0

    for task in due_tasks:
        task_id = task["id"]
        user_id = task["user_id"]
        title = task["title"]
        due_time = task["due_time"]
        is_reminder = bool(task["is_reminder"])

        if is_reminder:
            text = f"🔔 Напоминание: «{title}»!"
        else:
            text = f"⏰ Срок задачи: «{title}» ({due_time})."

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"task_done:{task_id}")]
            ]
        )

        try:
            await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
            count += 1
        except Exception as e:
            logger.warning("Failed to send task reminder %s to %s: %s", task_id, user_id, e)
        finally:
            await db.mark_task_reminder_sent(task_id)

    for meeting in due_meetings:
        meeting_id = meeting["id"]
        user_id = meeting["user_id"]
        title = meeting["title"]
        start_time = meeting["start_time"]
        participants = meeting.get("participants")

        text = f"📅 Напоминание о встрече: «{title}» в {start_time}."
        if participants:
            text += f"\nУчастники: {participants}"

        try:
            await bot.send_message(chat_id=user_id, text=text)
            count += 1
        except Exception as e:
            logger.warning("Failed to send meeting reminder %s to %s: %s", meeting_id, user_id, e)
        finally:
            await db.mark_meeting_reminder_sent(meeting_id)

    return count


async def start_reminder_worker(bot: Bot, db: Optional[Database] = None, interval: float = 15.0) -> None:
    database = db or Database(settings.database_path)
    logger.info("Reminder worker started with interval=%ss", interval)
    while True:
        try:
            await check_and_send_reminders(bot, database)
        except asyncio.CancelledError:
            logger.info("Reminder worker stopped")
            break
        except Exception as e:
            logger.exception("Error in reminder worker loop: %s", e)
        await asyncio.sleep(interval)

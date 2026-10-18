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
    if now is not None:
        current_dt = now
    else:
        try:
            from zoneinfo import ZoneInfo
            current_dt = datetime.datetime.now(ZoneInfo("Europe/Moscow"))
        except Exception:
            current_dt = datetime.datetime.now()

    current_date = current_dt.strftime("%Y-%m-%d")
    current_time = current_dt.strftime("%H:%M")

    due_tasks = await db.get_due_tasks(current_date, current_time)
    due_meetings = await db.get_due_meetings(current_date, current_time)

    count = 0

    for task in due_tasks:
        if now is None:
            user_tz = task.get("timezone") or "Europe/Moscow"
            try:
                from zoneinfo import ZoneInfo
                u_now = datetime.datetime.now(ZoneInfo(user_tz))
            except Exception:
                u_now = datetime.datetime.now()
            u_date = u_now.strftime("%Y-%m-%d")
            u_time = u_now.strftime("%H:%M")
            if not ((task["due_date"] < u_date) or (task["due_date"] == u_date and task["due_time"] <= u_time)):
                continue

        task_id = task["id"]
        user_id = task["user_id"]
        title = task["title"]
        due_time = task["due_time"]
        is_reminder = bool(task["is_reminder"])
        recurrence = task.get("recurrence")

        rec_note = " (повторяющаяся)" if recurrence else ""
        if is_reminder:
            text = f"🔔 Напоминание{rec_note}: «{title}»!"
        else:
            text = f"⏰ Срок задачи{rec_note}: «{title}» ({due_time})."

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
            if recurrence:
                from_d = u_date if now is None else current_date
                next_date = Database.calculate_next_occurrence(task["due_date"], recurrence, from_date=from_d)
                await db.advance_recurring_task(task_id, next_date)
            else:
                await db.mark_task_reminder_sent(task_id)

    for meeting in due_meetings:
        if now is None:
            user_tz = meeting.get("timezone") or "Europe/Moscow"
            try:
                from zoneinfo import ZoneInfo
                u_now = datetime.datetime.now(ZoneInfo(user_tz))
            except Exception:
                u_now = datetime.datetime.now()
            u_date = u_now.strftime("%Y-%m-%d")
            u_time = u_now.strftime("%H:%M")
            if not ((meeting["start_date"] < u_date) or (meeting["start_date"] == u_date and meeting["start_time"] <= u_time)):
                continue

        meeting_id = meeting["id"]
        user_id = meeting["user_id"]
        title = meeting["title"]
        start_time = meeting["start_time"]
        participants = meeting.get("participants")
        recurrence = meeting.get("recurrence")

        rec_note = " (повторяющаяся)" if recurrence else ""
        text = f"📅 Напоминание о встрече{rec_note}: «{title}» в {start_time}."
        if participants:
            text += f"\nУчастники: {participants}"

        try:
            await bot.send_message(chat_id=user_id, text=text)
            count += 1
        except Exception as e:
            logger.warning("Failed to send meeting reminder %s to %s: %s", meeting_id, user_id, e)
        finally:
            if recurrence:
                from_d = u_date if now is None else current_date
                next_date = Database.calculate_next_occurrence(meeting["start_date"], recurrence, from_date=from_d)
                await db.advance_recurring_meeting(meeting_id, next_date)
            else:
                await db.mark_meeting_reminder_sent(meeting_id)

    try:
        await db.archive_past_records()
    except Exception as e:
        logger.warning("Failed to auto-archive past records in reminder worker: %s", e)

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

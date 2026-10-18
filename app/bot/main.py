import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers import router
from app.bot.reminders import start_reminder_worker
from app.config import settings


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    worker_task = asyncio.create_task(start_reminder_worker(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())

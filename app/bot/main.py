import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.bot.handlers import router
from app.bot.reminders import start_reminder_worker
from app.config import settings


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню и старт"),
            BotCommand(command="today", description="Расписание на сегодня"),
            BotCommand(command="tasks", description="Список активных задач"),
            BotCommand(command="archive", description="Архив прошедших событий"),
            BotCommand(command="timezone", description="Настройка часового пояса"),
            BotCommand(command="help", description="Примеры команд и справка"),
            BotCommand(command="cancel", description="Отменить текущий шаг"),
        ])
    except Exception as e:
        logging.warning("Не удалось обновить список команд: %s", e)

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
        from app.bot.handlers import orchestrator, stt
        await orchestrator.aclose()
        await stt.aclose()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers import router
from app.config import settings


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

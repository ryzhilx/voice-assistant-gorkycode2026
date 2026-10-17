import io
import logging

from aiogram import Bot, Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.orchestrator.dialogue import DialogueOrchestrator
from app.speech.speechkit import YandexSpeechKitService

logger = logging.getLogger(__name__)

router = Router()
orchestrator = DialogueOrchestrator()
stt = YandexSpeechKitService()


@router.message(CommandStart())
async def cmd_start(message: Message):
    orchestrator.reset(message.chat.id)
    await message.answer("Привет! Отправь голосовое или текстовое сообщение, например: «Поставь встречу с Иваном завтра».")


@router.message(F.voice)
async def on_voice(message: Message, bot: Bot):
    buf = io.BytesIO()
    await bot.download(message.voice, destination=buf)
    text = await stt.speech_to_text(buf.getvalue())
    if not text:
        await message.answer("Не удалось распознать голосовое сообщение, попробуйте ещё раз.")
        return

    await message.answer(f"Распознано: «{text}»")
    await process_text(message, text)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message):
    await process_text(message, message.text)


async def process_text(message: Message, text: str):
    reply = await orchestrator.handle_text(message.chat.id, text)
    await message.answer(reply.text)

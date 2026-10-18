import asyncio
import io
import logging
from typing import Optional

from aiogram import Bot, Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, BufferedInputFile, CallbackQuery

from app.orchestrator.dialogue import DialogueOrchestrator
from app.speech.speechkit import YandexSpeechKitService

logger = logging.getLogger(__name__)

router = Router()
orchestrator = DialogueOrchestrator()
stt = YandexSpeechKitService()

async def _send_action_safe(bot: Optional[Bot], chat_id: int, action: str) -> None:
    if bot and hasattr(bot, "send_chat_action"):
        try:
            res = bot.send_chat_action(chat_id=chat_id, action=action)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass

@router.message(CommandStart())
async def cmd_start(message: Message):
    orchestrator.reset(message.chat.id)
    await message.answer("Привет! Отправь голосовое или текстовое сообщение, например: «Поставь встречу с Иваном завтра».")

@router.message(F.text.lower().in_(["/cancel", "отмена", "сброс"]))
async def cmd_cancel(message: Message):
    orchestrator.reset(message.chat.id)
    await message.answer("Контекст диалога сброшен. Чем могу помочь?")

@router.callback_query(F.data.startswith("task_done:"))
async def on_task_done(callback: CallbackQuery):
    try:
        task_id = int(callback.data.split(":")[1])
        success = await orchestrator.db.mark_task_completed(callback.from_user.id, task_id)
        if success:
            await callback.answer("Задача выполнена!")
            if callback.message and callback.message.text:
                await callback.message.edit_text(
                    f"{callback.message.text}\n\n✅ Отмечено как выполненное.",
                    reply_markup=None
                )
        else:
            await callback.answer("Задача уже выполнена или не найдена.")
    except Exception as e:
        logger.warning("Failed to complete task via callback: %s", e)
        await callback.answer("Ошибка при обновлении задачи.")

@router.message(F.voice)
async def on_voice(message: Message, bot: Optional[Bot] = None):
    await _send_action_safe(bot, message.chat.id, "record_voice")
    buf = io.BytesIO()
    if bot:
        await bot.download(message.voice, destination=buf)
    text = await stt.speech_to_text(buf.getvalue())
    if not text:
        await message.answer("Не удалось распознать голосовое сообщение, попробуйте ещё раз.")
        return

    await message.answer(f"Распознано: «{text}»")
    await _send_action_safe(bot, message.chat.id, "typing")
    try:
        reply = await orchestrator.handle_text(message.chat.id, text)
        await message.answer(reply.text)

        try:
            audio = await stt.text_to_speech(reply.text)
            if audio:
                await message.answer_voice(BufferedInputFile(audio, filename="voice.ogg"))
        except Exception as e:
            logger.warning("Failed to send voice response: %s", e)
    except Exception as e:
        logger.exception("Error processing voice message: %s", e)
        await message.answer("Произошла ошибка при обработке запроса. Попробуйте еще раз.")

@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Optional[Bot] = None):
    await _send_action_safe(bot, message.chat.id, "typing")
    try:
        reply = await orchestrator.handle_text(message.chat.id, message.text)
        await message.answer(reply.text)
    except Exception as e:
        logger.exception("Error processing text message: %s", e)
        await message.answer("Произошла ошибка при обработке запроса. Попробуйте еще раз.")

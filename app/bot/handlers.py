import io
import logging

from aiogram import Bot, Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.ai.llm_client import LLMOrchestrator
from app.ai.schemas import AIAction, AIResponse
from app.bot.states import Clarification
from app.speech.speechkit import YandexSpeechKitService

logger = logging.getLogger(__name__)

router = Router()
llm = LLMOrchestrator()
stt = YandexSpeechKitService()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет! Отправь голосовое или текстовое сообщение, например: «Поставь встречу с Иваном завтра».")


@router.message(F.voice)
async def on_voice(message: Message, bot: Bot, state: FSMContext):
    buf = io.BytesIO()
    await bot.download(message.voice, destination=buf)
    text = await stt.speech_to_text(buf.getvalue())
    if not text:
        await message.answer("Не удалось распознать голосовое сообщение, попробуйте ещё раз.")
        return

    await message.answer(f"Распознано: «{text}»")
    await process_text(message, state, text)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext):
    await process_text(message, state, message.text)


async def process_text(message: Message, state: FSMContext, text: str):
    data = await state.get_data()
    context = None
    if await state.get_state() == Clarification.waiting_slot.state:
        context = {"awaiting_slot": data.get("awaiting_slot"), "draft_data": data.get("draft_data", {})}

    result = await llm.parse_intent(text, context)
    await handle_result(message, state, result)


async def handle_result(message: Message, state: FSMContext, result: AIResponse):
    if result.action == AIAction.ASK_CLARIFICATION:
        await state.set_state(Clarification.waiting_slot)
        await state.update_data(
            awaiting_slot=result.params.get("missing_slot"),
            draft_data=result.params.get("draft_data", {}),
        )
        await message.answer(result.params.get("question", "Уточните, пожалуйста."))
        return

    await state.clear()
    
    logger.info("Parsed action=%s params=%s", result.action.value, result.params)
    await message.answer(f"[stage 1] action={result.action.value}\nparams={result.params}")

import asyncio
import io
import logging
from typing import Optional

from aiogram import Bot, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from app.agent.agent import ToolCallingAgent
from app.config import settings
from app.orchestrator.dialogue import DialogueOrchestrator
from app.speech.speechkit import YandexSpeechKitService

logger = logging.getLogger(__name__)

router = Router()
orchestrator = DialogueOrchestrator(agent=ToolCallingAgent())
stt = YandexSpeechKitService()


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 На сегодня", callback_data="nav:today"),
                InlineKeyboardButton(text="📋 Мои задачи", callback_data="nav:tasks"),
            ],
            [
                InlineKeyboardButton(text="📦 Архив", callback_data="nav:archive"),
                InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="nav:tz"),
            ],
            [
                InlineKeyboardButton(text="💡 Справка", callback_data="nav:help"),
            ]
        ]
    )


def get_timezone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Калининград (UTC+2)", callback_data="set_tz:Europe/Kaliningrad"),
                InlineKeyboardButton(text="Москва (UTC+3)", callback_data="set_tz:Europe/Moscow"),
            ],
            [
                InlineKeyboardButton(text="Самара (UTC+4)", callback_data="set_tz:Europe/Samara"),
                InlineKeyboardButton(text="Екатеринбург (UTC+5)", callback_data="set_tz:Asia/Yekaterinburg"),
            ],
            [
                InlineKeyboardButton(text="Омск (UTC+6)", callback_data="set_tz:Asia/Omsk"),
                InlineKeyboardButton(text="Новосибирск (UTC+7)", callback_data="set_tz:Asia/Novosibirsk"),
            ],
            [
                InlineKeyboardButton(text="Иркутск (UTC+8)", callback_data="set_tz:Asia/Irkutsk"),
                InlineKeyboardButton(text="Владивосток (UTC+10)", callback_data="set_tz:Asia/Vladivostok"),
            ]
        ]
    )


def get_schedule_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 На завтра", callback_data="nav:tomorrow"),
                InlineKeyboardButton(text="🔄 Обновить", callback_data="nav:today"),
            ],
            [
                InlineKeyboardButton(text="📋 Активные задачи", callback_data="nav:tasks"),
                InlineKeyboardButton(text="📦 Архив", callback_data="nav:archive"),
            ]
        ]
    )


def get_archive_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 На сегодня", callback_data="nav:today"),
                InlineKeyboardButton(text="📋 Мои задачи", callback_data="nav:tasks"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить архив", callback_data="nav:archive"),
            ]
        ]
    )


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить ввод", callback_data="dialogue:cancel")]
        ]
    )


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
    text = (
        "👋 Привет! Я голосовой ассистент для задач и встреч.\n\n"
        "Отправьте мне голосовое или текстовое сообщение:\n"
        "• «Поставь встречу с Михаилом завтра в 14:00»\n"
        "• «Напомни позвонить врачу сегодня в 18:30»\n"
        "• «Что у меня запланировано на сегодня?»\n"
        "• «Найди задачу про отчет»\n\n"
        "Или воспользуйтесь кнопками ниже 👇"
    )
    await message.answer(text, reply_markup=get_main_menu_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 *Как пользоваться ассистентом:*\n\n"
        "1️⃣ *Встречи:*\n"
        "• «Встреча с командой в пятницу в 15:00»\n"
        "• «Созвон с клиентом послезавтра в 11:00»\n"
        "_(Если не указать время или дату, я спрошу их дополнительно)_\n\n"
        "2️⃣ *Задачи и напоминания:*\n"
        "• «Напомни купить кофе завтра в 9 утра»\n"
        "• «Задача: подготовить презентацию до конца недели»\n\n"
        "3️⃣ *Расписание:*\n"
        "• «Что у меня сегодня?»\n"
        "• «Планы на завтра» или «Расписание на неделю»\n\n"
        "4️⃣ *Умный поиск:*\n"
        "• «Найди задачу про договор»\n"
        "• «Когда созвон с дизайнером?»\n\n"
        "⚙️ *Команды меню:*\n"
        "/today — расписание на сегодня\n"
        "/tasks — список задач\n"
        "/archive — архив прошедших событий\n"
        "/timezone — выбор часового пояса\n"
        "/cancel — отменить текущий ввод"
    )
    await message.answer(help_text, parse_mode="Markdown")


@router.message(Command("today", "schedule"))
async def cmd_today(message: Message, bot: Optional[Bot] = None):
    await _send_action_safe(bot, message.chat.id, "typing")
    reply = await orchestrator.handle_text(message.chat.id, "Что у меня запланировано на сегодня?")
    await message.answer(reply.text, reply_markup=get_schedule_keyboard())


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, bot: Optional[Bot] = None):
    await _send_action_safe(bot, message.chat.id, "typing")
    reply = await orchestrator.handle_text(message.chat.id, "Какие у меня активные задачи?")
    await message.answer(reply.text, reply_markup=get_schedule_keyboard())


@router.message(Command("archive"))
async def cmd_archive(message: Message, bot: Optional[Bot] = None):
    await _send_action_safe(bot, message.chat.id, "typing")
    text = await orchestrator.get_archive_view(message.chat.id)
    await message.answer(text, reply_markup=get_archive_keyboard())


@router.message(F.text.lower().in_(["/cancel", "отмена", "сброс"]))
async def cmd_cancel(message: Message):
    orchestrator.reset(message.chat.id)
    await message.answer("Контекст диалога сброшен. Чем могу помочь?")


@router.callback_query(F.data == "dialogue:cancel")
async def on_dialogue_cancel(callback: CallbackQuery):
    orchestrator.reset(callback.from_user.id)
    await callback.answer("Диалог отменен")
    if callback.message:
        await callback.message.edit_text("Действие отменено. Чем могу помочь?")


@router.callback_query(F.data.startswith("nav:"))
async def on_navigation(callback: CallbackQuery):
    action = callback.data.split(":")[1]
    chat_id = callback.from_user.id

    if action == "today":
        reply = await orchestrator.handle_text(chat_id, "Что у меня запланировано на сегодня?")
        await callback.answer()
        await callback.message.answer(reply.text, reply_markup=get_schedule_keyboard())
    elif action == "tomorrow":
        reply = await orchestrator.handle_text(chat_id, "Что у меня запланировано на завтра?")
        await callback.answer()
        await callback.message.answer(reply.text, reply_markup=get_schedule_keyboard())
    elif action == "tasks":
        reply = await orchestrator.handle_text(chat_id, "Какие у меня задачи?")
        await callback.answer()
        await callback.message.answer(reply.text, reply_markup=get_schedule_keyboard())
    elif action == "archive":
        text = await orchestrator.get_archive_view(chat_id)
        await callback.answer()
        await callback.message.answer(text, reply_markup=get_archive_keyboard())
    elif action == "help":
        await callback.answer()
        await cmd_help(callback.message)
    elif action == "tz":
        await callback.answer()
        await cmd_timezone(callback.message)


@router.message(Command("timezone", "tz"))
async def cmd_timezone(message: Message):
    current_tz = await orchestrator.db.get_user_timezone(message.chat.id)
    text = (
        f"🌍 *Настройка часового пояса*\n\n"
        f"Ваш текущий пояс: `{current_tz}`\n\n"
        f"Выберите регион из списка ниже:"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_timezone_keyboard())


@router.callback_query(F.data.startswith("set_tz:"))
async def on_set_timezone(callback: CallbackQuery):
    tz = callback.data.split(":", 1)[1]
    username = callback.from_user.username if callback.from_user else None
    try:
        await orchestrator.db.set_user_timezone(callback.from_user.id, tz, username)
    except ValueError:
        await callback.answer("Некорректный часовой пояс.", show_alert=True)
        return
    await callback.answer("Часовой пояс обновлен!")
    if callback.message:
        await callback.message.edit_text(f"✅ Часовой пояс успешно изменен на `{tz}`.", parse_mode="Markdown")


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
    duration = int(getattr(message.voice, "duration", 0) or 0)
    file_size = int(getattr(message.voice, "file_size", 0) or 0)
    if duration > settings.max_voice_duration_seconds or file_size > settings.max_voice_size_bytes:
        await message.answer(
            "Голосовое сообщение слишком длинное. "
            f"Поддерживается до {settings.max_voice_duration_seconds} секунд "
            f"и примерно {settings.max_voice_size_bytes / 1_000_000:.1f} МБ."
        )
        return

    await _send_action_safe(bot, message.chat.id, "record_voice")
    buf = io.BytesIO()
    if bot:
        try:
            await bot.download(message.voice, destination=buf)
        except Exception as e:
            logger.warning("Failed to download voice message: %s", e)
            await message.answer("Не удалось загрузить голосовое сообщение, попробуйте ещё раз.")
            return
    text = await stt.speech_to_text(buf.getvalue())
    if not text:
        await message.answer("Не удалось распознать голосовое сообщение, попробуйте ещё раз.")
        return

    await message.answer(f"Распознано: «{text}»")
    await _send_action_safe(bot, message.chat.id, "typing")
    try:
        reply = await orchestrator.handle_text(message.chat.id, text)

        is_pending = orchestrator.has_pending(message.chat.id) if hasattr(orchestrator, "has_pending") else False
        if is_pending is True:
            await message.answer(reply.text, reply_markup=get_cancel_keyboard())
        else:
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


@router.message(F.video_note)
async def on_video_note(message: Message):
    await message.answer("Я лучше всего воспринимаю обычные голосовые заметки (аудио) или текст. Пожалуйста, запишите голосовое сообщение!")


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Optional[Bot] = None):
    await _send_action_safe(bot, message.chat.id, "typing")
    try:
        reply = await orchestrator.handle_text(message.chat.id, message.text)

        is_pending = orchestrator.has_pending(message.chat.id) if hasattr(orchestrator, "has_pending") else False
        if is_pending is True:
            await message.answer(reply.text, reply_markup=get_cancel_keyboard())
        else:
            await message.answer(reply.text)
    except Exception as e:
        logger.exception("Error processing text message: %s", e)
        await message.answer("Произошла ошибка при обработке запроса. Попробуйте еще раз.")


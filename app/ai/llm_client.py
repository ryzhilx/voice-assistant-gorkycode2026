import re
import json
import logging
import datetime
import httpx
from typing import Dict, Any, Optional
from app.config import settings
from app.ai.schemas import AIResponse, AIAction
from app.ai.prompts import get_system_prompt

logger = logging.getLogger(__name__)

class LLMOrchestrator:
    def __init__(self):
        self.yandex_api_key = settings.yandex_api_key
        self.yandex_folder_id = settings.yandex_folder_id
        self.gigachat_credentials = settings.gigachat_credentials

    async def parse_intent(self, text: str, context: Optional[Dict[str, Any]] = None) -> AIResponse:
        text_clean = text.strip()
        logger.debug("Parsing intent: %s", text_clean)

        if context and context.get("awaiting_slot"):
            return self._resolve_clarification(text_clean, context)

        if self.yandex_api_key and self.yandex_folder_id:
            try:
                res = await self._call_yandex_gpt(text_clean)
                if res:
                    return res
            except Exception as e:
                logger.warning("YandexGPT request failed: %s", e)

        if self.gigachat_credentials:
            try:
                res = await self._call_gigachat(text_clean)
                if res:
                    return res
            except Exception as e:
                logger.warning("GigaChat request failed: %s", e)

        return self._heuristic_fallback(text_clean)

    def _resolve_clarification(self, answer_text: str, context: Dict[str, Any]) -> AIResponse:
        draft = context.get("draft_data", {})
        missing_slot = context.get("awaiting_slot")
        low = answer_text.lower().strip()

        if low in ["отмена", "не надо", "стоп", "забудь", "хватит", "нет", "отменить"]:
            return AIResponse(
                action=AIAction.CHAT,
                params={"reply": "Действие отменено."}
            )

        if missing_slot == "time":
            time_match = re.search(r"(\d{1,2})[:.-](\d{2})|в\s*(\d{1,2})", answer_text, re.IGNORECASE)
            extracted_time = None
            if time_match:
                if time_match.group(1) and time_match.group(2):
                    h = int(time_match.group(1))
                    m = int(time_match.group(2))
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        extracted_time = f"{h:02d}:{m:02d}"
                elif time_match.group(3):
                    h = int(time_match.group(3))
                    if 0 <= h <= 23:
                        extracted_time = f"{h:02d}:00"

            if extracted_time:
                draft["start_time"] = extracted_time
                if not draft.get("start_date"):
                    now = datetime.datetime.now()
                    draft["start_date"] = str(now.date() + datetime.timedelta(days=1))
                if not draft.get("title"):
                    draft["title"] = "Встреча"
                return AIResponse(
                    action=AIAction.CREATE_MEETING,
                    params=draft,
                    user_reply=f"Поставил встречу '{draft.get('title')}' на {draft.get('start_date')} в {extracted_time}."
                )

            if time_match and not extracted_time:
                return AIResponse(
                    action=AIAction.ASK_CLARIFICATION,
                    params={
                        "missing_slot": "time",
                        "question": "Кажется, время указано с ошибкой. Напишите время в формате ЧЧ:ММ (например, 15:00 или 18:30):",
                        "draft_data": draft
                    }
                )

        title = draft.get("title") or "Встреча"
        return AIResponse(
            action=AIAction.ASK_CLARIFICATION,
            params={
                "missing_slot": "time",
                "question": f"На какое время поставить встречу «{title}»?",
                "draft_data": draft
            }
        )

    async def _call_yandex_gpt(self, text: str) -> Optional[AIResponse]:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Authorization": f"Api-Key {self.yandex_api_key}",
            "x-folder-id": self.yandex_folder_id
        }
        payload = {
            "modelUri": f"gpt://{self.yandex_folder_id}/yandexgpt/latest",
            "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": 1000},
            "messages": [
                {"role": "system", "text": get_system_prompt()},
                {"role": "user", "text": text}
            ]
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["result"]["alternatives"][0]["message"]["text"]
                match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    action_val = parsed.get("action")
                    if action_val in [a.value for a in AIAction]:
                        return AIResponse(
                            action=AIAction(action_val),
                            params=parsed.get("params", {})
                        )
        return None

    async def _call_gigachat(self, text: str) -> Optional[AIResponse]:
        return None

    def _heuristic_fallback(self, text: str) -> AIResponse:
        now = datetime.datetime.now()
        low = text.lower().strip()

        # Chit-chat & Greetings
        if low in ["привет", "здравствуй", "добрый день", "добрый вечер", "доброе утро", "хай", "приветствую", "салют"]:
            return AIResponse(
                action=AIAction.CHAT,
                params={"reply": "Привет! Я голосовой ассистент. Могу записать задачу, назначить встречу или показать расписание."}
            )

        if any(w in low for w in ["что ты умеешь", "а чем можешь", "чем можешь", "помощь", "помоги", "что умеешь", "как пользоваться"]):
            return AIResponse(
                action=AIAction.CHAT,
                params={"reply": "Я помогаю с личными делами: создаю задачи и напоминания, планирую встречи, показываю расписание и ищу старые события по смыслу."}
            )

        if any(w in low for w in ["на какой нейросети", "какая нейросеть", "какая модель", "ты кто", "кто ты"]):
            return AIResponse(
                action=AIAction.CHAT,
                params={"reply": "Я работаю на базе YandexGPT для понимания речи и Yandex SpeechKit для синтеза и распознавания голоса."}
            )

        if low in ["спасибо", "благодарю", "отлично", "супер", "понял", "ясно"]:
            return AIResponse(
                action=AIAction.CHAT,
                params={"reply": "Всегда пожалуйста! Если понадобится что-то запланировать — обращайтесь."}
            )

        # Schedule
        if any(w in low for w in ["что у меня", "какие планы", "покажи встречи", "есть ли у меня", "какие задачи", "что запланировано"]):
            start_date = now.date()
            end_date = now.date()
            filter_type = "all"

            if "завтра" in low:
                start_date = now.date() + datetime.timedelta(days=1)
                end_date = start_date
            elif "неделю" in low:
                end_date = now.date() + datetime.timedelta(days=(6 - now.weekday() + 7) % 7)

            if "встреч" in low:
                filter_type = "meetings"
            elif "задач" in low:
                filter_type = "tasks"

            return AIResponse(
                action=AIAction.GET_SCHEDULE,
                params={
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "filter_type": filter_type
                }
            )

        # Search
        if any(w in low for w in ["найди", "поищи", "когда у меня была", "когда была", "я когда-то ставил"]):
            record_type = "all"
            if "встреч" in low:
                record_type = "meetings"
            elif "задач" in low:
                record_type = "tasks"

            clean = re.sub(r"\b(найди|поищи|задачу|задачи|встречу|встречи|встреча|про|по|с|когда-то|когда|у|меня|была|были|было|я|ставил|ставила|ее|его|их|мне|то)\b|[-?.,!]", " ", low)
            query = " ".join(clean.split()).strip()
            return AIResponse(
                action=AIAction.SEARCH_RECORDS,
                params={
                    "query": query if query else text,
                    "record_type": record_type
                }
            )

        target_date = now.date()
        if "завтра" in low:
            target_date = now.date() + datetime.timedelta(days=1)
        elif "послезавтра" in low:
            target_date = now.date() + datetime.timedelta(days=2)
        elif "в пятницу" in low:
            days_ahead = (4 - now.weekday() + 7) % 7
            target_date = now.date() + datetime.timedelta(days=days_ahead if days_ahead > 0 else 7)
        elif "до конца недели" in low:
            target_date = now.date() + datetime.timedelta(days=(6 - now.weekday()))

        target_time = None
        time_match = re.search(r"(\d{1,2})[:.-](\d{2})|в\s*(\d{1,2})\s*(утра|дня|вечера)?", low)
        if time_match:
            if time_match.group(1) and time_match.group(2):
                h = int(time_match.group(1))
                m = int(time_match.group(2))
                target_time = f"{h:02d}:{m:02d}"
            elif time_match.group(3):
                h = int(time_match.group(3))
                ampm = time_match.group(4)
                if ampm in ["дня", "вечера"] and h < 12:
                    h += 12
                target_time = f"{h:02d}:00"
        elif "через два часа" in low:
            new_dt = now + datetime.timedelta(hours=2)
            target_time = new_dt.strftime("%H:%M")

        # Meetings
        if "встреч" in low or "созвон" in low:
            title = text.strip()
            for prefix in ["добавь встречу с", "поставь встречу с", "добавь встречу", "поставь встречу", "у меня встреча с", "встреча с"]:
                if prefix in low:
                    idx = low.find(prefix) + len(prefix)
                    title = "Встреча с " + text[idx:].strip()
                    break

            title_clean = re.sub(r"завтра|сегодня|послезавтра|в \d{1,2}[:.]\d{2}|в \d{1,2}|в пятницу", "", title, flags=re.IGNORECASE).strip()
            title_clean = title_clean or "Встреча"

            if not target_time:
                return AIResponse(
                    action=AIAction.ASK_CLARIFICATION,
                    params={
                        "missing_slot": "time",
                        "question": f"На какое время поставить встречу '{title_clean}'?",
                        "draft_data": {
                            "title": title_clean,
                            "start_date": str(target_date),
                            "duration_minutes": 60
                        }
                    }
                )

            return AIResponse(
                action=AIAction.CREATE_MEETING,
                params={
                    "title": title_clean,
                    "start_date": str(target_date),
                    "start_time": target_time,
                    "duration_minutes": 60
                }
            )

        # Tasks
        is_reminder = "напомни" in low
        clean_title = re.sub(
            r"напомни мне|напомни|поставь задачу|нужно|надо|завтра|сегодня|послезавтра|до конца недели|в пятницу|в \d{1,2}(:\d{2})?(\s*утра|\s*вечера|\s*дня)?",
            "",
            text,
            flags=re.IGNORECASE
        ).strip()
        clean_title = clean_title.capitalize() if clean_title else "Задача"

        return AIResponse(
            action=AIAction.CREATE_TASK,
            params={
                "title": clean_title,
                "due_date": str(target_date),
                "due_time": target_time,
                "is_reminder": is_reminder
            }
        )

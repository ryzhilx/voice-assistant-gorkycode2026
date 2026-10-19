import re
import json
import logging
import datetime
import httpx
from typing import Dict, Any, Optional, List
from app.config import settings
from app.ai.schemas import AIResponse, AIAction
from app.ai.prompts import get_system_prompt

logger = logging.getLogger(__name__)

class LLMOrchestrator:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self.yandex_api_key = settings.yandex_api_key
        self.yandex_folder_id = settings.yandex_folder_id
        self._current_timezone: str = "Europe/Moscow"
        self._http_client = http_client
        self._owns_client = False

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=15.0)
            self._owns_client = True
        return self._http_client

    async def aclose(self) -> None:
        if self._owns_client and self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def set_current_timezone(self, tz: str) -> None:
        if tz:
            self._current_timezone = tz

    async def parse_intent(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> AIResponse:
        text_clean = text.strip()
        logger.debug("Parsing intent: %s", text_clean)

        if context and context.get("awaiting_slot"):
            return self._resolve_clarification(text_clean, context)

        if self.yandex_api_key and self.yandex_folder_id:
            try:
                res = await self._call_yandex_gpt(text_clean, history=history)
                if res:
                    return res
            except Exception as e:
                logger.warning("YandexGPT request failed: %s", e)

        return AIResponse(action=AIAction.UNKNOWN, params={})

    def _extract_date(self, text: str) -> Optional[datetime.date]:
        clean = re.sub(r"^(?:на|к|до)\s+", "", text.strip(), flags=re.IGNORECASE)
        clean_low = clean.strip().lower()

        if re.match(r"^(?:в\s*)?\d{1,2}(?:[:.-]\d{2})?(?:\s*(?:утра|дня|вечера))?$", clean_low):
            return None
        if re.match(r"^\d{1,2}\s*(?:утра|дня|вечера)$", clean_low):
            return None

        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo(self._current_timezone)).replace(tzinfo=None)
        except Exception:
            now = datetime.datetime.now()

        iso_m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if iso_m:
            try:
                return datetime.date.fromisoformat(iso_m.group(1))
            except Exception:
                pass

        try:
            import dateparser
            dt = dateparser.parse(
                clean,
                languages=["ru"],
                settings={
                    "PREFER_DATES_FROM": "future",
                    "RELATIVE_BASE": now,
                    "TIMEZONE": self._current_timezone,
                    "TO_TIMEZONE": self._current_timezone
                }
            )
            if dt:
                return dt.date()
        except Exception:
            pass

        low = text.lower()
        if "сегодня" in low:
            return now.date()
        if "послезавтра" in low:
            return now.date() + datetime.timedelta(days=2)
        if "завтра" in low:
            return now.date() + datetime.timedelta(days=1)
        return None

    @staticmethod
    def _parse_time(text: str) -> Optional[str]:
        low = text.lower().strip()
        clean = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", low)
        matches = re.finditer(
            r"(?:в\s*)?([01]?\d|2[0-3])[:.-]([0-5]\d)(?:\s*(утра|дня|вечера))?|в\s*(\d{1,2})(?:\s*(утра|дня|вечера))?|(\d{1,2})\s*(утра|дня|вечера)",
            clean
        )
        for time_match in matches:
            if time_match.group(1) and time_match.group(2):
                h = int(time_match.group(1))
                m = int(time_match.group(2))
                ampm = time_match.group(3)
                if ampm in ["дня", "вечера"] and h < 12:
                    h += 12
                if 0 <= h <= 23 and 0 <= m <= 59:
                    return f"{h:02d}:{m:02d}"
            elif time_match.group(4):
                h = int(time_match.group(4))
                ampm = time_match.group(5)
                if ampm in ["дня", "вечера"] and h < 12:
                    h += 12
                if 0 <= h <= 23:
                    return f"{h:02d}:00"
            elif time_match.group(6):
                h = int(time_match.group(6))
                ampm = time_match.group(7)
                if ampm in ["дня", "вечера"] and h < 12:
                    h += 12
                if 0 <= h <= 23:
                    return f"{h:02d}:00"
        if re.match(r"^\s*(\d{1,2})\s*$", clean):
            h = int(clean.strip())
            if 0 <= h <= 23:
                return f"{h:02d}:00"
        return None

    @staticmethod
    def _parse_relative_time(text: str, now: datetime.datetime) -> Optional[str]:
        low = text.lower()
        m_min = re.search(r"через\s+(\d+)\s*(?:минут|минуты|минуту|мин)\b", low)
        if m_min:
            new_dt = now + datetime.timedelta(minutes=int(m_min.group(1)))
            return new_dt.strftime("%H:%M")

        m_hr = re.search(r"через\s+(\d+)\s*(?:час|часа|часов)\b", low)
        if m_hr:
            new_dt = now + datetime.timedelta(hours=int(m_hr.group(1)))
            return new_dt.strftime("%H:%M")

        if "через полчаса" in low or "через пол-часа" in low:
            new_dt = now + datetime.timedelta(minutes=30)
            return new_dt.strftime("%H:%M")

        if "через час" in low:
            new_dt = now + datetime.timedelta(hours=1)
            return new_dt.strftime("%H:%M")

        if "через два часа" in low:
            new_dt = now + datetime.timedelta(hours=2)
            return new_dt.strftime("%H:%M")

        if "через три часа" in low:
            new_dt = now + datetime.timedelta(hours=3)
            return new_dt.strftime("%H:%M")

        return None



    def _resolve_clarification(self, answer_text: str, context: Dict[str, Any]) -> AIResponse:
        draft = dict(context.get("draft_data", {}))
        missing_slot = context.get("awaiting_slot")
        low = answer_text.lower().strip()

        if low in ["отмена", "не надо", "стоп", "забудь", "хватит", "нет", "отменить"]:
            return AIResponse(
                action=AIAction.CHAT,
                params={"reply": "Действие отменено."}
            )

        date_found = self._extract_date(answer_text)
        if date_found:
            draft["start_date"] = str(date_found)
            draft["new_date"] = str(date_found)

        time_found = self._parse_time(answer_text)
        if time_found:
            draft["start_time"] = time_found
            draft["new_time"] = time_found

        if draft.get("action") == "reschedule_record":
            if draft.get("new_date") or draft.get("new_time"):
                return AIResponse(
                    action=AIAction.RESCHEDULE_RECORD,
                    params=draft
                )

        if missing_slot == "title" and not draft.get("title"):
            draft["title"] = answer_text.strip().capitalize()

        if draft.get("start_date") and draft.get("start_time"):
            if not draft.get("title"):
                draft["title"] = "Встреча"
            return AIResponse(
                action=AIAction.CREATE_MEETING,
                params=draft,
                user_reply=f"Поставил встречу '{draft.get('title')}' на {draft.get('start_date')} в {draft.get('start_time')}."
            )

        if draft.get("start_time") and not draft.get("start_date"):
            if missing_slot == "time":
                try:
                    from zoneinfo import ZoneInfo
                    today_date = datetime.datetime.now(ZoneInfo(self._current_timezone)).date()
                except Exception:
                    today_date = datetime.datetime.now().date()
                draft["start_date"] = str(today_date)
                if not draft.get("title"):
                    draft["title"] = "Встреча"
                return AIResponse(
                    action=AIAction.CREATE_MEETING,
                    params=draft,
                    user_reply=f"Поставил встречу '{draft.get('title')}' на {draft.get('start_date')} в {draft.get('start_time')}."
                )
            else:
                title = draft.get("title") or "Встреча"
                return AIResponse(
                    action=AIAction.ASK_CLARIFICATION,
                    params={
                        "missing_slot": "date",
                        "question": f"На какую дату планируете встречу «{title}»?",
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

    async def _call_yandex_gpt(self, text: str, history: Optional[List[Dict[str, str]]] = None) -> Optional[AIResponse]:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Authorization": f"Api-Key {self.yandex_api_key}",
            "x-folder-id": self.yandex_folder_id
        }
        system_text = get_system_prompt(timezone_str=self._current_timezone)
        messages = [{"role": "system", "text": system_text}]
        if history:
            messages.extend(history[-4:])
        messages.append({"role": "user", "text": text})

        payload = {
            "modelUri": f"gpt://{self.yandex_folder_id}/yandexgpt/latest",
            "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": 1000},
            "messages": messages
        }
        client = self._get_client()
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            raw_text = data["result"]["alternatives"][0]["message"]["text"]
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                action_val = parsed.get("action")
                if action_val == AIAction.MULTI_ACTION.value or "sub_actions" in parsed or "actions" in parsed:
                    raw_subs = parsed.get("sub_actions") or parsed.get("actions", [])
                    parsed_subs = []
                    for sub_item in raw_subs:
                        sub_act = sub_item.get("action")
                        sub_p = sub_item.get("params", {})
                        if sub_act in [a.value for a in AIAction]:
                            parsed_subs.append(AIResponse(action=AIAction(sub_act), params=sub_p))
                    if parsed_subs:
                        return AIResponse(
                            action=AIAction.MULTI_ACTION,
                            params={},
                            sub_actions=parsed_subs
                        )

                if action_val in [a.value for a in AIAction]:
                    params = parsed.get("params", {})
                    if action_val == AIAction.GET_SCHEDULE.value:
                        now_date_str = str(datetime.datetime.now().date())
                        if not params.get("start_date"):
                            params["start_date"] = now_date_str
                        if not params.get("end_date"):
                            params["end_date"] = params["start_date"]

                    if action_val in [AIAction.CREATE_MEETING.value, AIAction.CREATE_TASK.value]:
                        time_key = "start_time" if action_val == AIAction.CREATE_MEETING.value else "due_time"
                        val_time = params.get(time_key)
                        if val_time and isinstance(val_time, str):
                            low_text = text.lower()
                            time_match = re.search(r"\b([01]?\d|2[0-3])[:.-](\d{2})\b", low_text)
                            if time_match:
                                explicit_h = int(time_match.group(1))
                                explicit_m = int(time_match.group(2))
                                has_pm_word = any(w in low_text for w in ["дня", "вечера", "pm"])
                                if not has_pm_word:
                                    params[time_key] = f"{explicit_h:02d}:{explicit_m:02d}"

                    return AIResponse(
                        action=AIAction(action_val),
                        params=params
                    )
        return None

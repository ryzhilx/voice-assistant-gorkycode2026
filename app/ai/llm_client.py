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
        self.gigachat_credentials = settings.gigachat_credentials
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

        if self.gigachat_credentials:
            try:
                res = await self._call_gigachat(text_clean)
                if res:
                    return res
            except Exception as e:
                logger.warning("GigaChat request failed: %s", e)

        return self._heuristic_fallback(text_clean)

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
    def _extract_recurrence(text: str) -> Optional[str]:
        low = text.lower()
        if re.search(r"\bпо\s+понедельникам\b|\bкаждый\s+понедельник\b", low):
            return "weekly:mon"
        if re.search(r"\bпо\s+вторникам\b|\bкаждый\s+вторник\b", low):
            return "weekly:tue"
        if re.search(r"\bпо\s+средам\b|\bкаждую\s+среду\b", low):
            return "weekly:wed"
        if re.search(r"\bпо\s+четвергам\b|\bкаждый\s+четверг\b", low):
            return "weekly:thu"
        if re.search(r"\bпо\s+пятницам\b|\bкаждую\s+пятницу\b", low):
            return "weekly:fri"
        if re.search(r"\bпо\s+субботам\b|\bкаждую\s+субботу\b", low):
            return "weekly:sat"
        if re.search(r"\bпо\s+воскресеньям\b|\bкаждое\s+воскресенье\b", low):
            return "weekly:sun"
        if re.search(r"\b(по\s+будням|в\s+будни|в\s+будние\s+дни|каждый\s+будний\s+день|по\s+будним\s+дням|с\s+понедельника\s+по\s+пятницу)\b", low):
            return "weekdays"
        if re.search(r"\b(каждый\s+день|ежедневно|каждое\s+утро|каждый\s+вечер|по\s+дням)\b", low):
            return "daily"
        if re.search(r"\b(каждую\s+неделю|еженедельно|раз\s+в\s+неделю)\b", low):
            return "weekly"
        if re.search(r"\b(каждый\s+месяц|ежемесячно|раз\s+в\s+месяц)\b", low):
            return "monthly"
        return None

    def _initial_recurring_date(self, recurrence: str, target_time: Optional[str] = None) -> datetime.date:
        try:
            from zoneinfo import ZoneInfo
            now_dt = datetime.datetime.now(ZoneInfo(self._current_timezone)).replace(tzinfo=None)
        except Exception:
            now_dt = datetime.datetime.now()
        today = now_dt.date()

        time_passed = False
        if target_time:
            try:
                th, tm = map(int, target_time.split(":"))
                now_min = now_dt.hour * 60 + now_dt.minute
                target_min = th * 60 + tm
                if target_min <= now_min:
                    time_passed = True
            except Exception:
                pass

        if recurrence == "daily":
            return today

        if recurrence == "weekdays":
            cand = today
            while cand.weekday() >= 5:
                cand = cand + datetime.timedelta(days=1)
            return cand

        if recurrence.startswith("weekly:"):
            day_code = recurrence.split(":", 1)[1]
            day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            target_wd = day_map.get(day_code, 0)
            days_ahead = (target_wd - today.weekday()) % 7
            return today + datetime.timedelta(days=days_ahead)

        if recurrence == "weekly":
            return today

        if recurrence == "monthly":
            return today

        return today

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

                        if not params.get("recurrence"):
                            rec = self._extract_recurrence(text)
                            if rec:
                                params["recurrence"] = rec

                    return AIResponse(
                        action=AIAction(action_val),
                        params=params
                    )
        return None

    async def _call_gigachat(self, text: str) -> Optional[AIResponse]:
        return None

    def _split_multi_query(self, text: str) -> List[str]:
        raw = text.strip()
        if "\n" in raw:
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            if len(lines) > 1:
                return lines

        if ";" in raw:
            parts = [p.strip() for p in raw.split(";") if p.strip()]
            if len(parts) > 1:
                return parts

        command_verbs = (
            r"(?:напоминай|напомни|поставь|добавь|назначь|запиши|создай|созвон|встреча|встречу|задачу|задача|планерка|планерку|стендап|"
            r"покажи|что у меня|какие планы|какие встречи|какие задачи|найди|поищи|перенеси|перенести|перенесем|сдвинь|отложи|"
            r"удали|удалить|убери|отмени|отменить|стереть|сотри|переименуй|отметь|выполни|выполнил|сделал|закрой|заверши|купи|купить|сделай|сделать)"
        )
        pattern = rf"(?:,\s*(?:а\s+также|а\s+еще|также|потом|затем|плюс|и)\s+|,\s*(?={command_verbs}\b)|\s+и\s+(?={command_verbs}\b))"
        parts = re.split(pattern, raw, flags=re.IGNORECASE)
        clean_parts = [p.strip() for p in parts if p.strip()]
        if len(clean_parts) > 1:
            merged = []
            tail_re = re.compile(r"^(?:найди|поищи|удали|удалить|отмени|отметь)(?:\s+(?:ее|его|их|это|мне|пожалуйста|плиз|выполненной|выполненным))*\s*[.?!]*$", re.IGNORECASE)
            for p in clean_parts:
                if merged and tail_re.match(p):
                    merged[-1] = f"{merged[-1]}, {p}"
                else:
                    merged.append(p)
            if len(merged) > 1:
                return merged

        return [raw]

    def _heuristic_fallback(self, text: str) -> AIResponse:
        parts = self._split_multi_query(text)
        if len(parts) > 1:
            sub_res = []
            for p in parts:
                r = self._single_heuristic(p)
                if r.action != AIAction.UNKNOWN:
                    sub_res.append(r)
            if len(sub_res) > 1:
                return AIResponse(
                    action=AIAction.MULTI_ACTION,
                    params={},
                    sub_actions=sub_res
                )
        return self._single_heuristic(text)

    def _single_heuristic(self, text: str) -> AIResponse:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo(self._current_timezone)).replace(tzinfo=None)
        except Exception:
            now = datetime.datetime.now()
        low = text.lower().strip()

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

        archive_triggers = [
            "архив", "прошедшие", "что прошло", "старые встречи", "завершенные задачи",
            "прошедшие события", "история встреч", "история задач"
        ]
        if any(w in low for w in archive_triggers) or low in ["архив", "прошедшее", "история"]:
            filter_type = "all"
            if "встреч" in low:
                filter_type = "meetings"
            elif "задач" in low:
                filter_type = "tasks"
            return AIResponse(
                action=AIAction.GET_ARCHIVE,
                params={"filter_type": filter_type}
            )

        schedule_triggers = [
            "что у меня", "какие планы", "покажи встречи", "есть ли у меня",
            "какие задачи", "что запланировано", "мои встречи", "мои задачи",
            "расписание", "список встреч", "список задач", "планы на", "покажи расписание"
        ]
        if any(w in low for w in schedule_triggers) or low in ["встречи", "задачи", "расписание", "планы"]:
            start_date = now.date()
            end_date = now.date()
            filter_type = "all"

            if "завтра" in low:
                start_date = now.date() + datetime.timedelta(days=1)
                end_date = start_date
            elif "послезавтра" in low:
                start_date = now.date() + datetime.timedelta(days=2)
                end_date = start_date
            elif "неделю" in low or "неделе" in low:
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

        if any(w in low for w in ["найди", "поищи", "когда у меня была", "когда была", "я когда-то", "была ли у меня", "поиск"]):
            record_type = "all"
            if "встреч" in low:
                record_type = "meetings"
            elif "задач" in low:
                record_type = "tasks"

            clean = re.sub(r"\b(найди|поищи|поиск|задачу|задачи|задача|встречу|встречи|встреча|про|по|с|со|о|об|обо|для|на|к|ко|когда-то|когда|у|меня|была|были|было|ли|я|ставил|ставила|создавал|создавала|делал|делала|ее|его|их|мне|то)\b|[-?.,!]", " ", low)
            query = " ".join(clean.split()).strip()
            return AIResponse(
                action=AIAction.SEARCH_RECORDS,
                params={
                    "query": query if query else text,
                    "record_type": record_type
                }
            )

        if any(w in low for w in ["перенеси", "перенесем", "перенести", "сдвинь", "отложи"]):
            target = "last"
            if "встреч" in low:
                target = "meeting"
            elif "задач" in low:
                target = "task"

            parsed_date = self._extract_date(low)
            parsed_time = self._parse_time(low)
            if not parsed_time and "через два часа" in low:
                new_dt = now + datetime.timedelta(hours=2)
                parsed_time = new_dt.strftime("%H:%M")

            if not parsed_date and not parsed_time:
                return AIResponse(
                    action=AIAction.ASK_CLARIFICATION,
                    params={
                        "missing_slot": "time",
                        "question": "На какую дату или время перенести?",
                        "draft_data": {"action": "reschedule_record", "target": target}
                    }
                )

            return AIResponse(
                action=AIAction.RESCHEDULE_RECORD,
                params={
                    "target": target,
                    "new_date": str(parsed_date) if parsed_date else None,
                    "new_time": parsed_time
                }
            )

        if any(w in low for w in ["отметь выполненной", "отметить выполненной", "задача выполнена", "выполнил задачу", "сделал задачу", "заверши задачу", "закрой задачу", "выполнена", "выполнено"]) or ("отметь" in low and "выполнен" in low):
            target = "task"
            clean = re.sub(r"\b(отметь|отметить|задачу|задачи|задача|как|выполненной|выполненным|выполнена|выполнено|выполнил|сделал|заверши|закрой|ее|его|их|мне|пожалуйста)\b|[-?.,!]", " ", low)
            q = " ".join(clean.split()).strip()
            return AIResponse(
                action=AIAction.COMPLETE_RECORD,
                params={"target": target, "query": q if q else None}
            )

        if any(w in low for w in ["удали", "удалить", "убери", "отмени", "отменить", "стереть", "сотри", "сними"]) and not any(w in low for w in ["ввод", "диалог"]):
            target = "last"
            if "встреч" in low or "созвон" in low:
                target = "meeting"
            elif "задач" in low or "напоминан" in low:
                target = "task"
            clean = re.sub(r"\b(удали|удалить|убери|отмени|отменить|стереть|сотри|сними|задачу|задачи|задача|встречу|встречи|встреча|созвон|напоминание|напоминания|ее|его|их|это|последнее|последнюю|мне|пожалуйста)\b|[-?.,!]", " ", low)
            q = " ".join(clean.split()).strip()
            return AIResponse(
                action=AIAction.DELETE_RECORD,
                params={"target": target, "query": q if q else None}
            )

        if any(w in low for w in ["переименуй", "измени название", "поменяй название", "измени текст", "измени задачу на", "поменяй задачу на", "измени встречу на"]):
            target = "last"
            if "встреч" in low or "созвон" in low:
                target = "meeting"
            elif "задач" in low:
                target = "task"
            match = re.search(r"(?:в|на|текст на|название на)\s+[\"«']?([^\"»']+)[\"»']?$", text, re.IGNORECASE)
            new_title = match.group(1).strip() if match else text.strip()
            return AIResponse(
                action=AIAction.UPDATE_RECORD,
                params={"target": target, "new_title": new_title}
            )

        recurrence = self._extract_recurrence(low)
        parsed_date = self._extract_date(low)
        target_time = self._parse_time(low)
        if not target_time and "через два часа" in low:
            new_dt = now + datetime.timedelta(hours=2)
            target_time = new_dt.strftime("%H:%M")

        if recurrence and not parsed_date:
            target_date = self._initial_recurring_date(recurrence, target_time)
        else:
            target_date = parsed_date if parsed_date else now.date()

        rec_strip = (
            r"\b(по\s+понедельникам|каждый\s+понедельник|по\s+вторникам|каждый\s+вторник|"
            r"по\s+средам|каждую\s+среду|по\s+четвергам|каждый\s+четверг|"
            r"по\s+пятницам|каждую\s+пятницу|по\s+субботам|каждую\s+субботу|"
            r"по\s+воскресеньям|каждое\s+воскресенье|по\s+будням|в\s+будни|в\s+будние\s+дни|"
            r"каждый\s+будний\s+день|по\s+будним\s+дням|с\s+понедельника\s+по\s+пятницу|"
            r"каждый\s+день|ежедневно|каждое\s+утро|каждый\s+вечер|каждую\s+неделю|еженедельно|каждый\s+месяц|ежемесячно)\b"
        )

        is_meeting_intent = (
            "встреч" in low
            or "созвон" in low
            or any(w in low for w in ["планерк", "стендап", "синк", "митинг"])
        )

        if is_meeting_intent:
            title = text.strip()
            for prefix in ["добавь встречу с", "поставь встречу с", "добавь встречу", "поставь встречу", "у меня встреча с", "встреча с"]:
                if prefix in low:
                    idx = low.find(prefix) + len(prefix)
                    title = "Встреча с " + text[idx:].strip()
                    break

            title_clean = re.sub(r"завтра|сегодня|послезавтра|в \d{1,2}[:.]\d{2}|в \d{1,2}|в пятницу", "", title, flags=re.IGNORECASE)
            title_clean = re.sub(rec_strip, "", title_clean, flags=re.IGNORECASE).strip()
            title_clean = re.sub(r"^[\s,.-]+|[\s,.-]+$", "", title_clean)
            title_clean = title_clean.capitalize() if title_clean else "Встреча"

            if not target_time:
                return AIResponse(
                    action=AIAction.ASK_CLARIFICATION,
                    params={
                        "missing_slot": "time",
                        "question": f"На какое время поставить встречу '{title_clean}'?",
                        "draft_data": {
                            "title": title_clean,
                            "start_date": str(target_date),
                            "duration_minutes": 60,
                            "recurrence": recurrence
                        }
                    }
                )

            return AIResponse(
                action=AIAction.CREATE_MEETING,
                params={
                    "title": title_clean,
                    "start_date": str(target_date),
                    "start_time": target_time,
                    "duration_minutes": 60,
                    "recurrence": recurrence
                }
            )

        is_reminder = any(w in low for w in ["напомни", "напоминай"])
        clean_title = re.sub(
            r"напоминай мне|напоминай|напомни мне|напомни|поставь задачу|нужно|надо|завтра|сегодня|послезавтра|до конца недели|в пятницу|в \d{1,2}(:\d{2})?(\s*утра|\s*вечера|\s*дня)?",
            "",
            text,
            flags=re.IGNORECASE
        )
        clean_title = re.sub(rec_strip, "", clean_title, flags=re.IGNORECASE).strip()
        clean_title = clean_title.capitalize() if clean_title else "Задача"

        return AIResponse(
            action=AIAction.CREATE_TASK,
            params={
                "title": clean_title,
                "due_date": str(target_date),
                "due_time": target_time,
                "is_reminder": is_reminder,
                "recurrence": recurrence
            }
        )

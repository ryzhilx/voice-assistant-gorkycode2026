import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.agent.schemas import ToolCall, ToolExecutionResult
from app.agent.tools import build_default_tools, get_tools_json_schema
from app.agent.tools.base import BaseTool
from app.ai.embeddings import SemanticSearchEngine
from app.ai.llm_client import LLMOrchestrator
from app.ai.schemas import AIAction
from app.config import settings
from app.storage.db import Database

logger = logging.getLogger(__name__)

class ToolCallingAgent:
    def __init__(
        self,
        db: Optional[Database] = None,
        search_engine: Optional[SemanticSearchEngine] = None,
        llm: Optional[LLMOrchestrator] = None,
        yandex_api_key: Optional[str] = None,
        yandex_folder_id: Optional[str] = None
    ):
        self.db = db or Database(settings.database_path)
        self.search_engine = search_engine or SemanticSearchEngine()
        self.llm = llm or LLMOrchestrator()
        self.yandex_api_key = yandex_api_key or settings.yandex_api_key
        self.yandex_folder_id = yandex_folder_id or settings.yandex_folder_id

        self._last_event: Dict[int, Dict[str, Any]] = {}
        self._history: Dict[int, List[Dict[str, str]]] = {}
        self.tools: Dict[str, BaseTool] = build_default_tools(
            self.db,
            self.search_engine,
            self._last_event
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=15.0)
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        if hasattr(self.search_engine, "aclose") and callable(getattr(self.search_engine, "aclose")):
            await self.search_engine.aclose()
        if hasattr(self.llm, "aclose") and callable(getattr(self.llm, "aclose")):
            await self.llm.aclose()

    def reset(self, chat_id: int) -> None:
        self._history.pop(chat_id, None)
        self._last_event.pop(chat_id, None)

    def _build_system_prompt(self, timezone_str: str) -> str:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo(timezone_str))
        except Exception:
            now = datetime.datetime.now()

        days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        current_dt_str = f"{now.strftime('%Y-%m-%d %H:%M')} ({days_ru[now.weekday()]})"

        tools_desc = []
        for tool in self.tools.values():
            d = tool.definition
            params_str = ", ".join([f"{k}: {v.type}" for k, v in d.parameters.items()])
            tools_desc.append(f"- {d.name}({params_str}): {d.description}")

        return (
            f"Ты — интеллектуальный персональный голосовой ассистент.\n"
            f"Текущее точное время и дата пользователя: {current_dt_str}.\n"
            f"Часовой пояс пользователя: {timezone_str}.\n\n"
            f"ТЕБЕ ДОСТУПНЫ СЛЕДУЮЩИЕ ИНСТРУМЕНТЫ (TOOLS):\n"
            f"{chr(10).join(tools_desc)}\n\n"
            f"ПРАВИЛА:\n"
            f"1. Если для выполнения запроса требуется вызвать инструмент, вызови его с точными аргументами.\n"
            f"2. Если пользователь хочет создать встречу или задачу, но не указал обязательное время или дату — НЕ вызывай инструмент, а вежливо и кратко спроси пользователя на русском языке.\n"
            f"3. Если пользователь оперативно корректирует предыдущее действие (например: «а нет, давай через 10 минут лучше», «нет, давай в 19:00», «перенеси на завтра») — используй инструмент reschedule_record с target='last'.\n"
            f"4. Если пользователь сообщает о выполнении задачи в прошедшем времени (например: «я выпил воды», «купил молоко», «сделал отчет») — используй complete_task.\n"
            f"5. Если запрос — приветствие или общий разговор, ответь лаконично и естественно без вызова инструментов.\n"
            f"6. При вызове инструментов в текстовом формате используй JSON вида: {{\"tool\": \"tool_name\", \"arguments\": {{...}}}}."
        )

    async def _call_llm(self, chat_id: int, text: str, tz_str: str) -> Optional[List[ToolCall]]:
        if not (self.yandex_api_key and self.yandex_folder_id):
            return None

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Authorization": f"Api-Key {self.yandex_api_key}",
            "x-folder-id": self.yandex_folder_id
        }

        system_text = self._build_system_prompt(tz_str)
        messages = [{"role": "system", "text": system_text}]
        chat_hist = self._history.get(chat_id, [])
        if chat_hist:
            messages.extend(chat_hist[-6:])
        messages.append({"role": "user", "text": text})

        payload: Dict[str, Any] = {
            "modelUri": f"gpt://{self.yandex_folder_id}/yandexgpt/latest",
            "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": 1000},
            "messages": messages,
            "tools": get_tools_json_schema(self.tools)
        }

        client = self._get_http_client()
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("result", {}).get("alternatives", [{}])[0].get("message", {})

                function_call = msg.get("call", {}).get("functionCall")
                if function_call:
                    name = function_call.get("name")
                    args = function_call.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    return [ToolCall(name=name, arguments=args)]

                raw_text = msg.get("text", "").strip()
                json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(0))
                        t_name = parsed.get("tool") or parsed.get("name") or parsed.get("action")
                        t_args = parsed.get("arguments") or parsed.get("params", {})
                        if t_name in self.tools:
                            return [ToolCall(name=t_name, arguments=t_args)]
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Agent LLM call error: %s", e)

        return None

    def _fallback_to_tool_call(self, text: str, context: Optional[Dict[str, Any]] = None) -> Optional[List[ToolCall]]:
        intent_res = self.llm._heuristic_fallback(text)
        action = intent_res.action
        params = intent_res.params

        mapping = {
            AIAction.CREATE_TASK: "create_task",
            AIAction.CREATE_MEETING: "create_meeting",
            AIAction.GET_SCHEDULE: "get_schedule",
            AIAction.GET_ARCHIVE: "get_archive",
            AIAction.SEARCH_RECORDS: "search_records",
            AIAction.RESCHEDULE_RECORD: "reschedule_record",
            AIAction.COMPLETE_RECORD: "complete_task",
            AIAction.DELETE_RECORD: "delete_record",
            AIAction.UPDATE_RECORD: "update_record_title",
        }

        tool_name = mapping.get(action)
        if tool_name and tool_name in self.tools:
            return [ToolCall(name=tool_name, arguments=params)]

        return None

    async def run(self, chat_id: int, message: str) -> str:
        tz_str = await self.db.get_user_timezone(chat_id)
        if hasattr(self.llm, "set_current_timezone") and callable(getattr(self.llm, "set_current_timezone")):
            self.llm.set_current_timezone(tz_str)

        tool_calls = await self._call_llm(chat_id, message, tz_str)

        if tool_calls is None:
            tool_calls = self._fallback_to_tool_call(message)

        if not tool_calls:
            low = message.lower().strip()
            if any(w in low for w in ["привет", "здравствуй", "добрый день", "хай"]):
                reply = "Привет! Я персональный голосовой ассистент. Могу записать задачу, назначить встречу или показать расписание."
            elif any(w in low for w in ["что ты умеешь", "какие возможности", "помощь"]):
                reply = "Я умею ставить задачи и напоминания, бронировать встречи в календаре, показывать расписание на день/неделю и находить старые записи."
            elif any(w in low for w in ["встреч", "поставь встречу", "добавь встречу"]) and not re.search(r"\d{1,2}[:.]\d{2}", low):
                reply = "На какую дату и время вы хотите запланировать встречу?"
            else:
                reply = "Чем я могу вам помочь?"

            self._record_turn(chat_id, message, reply)
            return reply

        results: List[ToolExecutionResult] = []
        for call in tool_calls:
            tool = self.tools.get(call.name)
            if tool:
                res = await tool.execute(chat_id, **call.arguments)
                results.append(res)
            else:
                results.append(ToolExecutionResult(tool_name=call.name, success=False, output=f"Инструмент «{call.name}» не найден."))

        if len(results) == 1:
            final_reply = results[0].output
        else:
            final_reply = "\n\n".join([f"{idx}️⃣ {r.output}" for idx, r in enumerate(results, 1)])

        self._record_turn(chat_id, message, final_reply)
        return final_reply

    def _record_turn(self, chat_id: int, user_msg: str, assistant_msg: str) -> None:
        if chat_id not in self._history:
            self._history[chat_id] = []
        self._history[chat_id].append({"role": "user", "text": user_msg})
        self._history[chat_id].append({"role": "assistant", "text": assistant_msg})
        if len(self._history[chat_id]) > 6:
            self._history[chat_id] = self._history[chat_id][-6:]

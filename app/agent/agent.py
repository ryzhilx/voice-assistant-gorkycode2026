import datetime
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.agent.schemas import ToolCall, ToolExecutionResult
from app.agent.tools import build_default_tools, get_tools_json_schema
from app.agent.tools.base import BaseTool
from app.ai.embeddings import SemanticSearchEngine
from app.config import settings
from app.storage.db import Database

logger = logging.getLogger(__name__)

class ToolCallingAgent:
    def __init__(
        self,
        db: Optional[Database] = None,
        search_engine: Optional[SemanticSearchEngine] = None,
        llm: Optional[Any] = None,
        yandex_api_key: Optional[str] = None,
        yandex_folder_id: Optional[str] = None
    ):
        self.db = db or Database(settings.database_path)
        self.search_engine = search_engine or SemanticSearchEngine()
        self.llm = llm
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
            res = self.search_engine.aclose()
            if inspect.isawaitable(res):
                await res
        if self.llm and hasattr(self.llm, "aclose") and callable(getattr(self.llm, "aclose")):
            res = self.llm.aclose()
            if inspect.isawaitable(res):
                await res

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
            f"2. Если запрос содержит несколько действий (например: напомнить про кофе через 8 минут и про чай через 3 минуты) — вызови инструмент для каждого действия.\n"
            f"3. Если пользователь хочет создать встречу или задачу, но не указал обязательное время или дату — НЕ вызывай инструмент, а вежливо и кратко спроси пользователя на русском языке.\n"
            f"4. Если пользователь оперативно корректирует предыдущее действие (например: «а нет, давай через 10 минут лучше», «нет, давай в 19:00», «перенеси на завтра») — используй инструмент reschedule_record с target='last'.\n"
            f"5. Если пользователь сообщает о выполнении задачи в прошедшем времени (например: «я выпил воды», «купил молоко», «сделал отчет») — используй complete_task.\n"
            f"6. Если запрос — приветствие, вопрос или общий разговор, ответь лаконично, вежливо и естественно на русском языке без вызова инструментов.\n"
            f"7. При вызове инструментов в текстовом формате используй JSON вида: {{\"tool\": \"tool_name\", \"arguments\": {{...}}}} или список инструментов [{{...}}, {{...}}]."
        )

    def _normalize_tool_name(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        norm = name.strip().lower()
        alias_map = {
            "archive": "get_archive",
            "get_archive": "get_archive",
            "show_archive": "get_archive",
            "schedule": "get_schedule",
            "get_schedule": "get_schedule",
            "show_schedule": "get_schedule",
            "search": "search_records",
            "search_records": "search_records",
            "reschedule": "reschedule_record",
            "reschedule_record": "reschedule_record",
            "create_task": "create_task",
            "complete_task": "complete_task",
            "create_meeting": "create_meeting",
            "delete_record": "delete_record",
            "update_record_title": "update_record_title",
        }
        mapped = alias_map.get(norm, norm)
        return mapped if mapped in self.tools else None

    async def _call_llm(self, chat_id: int, text: str, tz_str: str) -> Tuple[Optional[List[ToolCall]], Optional[str]]:
        if not (self.yandex_api_key and self.yandex_folder_id):
            return None, None

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

                raw_calls = []
                if "toolCallList" in msg and isinstance(msg["toolCallList"], dict):
                    raw_calls.extend(msg["toolCallList"].get("toolCalls", []))
                elif "tool_calls" in msg and isinstance(msg["tool_calls"], list):
                    raw_calls.extend(msg["tool_calls"])
                elif "toolCalls" in msg and isinstance(msg["toolCalls"], list):
                    raw_calls.extend(msg["toolCalls"])
                elif "calls" in msg and isinstance(msg["calls"], list):
                    raw_calls.extend(msg["calls"])
                elif "call" in msg and isinstance(msg["call"], dict):
                    raw_calls.append(msg["call"])

                tool_calls: List[ToolCall] = []
                for c in raw_calls:
                    fn = None
                    if isinstance(c, dict):
                        fn = c.get("functionCall") or c.get("function")
                    if fn and isinstance(fn, dict):
                        name = self._normalize_tool_name(fn.get("name"))
                        if name:
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {}
                            tool_calls.append(ToolCall(name=name, arguments=args))

                if tool_calls:
                    return tool_calls, None

                raw_text = msg.get("text", "").strip()
                if raw_text:
                    json_match = re.search(r"(\[.*\]|\{.*\})", raw_text, re.DOTALL)
                    if json_match:
                        try:
                            parsed = json.loads(json_match.group(0))
                            if isinstance(parsed, list):
                                for item in parsed:
                                    t_name = self._normalize_tool_name(item.get("tool") or item.get("name") or item.get("action"))
                                    t_args = item.get("arguments") or item.get("params", {})
                                    if t_name:
                                        tool_calls.append(ToolCall(name=t_name, arguments=t_args))
                            elif isinstance(parsed, dict):
                                t_name = self._normalize_tool_name(parsed.get("tool") or parsed.get("name") or parsed.get("action"))
                                t_args = parsed.get("arguments") or parsed.get("params", {})
                                if t_name:
                                    tool_calls.append(ToolCall(name=t_name, arguments=t_args))
                            if tool_calls:
                                return tool_calls, None
                        except Exception:
                            pass

                    return None, raw_text
        except Exception as e:
            logger.warning("Agent LLM call error: %s", e)

        return None, None

    async def run(self, chat_id: int, message: str) -> str:
        tz_str = await self.db.get_user_timezone(chat_id)
        if self.llm and hasattr(self.llm, "set_current_timezone") and callable(getattr(self.llm, "set_current_timezone")):
            self.llm.set_current_timezone(tz_str)

        tool_calls, direct_reply = await self._call_llm(chat_id, message, tz_str)

        if tool_calls:
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

        if direct_reply:
            self._record_turn(chat_id, message, direct_reply)
            return direct_reply

        return "Не удалось распознать команду. Чем я могу помочь?"

    def _record_turn(self, chat_id: int, user_msg: str, assistant_msg: str) -> None:
        if chat_id not in self._history:
            self._history[chat_id] = []
        self._history[chat_id].append({"role": "user", "text": user_msg})
        self._history[chat_id].append({"role": "assistant", "text": assistant_msg})
        if len(self._history[chat_id]) > 6:
            self._history[chat_id] = self._history[chat_id][-6:]

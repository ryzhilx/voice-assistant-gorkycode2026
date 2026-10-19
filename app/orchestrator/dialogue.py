import logging
from typing import Any, Dict, List, Optional

from app.agent.agent import ToolCallingAgent
from app.ai.embeddings import SemanticSearchEngine
from app.ai.llm_client import LLMOrchestrator
from app.ai.schemas import AIAction, AIResponse
from app.config import settings
from app.orchestrator.context import DEFAULT_QUESTION, HandlerContext, PendingClarification, Reply
from app.orchestrator.formatters import format_recurrence
from app.orchestrator.handlers import get_default_handlers
from app.orchestrator.handlers.base import BaseActionHandler
from app.orchestrator.handlers.schedule import format_archive_view
from app.storage.db import Database

logger = logging.getLogger(__name__)

class DialogueOrchestrator:
    def __init__(
        self,
        llm: Optional[LLMOrchestrator] = None,
        db: Optional[Database] = None,
        search_engine: Optional[SemanticSearchEngine] = None,
        handlers: Optional[Dict[AIAction, BaseActionHandler]] = None,
        agent: Optional[ToolCallingAgent] = None
    ):
        self.llm = llm or LLMOrchestrator()
        self.db = db or Database(settings.database_path)
        self.search_engine = search_engine or SemanticSearchEngine()
        self.handlers: Dict[AIAction, BaseActionHandler] = handlers or get_default_handlers()
        self.agent: Optional[ToolCallingAgent] = agent
        self._pending: Dict[int, PendingClarification] = {}
        self._history: Dict[int, List[Dict[str, str]]] = {}
        self._last_event: Dict[int, Dict[str, Any]] = {}

    def has_pending(self, chat_id: int) -> bool:
        return chat_id in self._pending

    def reset(self, chat_id: int) -> None:
        self._pending.pop(chat_id, None)
        self._history.pop(chat_id, None)
        if self.agent:
            self.agent.reset(chat_id)

    async def aclose(self) -> None:
        if self.agent and hasattr(self.agent, "aclose") and callable(getattr(self.agent, "aclose")):
            await self.agent.aclose()
        if hasattr(self.llm, "aclose") and callable(getattr(self.llm, "aclose")):
            await self.llm.aclose()
        if hasattr(self.search_engine, "aclose") and callable(getattr(self.search_engine, "aclose")):
            await self.search_engine.aclose()

    async def handle_text(self, chat_id: int, text: str) -> Reply:
        if self.agent is not None:
            answer = await self.agent.run(chat_id, text)
            return Reply(answer)

        if hasattr(self.llm, "set_current_timezone") and callable(getattr(self.llm, "set_current_timezone")):
            try:
                tz = await self.db.get_user_timezone(chat_id)
                self.llm.set_current_timezone(tz)
            except Exception:
                pass

        pending = self._pending.get(chat_id)
        context = {"awaiting_slot": pending.slot, "draft_data": pending.draft} if pending else None
        history = self._history.get(chat_id)

        if isinstance(self.llm, LLMOrchestrator):
            result = await self.llm.parse_intent(text, context, history=history)
        else:
            result = await self.llm.parse_intent(text, context)
        reply = await self._dispatch(chat_id, result, raw_text=text)

        if chat_id not in self._history:
            self._history[chat_id] = []
        self._history[chat_id].append({"role": "user", "text": text})
        self._history[chat_id].append({"role": "assistant", "text": reply.text})
        if len(self._history[chat_id]) > 6:
            self._history[chat_id] = self._history[chat_id][-6:]

        return reply

    async def _dispatch(self, chat_id: int, result: AIResponse, raw_text: Optional[str] = None) -> Reply:
        if result.action == AIAction.ASK_CLARIFICATION:
            prev_draft = self._pending[chat_id].draft if chat_id in self._pending else {}
            new_draft = {**prev_draft, **result.params.get("draft_data", {})}
            self._pending[chat_id] = PendingClarification(
                slot=result.params.get("missing_slot"),
                draft=new_draft,
            )
            return Reply(result.params.get("question", DEFAULT_QUESTION))

        self.reset(chat_id)

        if result.action == AIAction.MULTI_ACTION or result.sub_actions:
            sub_actions = result.sub_actions or []
            replies = []
            for idx, sub in enumerate(sub_actions, 1):
                sub_reply = await self._execute_single_action(chat_id, sub.action, sub.params, sub.user_reply, raw_text=raw_text)
                replies.append(f"{idx}️⃣ {sub_reply.text}")
            return Reply("\n\n".join(replies))

        return await self._execute_single_action(chat_id, result.action, result.params, result.user_reply, raw_text=raw_text)

    async def _execute_single_action(
        self,
        chat_id: int,
        action: AIAction,
        params: Dict[str, Any],
        user_reply: Optional[str] = None,
        raw_text: Optional[str] = None
    ) -> Reply:
        handler = self.handlers.get(action)
        if not handler:
            logger.info("Unknown action=%s params=%s", action.value, params)
            return Reply("Запрос принят, но действие не определено.")

        ctx = HandlerContext(
            chat_id=chat_id,
            db=self.db,
            search_engine=self.search_engine,
            pending=self._pending,
            last_event=self._last_event,
            dispatcher=self._execute_single_action,
            raw_text=raw_text,
            user_reply=user_reply
        )
        return await handler.handle(params, ctx)

    async def get_archive_view(self, chat_id: int, filter_type: str = "all") -> str:
        return await format_archive_view(self.db, chat_id, filter_type=filter_type)

    @staticmethod
    def _format_recurrence(recurrence: Optional[str]) -> str:
        return format_recurrence(recurrence)

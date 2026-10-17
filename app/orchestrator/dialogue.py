import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.ai.llm_client import LLMOrchestrator
from app.ai.schemas import AIAction, AIResponse

logger = logging.getLogger(__name__)

DEFAULT_QUESTION = "Уточните, пожалуйста."


@dataclass
class Reply:
    text: str


@dataclass
class PendingClarification:
    slot: Optional[str]
    draft: Dict[str, Any]


class DialogueOrchestrator:
    """Transport-agnostic dialogue core: FSM (pending clarification per chat),
    LLM intent parsing and dispatch of the resulting action."""

    def __init__(self, llm: Optional[LLMOrchestrator] = None):
        self.llm = llm or LLMOrchestrator()
        self._pending: Dict[int, PendingClarification] = {}

    def has_pending(self, chat_id: int) -> bool:
        return chat_id in self._pending

    def reset(self, chat_id: int) -> None:
        self._pending.pop(chat_id, None)

    async def handle_text(self, chat_id: int, text: str) -> Reply:
        pending = self._pending.get(chat_id)
        context = {"awaiting_slot": pending.slot, "draft_data": pending.draft} if pending else None

        result = await self.llm.parse_intent(text, context)
        return await self._dispatch(chat_id, result)

    async def _dispatch(self, chat_id: int, result: AIResponse) -> Reply:
        if result.action == AIAction.ASK_CLARIFICATION:
            self._pending[chat_id] = PendingClarification(
                slot=result.params.get("missing_slot"),
                draft=result.params.get("draft_data", {}),
            )
            return Reply(result.params.get("question", DEFAULT_QUESTION))

        self.reset(chat_id)
        
        logger.info("Parsed action=%s params=%s", result.action.value, result.params)
        return Reply(f"[stage 1] action={result.action.value}\nparams={result.params}")

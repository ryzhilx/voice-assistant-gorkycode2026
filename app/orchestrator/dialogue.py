import inspect
import logging
from typing import Any, Dict, Optional

from app.agent.agent import ToolCallingAgent
from app.ai.embeddings import SemanticSearchEngine
from app.config import settings
from app.orchestrator.context import Reply
from app.orchestrator.formatters import format_archive_view
from app.storage.db import Database

logger = logging.getLogger(__name__)

class DialogueOrchestrator:
    def __init__(
        self,
        db: Optional[Database] = None,
        search_engine: Optional[SemanticSearchEngine] = None,
        agent: Optional[ToolCallingAgent] = None,
        llm: Any = None
    ):
        self.db = db or Database(settings.database_path)
        self.search_engine = search_engine or SemanticSearchEngine()
        self.agent = agent or ToolCallingAgent(db=self.db, search_engine=self.search_engine, llm=llm)

    @property
    def _last_event(self) -> Dict[int, Dict[str, Any]]:
        return self.agent._last_event

    def has_pending(self, chat_id: int) -> bool:
        return False

    def reset(self, chat_id: int) -> None:
        if self.agent:
            self.agent.reset(chat_id)

    async def aclose(self) -> None:
        if self.agent and hasattr(self.agent, "aclose") and callable(getattr(self.agent, "aclose")):
            res = self.agent.aclose()
            if inspect.isawaitable(res):
                await res
        if hasattr(self.search_engine, "aclose") and callable(getattr(self.search_engine, "aclose")):
            res = self.search_engine.aclose()
            if inspect.isawaitable(res):
                await res

    async def handle_text(self, chat_id: int, text: str) -> Reply:
        answer = await self.agent.run(chat_id, text)
        return Reply(answer)

    async def get_archive_view(self, chat_id: int, filter_type: str = "all") -> str:
        return await format_archive_view(self.db, chat_id, filter_type=filter_type)


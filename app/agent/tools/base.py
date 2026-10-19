from abc import ABC, abstractmethod
from typing import Any, Dict
from app.agent.schemas import ToolDefinition, ToolExecutionResult
from app.storage.db import Database
from app.ai.embeddings import SemanticSearchEngine

class BaseTool(ABC):
    def __init__(
        self,
        db: Database,
        search_engine: SemanticSearchEngine,
        last_event_store: Dict[int, Dict[str, Any]]
    ):
        self.db = db
        self.search_engine = search_engine
        self.last_event_store = last_event_store

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        pass

    @abstractmethod
    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        pass

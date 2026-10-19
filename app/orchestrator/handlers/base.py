from abc import ABC, abstractmethod
from typing import Any, Dict
from app.orchestrator.context import HandlerContext, Reply

class BaseActionHandler(ABC):
    @abstractmethod
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        pass

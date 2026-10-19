from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional
from app.ai.schemas import AIAction
from app.storage.db import Database
from app.ai.embeddings import SemanticSearchEngine

DEFAULT_QUESTION = "Уточните, пожалуйста."

@dataclass
class Reply:
    text: str

@dataclass
class PendingClarification:
    slot: Optional[str]
    draft: Dict[str, Any]

@dataclass
class HandlerContext:
    chat_id: int
    db: Database
    search_engine: SemanticSearchEngine
    pending: Dict[int, PendingClarification]
    last_event: Dict[int, Dict[str, Any]]
    dispatcher: Callable[[AIAction, Dict[str, Any], Optional[str], Optional[str]], Awaitable[Reply]]
    raw_text: Optional[str] = None
    user_reply: Optional[str] = None

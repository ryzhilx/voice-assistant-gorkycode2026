from dataclasses import dataclass
from typing import Any, Dict, Optional

DEFAULT_QUESTION = "Уточните, пожалуйста."

@dataclass
class Reply:
    text: str

@dataclass
class PendingClarification:
    slot: Optional[str]
    draft: Dict[str, Any]

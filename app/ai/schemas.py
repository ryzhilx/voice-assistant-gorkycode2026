from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal

class FilterType(str, Enum):
    ALL = "all"
    TASKS = "tasks"
    MEETINGS = "meetings"

class AIAction(str, Enum):
    CREATE_TASK = "create_task"
    CREATE_MEETING = "create_meeting"
    GET_SCHEDULE = "get_schedule"
    GET_ARCHIVE = "get_archive"
    SEARCH_RECORDS = "search_records"
    ASK_CLARIFICATION = "ask_clarification"
    CHAT = "chat"
    UNKNOWN = "unknown"

@dataclass
class CreateTaskParams:
    title: str
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    is_reminder: bool = False

@dataclass
class CreateMeetingParams:
    title: str
    start_date: str
    start_time: str
    duration_minutes: int = 60
    participants: Optional[str] = None

@dataclass
class GetScheduleParams:
    start_date: str
    end_date: Optional[str] = None
    filter_type: FilterType = FilterType.ALL

@dataclass
class SearchRecordsParams:
    query: str
    record_type: FilterType = FilterType.ALL

@dataclass
class AskClarificationParams:
    missing_slot: Literal["time", "date", "title", "details"]
    question: str
    draft_data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AIResponse:
    action: AIAction
    params: Dict[str, Any]
    user_reply: Optional[str] = None

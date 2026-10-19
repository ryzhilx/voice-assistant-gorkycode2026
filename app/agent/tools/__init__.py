from typing import Any, Dict, List
from app.agent.schemas import ToolDefinition
from app.agent.tools.base import BaseTool
from app.agent.tools.task import CreateTaskTool, CompleteTaskTool
from app.agent.tools.meeting import CreateMeetingTool
from app.agent.tools.schedule import GetScheduleTool, GetArchiveTool, SearchRecordsTool
from app.agent.tools.reschedule import RescheduleRecordTool
from app.agent.tools.manage import DeleteRecordTool, UpdateRecordTitleTool
from app.storage.db import Database
from app.ai.embeddings import SemanticSearchEngine

def build_default_tools(
    db: Database,
    search_engine: SemanticSearchEngine,
    last_event_store: Dict[int, Dict[str, Any]]
) -> Dict[str, BaseTool]:
    tools_list = [
        CreateTaskTool(db, search_engine, last_event_store),
        CompleteTaskTool(db, search_engine, last_event_store),
        CreateMeetingTool(db, search_engine, last_event_store),
        GetScheduleTool(db, search_engine, last_event_store),
        GetArchiveTool(db, search_engine, last_event_store),
        SearchRecordsTool(db, search_engine, last_event_store),
        RescheduleRecordTool(db, search_engine, last_event_store),
        DeleteRecordTool(db, search_engine, last_event_store),
        UpdateRecordTitleTool(db, search_engine, last_event_store),
    ]
    return {tool.definition.name: tool for tool in tools_list}

def get_tools_json_schema(tools: Dict[str, BaseTool]) -> List[Dict[str, Any]]:
    return [tool.definition.to_json_schema() for tool in tools.values()]

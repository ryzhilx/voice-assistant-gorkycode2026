from typing import Any, Dict
from app.agent.tools.meeting import CreateMeetingTool
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class CreateMeetingHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        tool = CreateMeetingTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, **params)
        return Reply(res.output)

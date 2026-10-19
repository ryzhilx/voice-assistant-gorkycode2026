from typing import Any, Dict
from app.agent.tools.task import CreateTaskTool, CompleteTaskTool
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class CreateTaskHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        tool = CreateTaskTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, **params)
        return Reply(res.output)

class CompleteRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        tool = CompleteTaskTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, **params)
        return Reply(res.output)

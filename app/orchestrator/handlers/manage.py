from typing import Any, Dict
from app.agent.tools.manage import DeleteRecordTool, UpdateRecordTitleTool
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class DeleteRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        tool = DeleteRecordTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, **params)
        return Reply(res.output)

class UpdateRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        tool = UpdateRecordTitleTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, **params)
        return Reply(res.output)

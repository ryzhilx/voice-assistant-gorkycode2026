from typing import Any, Dict
from app.agent.tools.schedule import GetScheduleTool, GetArchiveTool
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.formatters import format_archive_view
from app.orchestrator.handlers.base import BaseActionHandler

class GetScheduleHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        f_type = params.get("filter_type", "all")
        if f_type == "archive":
            text_view = await format_archive_view(ctx.db, ctx.chat_id, filter_type="all")
            return Reply(text_view)
        tool = GetScheduleTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, **params)
        return Reply(res.output)

class GetArchiveHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        f_type = params.get("filter_type", "all")
        if f_type == "archive":
            f_type = "all"
        tool = GetArchiveTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, filter_type=f_type)
        return Reply(res.output)

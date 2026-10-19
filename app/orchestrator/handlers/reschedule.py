from typing import Any, Dict
from app.agent.tools.reschedule import RescheduleRecordTool
from app.orchestrator.context import HandlerContext, PendingClarification, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class RescheduleRecordHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        new_date = params.get("new_date")
        new_time = params.get("new_time")
        if not new_date and not new_time:
            draft_d = {"action": "reschedule_record", "target": params.get("target", "last")}
            if params.get("query"):
                draft_d["query"] = params.get("query")
            ctx.pending[ctx.chat_id] = PendingClarification(
                slot="time",
                draft=draft_d
            )
            return Reply("На какую дату или время перенести?")

        tool = RescheduleRecordTool(ctx.db, ctx.search_engine, ctx.last_event)
        res = await tool.execute(ctx.chat_id, **params)
        return Reply(res.output)

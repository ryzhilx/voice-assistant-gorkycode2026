from typing import Any, Dict
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class ChatHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        reply_text = params.get("reply") or ctx.user_reply or "Чем я могу вам помочь?"
        return Reply(reply_text)

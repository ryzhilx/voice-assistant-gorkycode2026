import re
from typing import Any, Dict
from app.ai.schemas import AIAction
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class ChatHandler(BaseActionHandler):
    past_pattern = re.compile(
        r"^(?:я\s+)?(выпил|выпила|попил|попила|позвонил|позвонила|набрал|набрала|купил|купила|сделал|сделала|выполнил|выполнила|отправил|отправила|принял|приняла|сходил|сходила|пошел|пошла|забрал|забрала|оплатил|оплатила|закрыл|закрыла|полил|полила|съел|съела|поел|поела|прочитал|прочитала|сдал|сдала|закончил|закончила|написал|написала|перевел|перевела|решил|решила)\b",
        re.IGNORECASE
    )

    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        if ctx.raw_text:
            low = ctx.raw_text.lower().strip()
            if self.past_pattern.search(low):
                records = await ctx.db.get_all_records_for_search(ctx.chat_id, "tasks")
                pending = [r for r in records if r.get("status") not in ("completed", "archived")]
                if pending:
                    matches = ctx.search_engine.rank_records(ctx.raw_text, pending, top_k=1)
                    if matches:
                        return await ctx.dispatcher(
                            AIAction.COMPLETE_RECORD,
                            {"target": "task", "query": ctx.raw_text},
                            None,
                            ctx.raw_text
                        )

        reply_text = params.get("reply") or ctx.user_reply or "Чем я могу вам помочь?"
        return Reply(reply_text)

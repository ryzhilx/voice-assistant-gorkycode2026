from typing import Any, Dict
from app.orchestrator.context import HandlerContext, Reply
from app.orchestrator.handlers.base import BaseActionHandler

class SearchRecordsHandler(BaseActionHandler):
    async def handle(self, params: Dict[str, Any], ctx: HandlerContext) -> Reply:
        query = params.get("query", "").strip()
        record_type = params.get("record_type", "all")

        records = await ctx.db.get_all_records_for_search(ctx.chat_id, record_type)
        if not records:
            return Reply(f"По запросу «{query}» ничего не найдено.")

        matches = ctx.search_engine.rank_records(query, records, top_k=3)
        if not matches:
            return Reply(f"По запросу «{query}» ничего не найдено.")

        lines = [f"Найдено по запросу «{query}»:"]
        for m in matches:
            kind = "Встреча" if m.get("type") == "meeting" else "Задача"
            date_str = f" ({m.get('date')})" if m.get("date") else ""
            archived_tag = " [Архив]" if m.get("status") == "archived" else ""
            lines.append(f"- [{kind}]{archived_tag} {m.get('title')}{date_str}")

        if matches:
            top_m = matches[0]
            ctx.last_event[ctx.chat_id] = {
                "id": top_m.get("id"),
                "title": top_m.get("title"),
                "date": top_m.get("date"),
                "time": top_m.get("time"),
                "type": top_m.get("type")
            }

        return Reply("\n".join(lines))

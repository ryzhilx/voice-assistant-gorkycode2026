import datetime
from typing import Any, Dict, List
from app.agent.schemas import ToolDefinition, ToolExecutionResult, ToolParameter
from app.agent.tools.base import BaseTool
from app.orchestrator.formatters import format_recurrence
from app.orchestrator.handlers.schedule import format_archive_view

class GetScheduleTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_schedule",
            description="Возвращает расписание встреч и задач пользователя за указанный день или период дат.",
            parameters={
                "start_date": ToolParameter(
                    type="string",
                    description="Начальная дата в формате YYYY-MM-DD (если не указана, берется сегодня)."
                ),
                "end_date": ToolParameter(
                    type="string",
                    description="Конечная дата в формате YYYY-MM-DD (если не указана, равна начальной)."
                ),
                "filter_type": ToolParameter(
                    type="string",
                    description="Фильтр записей: all (все), meetings (только встречи), tasks (только задачи).",
                    enum=["all", "meetings", "tasks"]
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        tz_str = await self.db.get_user_timezone(chat_id)
        try:
            from zoneinfo import ZoneInfo
            now_date = datetime.datetime.now(ZoneInfo(tz_str)).date()
        except Exception:
            now_date = datetime.datetime.now().date()
        now_str = str(now_date)

        start_date = kwargs.get("start_date") or now_str
        end_date = kwargs.get("end_date") or start_date
        filter_type = kwargs.get("filter_type", "all") or "all"

        data = await self.db.get_schedule(chat_id, start_date, end_date, filter_type)
        tasks = data.get("tasks", [])
        meetings = data.get("meetings", [])

        if not tasks and not meetings:
            if start_date == now_str and end_date == now_str:
                period_text = f"сегодня ({start_date})"
            elif start_date == end_date:
                period_text = start_date
            else:
                period_text = f"период с {start_date} по {end_date}"

            target = "нет активных встреч и задач (прошедшие события перемещены в архив)"
            if filter_type == "meetings":
                target = "нет запланированных встреч"
            elif filter_type == "tasks":
                target = "нет активных задач"

            return ToolExecutionResult(
                tool_name="get_schedule",
                success=True,
                output=f"На {period_text} {target}.",
                data=data
            )

        lines: List[str] = []
        if start_date == now_str and end_date == now_str:
            period_str = f"сегодня, {start_date}"
        elif start_date == end_date:
            period_str = start_date
        else:
            period_str = f"{start_date} — {end_date}"
        lines.append(f"Расписание ({period_str}):")

        if meetings:
            lines.append("\nВстречи:")
            for m in meetings:
                t = m.get("start_time") or ""
                title = m.get("title")
                rec_badge = f" (🔄 {format_recurrence(m.get('recurrence'))})" if m.get("recurrence") else ""
                lines.append(f"- {t} {title}{rec_badge}")

        if tasks:
            lines.append("\nЗадачи:")
            for t in tasks:
                status = "[x]" if t.get("status") == "completed" else "[ ]"
                tm = f" (до {t.get('due_time')})" if t.get("due_time") else ""
                rec_badge = f" (🔄 {format_recurrence(t.get('recurrence'))})" if t.get("recurrence") else ""
                lines.append(f"{status} {t.get('title')}{tm}{rec_badge}")

        return ToolExecutionResult(
            tool_name="get_schedule",
            success=True,
            output="\n".join(lines),
            data=data
        )

class GetArchiveTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_archive",
            description="Показывает архив прошедших встреч и выполненных задач пользователя.",
            parameters={
                "filter_type": ToolParameter(
                    type="string",
                    description="Фильтр: all (все), meetings (прошедшие встречи), tasks (завершенные задачи).",
                    enum=["all", "meetings", "tasks"]
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        filter_type = kwargs.get("filter_type", "all") or "all"
        text_view = await format_archive_view(self.db, chat_id, filter_type=filter_type)
        return ToolExecutionResult(
            tool_name="get_archive",
            success=True,
            output=text_view
        )

class SearchRecordsTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_records",
            description="Выполняет семантический поиск по прошлым и текущим задачам и встречам.",
            parameters={
                "query": ToolParameter(
                    type="string",
                    description="Поисковый запрос по смыслу или названию (например, «дизайнер», «отчет»).",
                    required=True
                ),
                "record_type": ToolParameter(
                    type="string",
                    description="Тип записей: all, meetings, tasks.",
                    enum=["all", "meetings", "tasks"]
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        query = kwargs.get("query", "").strip()
        record_type = kwargs.get("record_type", "all") or "all"

        records = await self.db.get_all_records_for_search(chat_id, record_type)
        if not records:
            return ToolExecutionResult(
                tool_name="search_records",
                success=True,
                output=f"По запросу «{query}» ничего не найдено."
            )

        matches = self.search_engine.rank_records(query, records, top_k=3)
        if not matches:
            return ToolExecutionResult(
                tool_name="search_records",
                success=True,
                output=f"По запросу «{query}» ничего не найдено."
            )

        lines = [f"Найдено по запросу «{query}»:"]
        for m in matches:
            kind = "Встреча" if m.get("type") == "meeting" else "Задача"
            date_str = f" ({m.get('date')})" if m.get("date") else ""
            archived_tag = " [Архив]" if m.get("status") == "archived" else ""
            lines.append(f"- [{kind}]{archived_tag} {m.get('title')}{date_str}")

        if matches:
            top_m = matches[0]
            self.last_event_store[chat_id] = {
                "id": top_m.get("id"),
                "title": top_m.get("title"),
                "date": top_m.get("date"),
                "time": top_m.get("time"),
                "type": top_m.get("type")
            }

        return ToolExecutionResult(
            tool_name="search_records",
            success=True,
            output="\n".join(lines),
            data={"matches": matches}
        )

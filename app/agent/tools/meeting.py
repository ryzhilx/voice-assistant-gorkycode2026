from typing import Any, Dict
from app.agent.schemas import ToolDefinition, ToolExecutionResult, ToolParameter
from app.agent.tools.base import BaseTool
from app.orchestrator.formatters import format_recurrence

class CreateMeetingTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="create_meeting",
            description="Назначает встречу или созвон в календаре на указанную дату и время.",
            parameters={
                "title": ToolParameter(
                    type="string",
                    description="Название встречи или тема созвона (например, «Встреча с Михаилом»).",
                    required=True
                ),
                "start_date": ToolParameter(
                    type="string",
                    description="Дата встречи в формате YYYY-MM-DD.",
                    required=True
                ),
                "start_time": ToolParameter(
                    type="string",
                    description="Время начала встречи в формате 24h HH:MM.",
                    required=True
                ),
                "duration_minutes": ToolParameter(
                    type="integer",
                    description="Длительность встречи в минутах (по умолчанию 60)."
                ),
                "participants": ToolParameter(
                    type="string",
                    description="Участники встречи через запятую (например, «Иван, Анна»)."
                ),
                "recurrence": ToolParameter(
                    type="string",
                    description="Периодичность: daily, weekdays, weekends, weekly:mon, weekly:fri, monthly."
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        title = kwargs.get("title", "Встреча")
        start_date = kwargs.get("start_date")
        start_time = kwargs.get("start_time")
        duration = int(kwargs.get("duration_minutes", 60) or 60)
        participants = kwargs.get("participants")
        recurrence = kwargs.get("recurrence")

        if not start_date or not start_time:
            return ToolExecutionResult(
                tool_name="create_meeting",
                success=False,
                output="Для создания встречи обязательно укажите дату и время."
            )

        conflict = await self.db.check_meeting_conflict(chat_id, start_date, start_time, recurrence=recurrence)
        meeting_id = await self.db.add_meeting(
            user_id=chat_id,
            title=title,
            start_date=start_date,
            start_time=start_time,
            duration_minutes=duration,
            participants=participants,
            recurrence=recurrence
        )

        self.last_event_store[chat_id] = {
            "id": meeting_id,
            "title": title,
            "date": start_date,
            "time": start_time,
            "type": "meeting",
            "recurrence": recurrence
        }

        rec_badge = f" (🔄 {format_recurrence(recurrence)})" if recurrence else ""
        if title.strip().lower() in ["встреча", "созвон", "meeting"]:
            text = f"Встреча назначена на {start_date} в {start_time}{rec_badge}."
        else:
            text = f"Встреча «{title}» назначена на {start_date} в {start_time}{rec_badge}."

        if conflict:
            text += f"\nВнимание: в это же время уже стоит «{conflict.get('title')}»."

        return ToolExecutionResult(
            tool_name="create_meeting",
            success=True,
            output=text,
            data={"id": meeting_id, "conflict": bool(conflict)}
        )

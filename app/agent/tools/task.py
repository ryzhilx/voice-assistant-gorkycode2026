from typing import Any, Dict
from app.agent.schemas import ToolDefinition, ToolExecutionResult, ToolParameter
from app.agent.tools.base import BaseTool
from app.agent.tools.validation import (
    ToolValidationError,
    normalize_bool,
    normalize_date,
    normalize_recurrence,
    normalize_time,
    normalize_title,
    today_in_timezone,
)
from app.orchestrator.formatters import format_recurrence
from app.storage.db import Database

class CreateTaskTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="create_task",
            description="Создает новую задачу или напоминание для пользователя.",
            parameters={
                "title": ToolParameter(
                    type="string",
                    description="Название или краткое описание задачи/напоминания.",
                    required=True
                ),
                "due_date": ToolParameter(
                    type="string",
                    description="Дата дедлайна или напоминания в формате YYYY-MM-DD."
                ),
                "due_time": ToolParameter(
                    type="string",
                    description="Время дедлайна или напоминания в формате 24h HH:MM."
                ),
                "is_reminder": ToolParameter(
                    type="boolean",
                    description="True, если это напоминание (пользователь просит напомнить)."
                ),
                "recurrence": ToolParameter(
                    type="string",
                    description="Периодичность: daily, weekdays, weekends, weekly, weekly:mon, weekly:fri, monthly."
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        try:
            title = normalize_title(kwargs.get("title"), "Задача")
            due_date = normalize_date(kwargs.get("due_date"))
            due_time = normalize_time(kwargs.get("due_time"))
            is_reminder = normalize_bool(kwargs.get("is_reminder"), False)
            recurrence = normalize_recurrence(kwargs.get("recurrence"))

            timezone = await self.db.get_user_timezone(chat_id)
            if (is_reminder or recurrence) and not due_date:
                due_date = today_in_timezone(timezone)

            if is_reminder and not due_time:
                return ToolExecutionResult(
                    tool_name="create_task",
                    success=False,
                    output="Для напоминания нужно указать время. Например: «Напомни завтра в 10:00 позвонить врачу»."
                )
        except ToolValidationError as exc:
            return ToolExecutionResult(tool_name="create_task", success=False, output=str(exc))

        task_id = await self.db.add_task(
            user_id=chat_id,
            title=title,
            due_date=due_date,
            due_time=due_time,
            is_reminder=is_reminder,
            recurrence=recurrence
        )

        self.last_event_store[chat_id] = {
            "id": task_id,
            "title": title,
            "date": due_date,
            "time": due_time,
            "type": "task",
            "is_reminder": is_reminder,
            "recurrence": recurrence
        }

        date_info = f" на {due_date}" if due_date else ""
        time_info = f" в {due_time}" if due_time else ""
        rec_badge = f" (🔄 {format_recurrence(recurrence)})" if recurrence else ""
        prefix = "Напоминание установлено" if is_reminder else "Задача добавлена"
        if title.strip().lower() in ["задача", "напоминание", "task"]:
            text = f"{prefix}{date_info}{time_info}{rec_badge}."
        else:
            text = f"{prefix}: «{title}»{date_info}{time_info}{rec_badge}."

        return ToolExecutionResult(
            tool_name="create_task",
            success=True,
            output=text,
            data={"id": task_id, "title": title, "due_date": due_date, "due_time": due_time}
        )

class CompleteTaskTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="complete_task",
            description="Отмечает задачу как выполненную по ее названию или последнюю активную задачу.",
            parameters={
                "query": ToolParameter(
                    type="string",
                    description="Название или ключевые слова выполненной задачи."
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        query = str(kwargs.get("query") or "").strip()
        record = None

        if query:
            records = await self.db.get_all_records_for_search(chat_id, "tasks")
            if records:
                pending_records = [r for r in records if r.get("status") not in ("completed", "archived")]
                cands = pending_records if pending_records else records
                matches = await self.search_engine.rank_records_async(query, cands, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = self.last_event_store.get(chat_id)
            if not record or record.get("type") != "task":
                record = await self.db.get_latest_record(chat_id, "task")

        if not record or record.get("type") != "task":
            return ToolExecutionResult(
                tool_name="complete_task",
                success=False,
                output="Не удалось найти задачу для отметки выполненной. Уточните название задачи."
            )

        rec_id = record["id"]
        title = record.get("title", "Задача")
        recurrence = record.get("recurrence")
        success = await self.db.mark_task_completed(chat_id, rec_id)

        if success:
            if recurrence:
                timezone = await self.db.get_user_timezone(chat_id)
                today_str = today_in_timezone(timezone)
                next_d = Database.calculate_next_occurrence(record.get("date") or today_str, recurrence, from_date=today_str)
                self.last_event_store[chat_id] = {**record, "date": next_d, "status": "pending"}
                return ToolExecutionResult(
                    tool_name="complete_task",
                    success=True,
                    output=f"Задача «{title}» выполнена! Следующее повторение запланировано на {next_d}. ✅",
                    data={"id": rec_id, "next_date": next_d}
                )
            self.last_event_store[chat_id] = {**record, "status": "completed"}
            return ToolExecutionResult(
                tool_name="complete_task",
                success=True,
                output=f"Задача «{title}» отмечена как выполненная! ✅",
                data={"id": rec_id}
            )

        return ToolExecutionResult(
            tool_name="complete_task",
            success=False,
            output=f"Не удалось обновить статус задачи «{title}»."
        )

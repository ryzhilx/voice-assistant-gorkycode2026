from typing import Any, Dict
from app.agent.schemas import ToolDefinition, ToolExecutionResult, ToolParameter
from app.agent.tools.base import BaseTool
from app.agent.tools.validation import ToolValidationError, normalize_target

class DeleteRecordTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="delete_record",
            description="Удаляет задачу или встречу (последнюю или найденную по названию).",
            parameters={
                "target": ToolParameter(
                    type="string",
                    description="Тип записи: last, meeting, task.",
                    enum=["last", "meeting", "task"]
                ),
                "query": ToolParameter(
                    type="string",
                    description="Название или ключевые слова удаляемой записи."
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        try:
            target = normalize_target(kwargs.get("target"), "last")
        except ToolValidationError as exc:
            return ToolExecutionResult(tool_name="delete_record", success=False, output=str(exc))
        query = str(kwargs.get("query") or "").strip()
        record = None

        if query:
            records = await self.db.get_all_records_for_search(chat_id, target if target in ("meeting", "task") else "all")
            if records:
                matches = await self.search_engine.rank_records_async(query, records, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = self.last_event_store.get(chat_id)
            if not record or (target in ("meeting", "task") and record.get("type") != target):
                record = await self.db.get_latest_record(chat_id, target)

        if not record:
            return ToolExecutionResult(
                tool_name="delete_record",
                success=False,
                output="Не удалось найти запись для удаления. Уточните название задачи или встречи."
            )

        rec_type = record.get("type", "task")
        rec_id = record["id"]
        title = record.get("title", "Запись")

        success = await self.db.delete_record(chat_id, rec_type, rec_id)
        if success:
            if self.last_event_store.get(chat_id, {}).get("id") == rec_id:
                self.last_event_store.pop(chat_id, None)
            if rec_type == "meeting":
                return ToolExecutionResult(
                    tool_name="delete_record",
                    success=True,
                    output=f"Встреча «{title}» успешно отменена и удалена. 🗑️",
                    data={"id": rec_id}
                )
            return ToolExecutionResult(
                tool_name="delete_record",
                success=True,
                output=f"Задача «{title}» успешно удалена. 🗑️",
                data={"id": rec_id}
            )

        return ToolExecutionResult(
            tool_name="delete_record",
            success=False,
            output=f"Не удалось удалить запись «{title}»."
        )

class UpdateRecordTitleTool(BaseTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="update_record_title",
            description="Изменяет название или текст задачи или встречи.",
            parameters={
                "new_title": ToolParameter(
                    type="string",
                    description="Новое название задачи или встречи.",
                    required=True
                ),
                "target": ToolParameter(
                    type="string",
                    description="Тип записи: last, meeting, task.",
                    enum=["last", "meeting", "task"]
                ),
                "query": ToolParameter(
                    type="string",
                    description="Старое название для поиска нужной записи."
                )
            }
        )

    async def execute(self, chat_id: int, **kwargs: Any) -> ToolExecutionResult:
        try:
            target = normalize_target(kwargs.get("target"), "last")
        except ToolValidationError as exc:
            return ToolExecutionResult(tool_name="update_record_title", success=False, output=str(exc))
        new_title = str(kwargs.get("new_title") or "").strip()
        query = str(kwargs.get("query") or "").strip()

        if not new_title:
            return ToolExecutionResult(
                tool_name="update_record_title",
                success=False,
                output="Укажите новое название для задачи или встречи."
            )

        record = None
        if query:
            records = await self.db.get_all_records_for_search(chat_id, target if target in ("meeting", "task") else "all")
            if records:
                matches = await self.search_engine.rank_records_async(query, records, top_k=1)
                if matches:
                    record = matches[0]

        if not record:
            record = self.last_event_store.get(chat_id)
            if not record or (target in ("meeting", "task") and record.get("type") != target):
                record = await self.db.get_latest_record(chat_id, target)

        if not record:
            return ToolExecutionResult(
                tool_name="update_record_title",
                success=False,
                output="Не удалось найти запись для изменения. Уточните название задачи или встречи."
            )

        rec_type = record.get("type", "task")
        rec_id = record["id"]
        old_title = record.get("title", "")

        success = await self.db.update_record_title(chat_id, rec_type, rec_id, new_title)
        if success:
            self.last_event_store[chat_id] = {**record, "title": new_title}
            kind = "Встреча" if rec_type == "meeting" else "Задача"
            return ToolExecutionResult(
                tool_name="update_record_title",
                success=True,
                output=f"{kind} «{old_title}» переименована в «{new_title}». ✏️",
                data={"id": rec_id, "new_title": new_title}
            )

        return ToolExecutionResult(
            tool_name="update_record_title",
            success=False,
            output=f"Не удалось обновить запись «{old_title}»."
        )

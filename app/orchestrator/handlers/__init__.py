from typing import Dict
from app.ai.schemas import AIAction
from app.orchestrator.handlers.base import BaseActionHandler
from app.orchestrator.handlers.chat import ChatHandler
from app.orchestrator.handlers.task import CreateTaskHandler, CompleteRecordHandler
from app.orchestrator.handlers.meeting import CreateMeetingHandler
from app.orchestrator.handlers.schedule import GetScheduleHandler, GetArchiveHandler
from app.orchestrator.handlers.search import SearchRecordsHandler
from app.orchestrator.handlers.reschedule import RescheduleRecordHandler
from app.orchestrator.handlers.manage import DeleteRecordHandler, UpdateRecordHandler

def get_default_handlers() -> Dict[AIAction, BaseActionHandler]:
    return {
        AIAction.CHAT: ChatHandler(),
        AIAction.CREATE_TASK: CreateTaskHandler(),
        AIAction.CREATE_MEETING: CreateMeetingHandler(),
        AIAction.GET_SCHEDULE: GetScheduleHandler(),
        AIAction.GET_ARCHIVE: GetArchiveHandler(),
        AIAction.SEARCH_RECORDS: SearchRecordsHandler(),
        AIAction.RESCHEDULE_RECORD: RescheduleRecordHandler(),
        AIAction.COMPLETE_RECORD: CompleteRecordHandler(),
        AIAction.DELETE_RECORD: DeleteRecordHandler(),
        AIAction.UPDATE_RECORD: UpdateRecordHandler(),
    }

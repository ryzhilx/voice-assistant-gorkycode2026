from aiogram.fsm.state import State, StatesGroup


class Clarification(StatesGroup):
    waiting_slot = State()

"""Состояния конечного автома (FSM) диалога."""
from aiogram.fsm.state import State, StatesGroup


class Booking(StatesGroup):
    dates = State()      # выбор дат заезда/выезда в inline-календаре
    guests = State()     # количество гостей
    unit_type = State()  # тип размещения
    unit_pick = State()  # витрина: выбор конкретного домика/номера
    wishes = State()     # пожелания (мультивыбор)
    contact = State()    # имя + телефон
    summary = State()    # сводка, подтверждение


class Escalation(StatesGroup):
    chat = State()       # диалог с живым администратором

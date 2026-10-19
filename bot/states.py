"""Шаги анкеты заявки (FSM)."""

from maxapi.context.state_machine import State, StatesGroup


class RequestForm(StatesGroup):
    requester = State()   # кто заказывает
    item = State()        # что заказывает
    quantity = State()    # сколько
    deadline = State()    # к какому сроку
    purpose = State()     # зачем
    example = State()     # ссылка или фото (необязательно)
    confirm = State()     # проверка перед отправкой

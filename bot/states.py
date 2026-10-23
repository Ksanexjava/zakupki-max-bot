"""Шаги анкеты заявки (FSM)."""

from maxapi.context.state_machine import State, StatesGroup


class RequestForm(StatesGroup):
    requester = State()      # кто заказывает
    mode = State()           # одна позиция / несколько / списком

    item = State()           # название позиции
    quantity = State()       # количество позиции
    example = State()        # ссылка или фото позиции
    more = State()           # добавить ещё позицию?

    bulk_list = State()      # вставка всего списка одним сообщением
    fix_quantity = State()   # дозапрос количеств для позиций из списка

    deadline = State()       # к какому сроку (общее на заявку)
    purpose = State()        # зачем (общее на заявку)
    confirm = State()        # проверка перед отправкой

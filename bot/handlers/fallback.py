"""Всё, что не поймали остальные роутеры. Подключается последним."""

from maxapi.context.base import BaseContext
from maxapi.dispatcher import Router
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from bot import keyboards as kb
from bot import texts
from bot.states import RequestForm

router = Router(router_id="fallback")

#: шаги, где ответ ожидается кнопкой, а не текстом
BUTTON_STEPS = {str(RequestForm.confirm)}


@router.message_created()
async def on_any_message(event: MessageCreated, context: BaseContext) -> None:
    state = await context.get_state()
    if state is None:
        await event.message.answer(text=texts.UNKNOWN, attachments=kb.main_menu_kb())
    elif str(state) in BUTTON_STEPS:
        await event.message.answer(text=texts.USE_BUTTONS, attachments=kb.confirm_kb())
    else:
        await event.message.answer(texts.EMPTY_TEXT)


@router.message_callback()
async def on_any_callback(event: MessageCallback) -> None:
    await event.answer(notification=texts.STALE_BUTTON)

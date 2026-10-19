"""Приветствие, меню, справка, список своих заявок."""

from typing import Any

from maxapi import F
from maxapi.context.base import BaseContext
from maxapi.dispatcher import Router
from maxapi.filters.command import Command, CommandStart
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from bot import keyboards as kb
from bot import texts
from bot.handlers.request import display_name, start_form
from db import repo

router = Router(router_id="start")


def answer_to(bot: Any, user_id: int):
    """Функция отправки сообщения пользователю — когда исходного сообщения нет."""

    async def answer(text: str | None = None, attachments: Any = None, format: Any = None) -> Any:
        return await bot.send_message(
            user_id=user_id, text=text, attachments=attachments, format=format
        )

    return answer


@router.bot_started()
async def on_bot_started(event: BotStarted, context: BaseContext) -> None:
    """Пользователь впервые открыл бота (кнопка «Начать»)."""
    await context.clear()
    await event.bot.send_message(
        user_id=event.user.user_id,
        text=texts.WELCOME.format(name=display_name(event.user)),
        attachments=kb.main_menu_kb(),
    )


@router.message_created(CommandStart())
async def on_start(event: MessageCreated, context: BaseContext) -> None:
    await context.clear()
    await event.message.answer(
        text=texts.WELCOME.format(name=display_name(event.message.sender)),
        attachments=kb.main_menu_kb(),
    )


@router.message_created(Command("help"))
async def on_help(event: MessageCreated) -> None:
    await event.message.answer(text=texts.HELP, attachments=kb.main_menu_kb())


@router.message_created(Command(["new", "zayavka"]))
async def on_new(event: MessageCreated, context: BaseContext) -> None:
    chat_id = event.message.recipient.chat_id if event.message.recipient else None
    await start_form(event.message.answer, context, event.message.sender, chat_id)


@router.message_created(Command("cancel"))
async def on_cancel(event: MessageCreated, context: BaseContext) -> None:
    if await context.get_state() is None:
        await event.message.answer(texts.NOTHING_TO_CANCEL)
        return
    await context.clear()
    await event.message.answer(text=texts.CANCELLED, attachments=kb.main_menu_kb())


@router.message_created(Command("my"))
async def on_my(event: MessageCreated) -> None:
    await _send_my_requests(event.message.answer, event.message.sender.user_id)


@router.message_callback(F.callback.payload == kb.MENU_NEW)
async def on_menu_new(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    chat_id = event.message.recipient.chat_id if event.message and event.message.recipient else None
    await start_form(event.message.answer, context, event.callback.user, chat_id)


@router.message_callback(F.callback.payload == kb.MENU_MY)
async def on_menu_my(event: MessageCallback) -> None:
    await event.answer()
    await _send_my_requests(event.message.answer, event.callback.user.user_id)


async def _send_my_requests(answer: Any, user_id: int) -> None:
    rows = await repo.list_requests(author_user_id=user_id, limit=20)
    await answer(
        text=texts.my_requests([repo.to_dict(row) for row in rows]),
        attachments=kb.main_menu_kb(),
    )

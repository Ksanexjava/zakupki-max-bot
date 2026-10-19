"""Пошаговое заполнение заявки на закупку."""

import logging
from typing import Any, Awaitable, Callable

from maxapi import F
from maxapi.context.base import BaseContext
from maxapi.dispatcher import Router
from maxapi.enums.format import Format
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from bot import keyboards as kb
from bot import media
from bot import texts
from bot.states import RequestForm
from core.notifications import notify_admins
from core.statuses import label
from db import repo

log = logging.getLogger(__name__)
router = Router(router_id="request")

#: ограничения длины ответов, чтобы в базу не уезжали «простыни»
LIMITS = {
    "requester": 300,
    "item": 500,
    "quantity": 200,
    "deadline": 200,
    "purpose": 1000,
    "example_url": 500,
}

Answer = Callable[..., Awaitable[Any]]


def _text(event: MessageCreated) -> str:
    body = event.message.body
    return (body.text or "").strip() if body else ""


async def _take_text(event: MessageCreated, field: str) -> str | None:
    """Достаёт текст ответа и проверяет длину. None — значит спрашиваем ещё раз."""
    value = _text(event)
    if not value:
        await event.message.answer(texts.EMPTY_TEXT)
        return None
    return value[: LIMITS.get(field, 300)]


def display_name(user: Any) -> str:
    parts = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    name = " ".join(part for part in parts if part).strip()
    if name:
        return name
    username = getattr(user, "username", None)
    return f"@{username}" if username else "Коллега"


# --------------------------------------------------------------- шаг 1: кто

async def start_form(answer: Answer, context: BaseContext, user: Any, chat_id: int | None = None) -> None:
    """Начать заполнение заявки с первого шага. answer — функция отправки сообщения."""
    await context.clear()
    name = display_name(user)
    await context.update_data(
        author_user_id=getattr(user, "user_id", None),
        author_name=name,
        author_username=getattr(user, "username", None),
        author_chat_id=chat_id,
    )
    await context.set_state(RequestForm.requester)
    await answer(text=texts.STEP_REQUESTER, attachments=kb.requester_kb(name), format=Format.MARKDOWN)


@router.message_created(RequestForm.requester, F.message.body.text)
async def step_requester(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "requester")
    if value is None:
        return
    await context.update_data(requester=value)
    await _ask_item(event.message.answer, context)


@router.message_callback(RequestForm.requester, F.callback.payload == kb.FORM_SELF)
async def step_requester_self(event: MessageCallback, context: BaseContext) -> None:
    """Кнопка «Это я» — подставляем имя из профиля MAX."""
    await event.answer()
    data = await context.get_data()
    await context.update_data(requester=data.get("author_name") or display_name(event.callback.user))
    await _ask_item(event.message.answer, context)


@router.message_callback(RequestForm.requester, F.callback.payload == kb.FORM_OTHER)
async def step_requester_other(event: MessageCallback, context: BaseContext) -> None:
    """Кнопка «Это не я» — просим вписать, для кого оформляется заказ."""
    await event.answer()
    await event.message.answer(
        text=texts.STEP_REQUESTER_OTHER,
        attachments=kb.cancel_kb(),
        format=Format.MARKDOWN,
    )
    # состояние не меняем: следующий текст попадёт в step_requester


# -------------------------------------------------------------- шаг 2: что

async def _ask_item(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.item)
    await answer(text=texts.STEP_ITEM, attachments=kb.cancel_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.item, F.message.body.text)
async def step_item(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "item")
    if value is None:
        return
    await context.update_data(item=value)
    await _ask_quantity(event.message.answer, context)


# ----------------------------------------------------------- шаг 3: сколько

async def _ask_quantity(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.quantity)
    await answer(text=texts.STEP_QUANTITY, attachments=kb.cancel_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.quantity, F.message.body.text)
async def step_quantity(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "quantity")
    if value is None:
        return
    await context.update_data(quantity=value)
    await _ask_deadline(event.message.answer, context)


# -------------------------------------------------------------- шаг 4: срок

async def _ask_deadline(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.deadline)
    await answer(text=texts.STEP_DEADLINE, attachments=kb.deadline_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.deadline, F.message.body.text)
async def step_deadline(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "deadline")
    if value is None:
        return
    await context.update_data(deadline=value)
    await _ask_purpose(event.message.answer, context)


@router.message_callback(RequestForm.deadline, F.callback.payload.startswith(kb.FORM_DEADLINE))
async def step_deadline_button(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    key = (event.callback.payload or "").rsplit(":", 1)[-1]
    await context.update_data(deadline=texts.DEADLINE_CHOICES.get(key, key))
    await _ask_purpose(event.message.answer, context)


# -------------------------------------------------------------- шаг 5: цель

async def _ask_purpose(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.purpose)
    await answer(text=texts.STEP_PURPOSE, attachments=kb.cancel_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.purpose, F.message.body.text)
async def step_purpose(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "purpose")
    if value is None:
        return
    await context.update_data(purpose=value)
    await _ask_example(event.message.answer, context)


# ------------------------------------------------------------ шаг 6: пример

async def _ask_example(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.example)
    await answer(text=texts.STEP_EXAMPLE, attachments=kb.example_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.example, F.message.body.attachments)
async def step_example_photo(event: MessageCreated, context: BaseContext) -> None:
    """Прислали фото товара — сохраняем токен и файл для панели."""
    body = event.message.body
    photo = media.find_photo(body.attachments if body else None)
    if photo is None or photo.payload is None:
        await event.message.answer(text=texts.STEP_EXAMPLE, attachments=kb.example_kb())
        return
    filename = await media.save_photo(event.bot, getattr(photo.payload, "url", None))
    await context.update_data(
        photo_token=getattr(photo.payload, "token", None),
        photo_file=filename,
    )
    caption = (body.text or "").strip() if body else ""
    if caption:
        await context.update_data(example_url=caption[: LIMITS["example_url"]])
    await _show_preview(event.message.answer, context)


@router.message_created(RequestForm.example, F.message.body.text)
async def step_example_text(event: MessageCreated, context: BaseContext) -> None:
    value = _text(event)
    if value.lower() in {"-", "нет", "пропустить", "skip"}:
        value = ""
    await context.update_data(example_url=value[: LIMITS["example_url"]] or None)
    await _show_preview(event.message.answer, context)


@router.message_callback(RequestForm.example, F.callback.payload == kb.FORM_SKIP)
async def step_example_skip(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.update_data(example_url=None)
    await _show_preview(event.message.answer, context)


# --------------------------------------------------------- проверка и отправка

async def _show_preview(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.confirm)
    draft = await context.get_data()
    card = texts.render_request({**draft, "id": None}, with_status=False)
    await answer(text=f"{texts.ASK_CONFIRM}\n\n{card}", attachments=kb.confirm_kb())


@router.message_callback(RequestForm.confirm, F.callback.payload == kb.FORM_RESTART)
async def form_restart(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await event.message.answer(texts.RESTARTED)
    await start_form(event.message.answer, context, event.callback.user)


@router.message_callback(F.callback.payload == kb.FORM_CANCEL)
async def form_cancel(event: MessageCallback, context: BaseContext) -> None:
    await event.answer(notification="Отменено")
    await context.clear()
    await event.message.answer(text=texts.CANCELLED, attachments=kb.main_menu_kb())


@router.message_callback(RequestForm.confirm, F.callback.payload == kb.FORM_SUBMIT)
async def form_submit(event: MessageCallback, context: BaseContext) -> None:
    """Сохраняем заявку и уведомляем закупки."""
    await event.answer(notification="Заявка отправлена")
    draft = await context.get_data()
    await context.clear()

    request = await repo.create_request(draft)
    data = repo.to_dict(request)
    log.info("Создана заявка №%s от user_id=%s", request.id, request.author_user_id)

    await event.message.answer(
        text=texts.SUBMITTED.format(id=request.id, status=label(request.status)),
        attachments=kb.main_menu_kb(),
    )
    await notify_admins(event.bot, data)

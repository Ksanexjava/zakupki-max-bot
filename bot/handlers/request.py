"""Заполнение заявки: одна позиция, несколько по очереди или списком."""

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
from core.parsing import parse_items
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
    "link": 500,
    "list": 4000,
}
MAX_ITEMS = 30

Answer = Callable[..., Awaitable[Any]]


# ----------------------------------------------------------- вспомогательное

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


async def _items(context: BaseContext) -> list[dict[str, Any]]:
    data = await context.get_data()
    return list(data.get("items") or [])


async def _is_single(context: BaseContext) -> bool:
    data = await context.get_data()
    return (data.get("mode") or "one") == "one"


# --------------------------------------------------------- шаг 1: кто заказывает

async def start_form(answer: Answer, context: BaseContext, user: Any, chat_id: int | None = None) -> None:
    """Начать заполнение заявки с первого шага. answer — функция отправки сообщения."""
    await context.clear()
    name = display_name(user)
    await context.update_data(
        author_user_id=getattr(user, "user_id", None),
        author_name=name,
        author_username=getattr(user, "username", None),
        author_chat_id=chat_id,
        items=[],
        draft={},
        mode="one",
    )
    await context.set_state(RequestForm.requester)
    await answer(text=texts.STEP_REQUESTER, attachments=kb.requester_kb(name), format=Format.MARKDOWN)


@router.message_created(RequestForm.requester, F.message.body.text)
async def step_requester(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "requester")
    if value is None:
        return
    await context.update_data(requester=value)
    await _ask_mode(event.message.answer, context)


@router.message_callback(RequestForm.requester, F.callback.payload == kb.FORM_SELF)
async def step_requester_self(event: MessageCallback, context: BaseContext) -> None:
    """Кнопка «Это я» — подставляем имя из профиля MAX."""
    await event.answer()
    data = await context.get_data()
    await context.update_data(requester=data.get("author_name") or display_name(event.callback.user))
    await _ask_mode(event.message.answer, context)


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


# ------------------------------------------------- развилка: сколько позиций

async def _ask_mode(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.mode)
    await answer(text=texts.ASK_MODE, attachments=kb.mode_kb(), format=Format.MARKDOWN)


@router.message_callback(RequestForm.mode, F.callback.payload == kb.FORM_MODE_ONE)
async def mode_one(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.update_data(mode="one")
    await _ask_item(event.message.answer, context)


@router.message_callback(RequestForm.mode, F.callback.payload == kb.FORM_MODE_MANY)
async def mode_many(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.update_data(mode="many")
    await _ask_item(event.message.answer, context)


@router.message_callback(RequestForm.mode, F.callback.payload == kb.FORM_MODE_LIST)
async def mode_list(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.update_data(mode="list")
    await _ask_list(event.message.answer, context)


# --------------------------------------------------------- позиции по одной

async def _ask_item(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.item)
    if await _is_single(context):
        await answer(text=texts.STEP_ITEM, attachments=kb.cancel_kb(), format=Format.MARKDOWN)
        return
    number = len(await _items(context)) + 1
    await answer(text=texts.pos_item(number), attachments=kb.cancel_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.item, F.message.body.text)
async def step_item(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "item")
    if value is None:
        return
    await context.update_data(draft={"name": value})
    await _ask_quantity(event.message.answer, context)


async def _ask_quantity(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.quantity)
    if await _is_single(context):
        await answer(text=texts.STEP_QUANTITY, attachments=kb.cancel_kb(), format=Format.MARKDOWN)
        return
    data = await context.get_data()
    number = len(data.get("items") or []) + 1
    name = (data.get("draft") or {}).get("name", "")
    await answer(text=texts.pos_quantity(number, name), attachments=kb.cancel_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.quantity, F.message.body.text)
async def step_quantity(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "quantity")
    if value is None:
        return
    data = await context.get_data()
    draft = dict(data.get("draft") or {})
    draft["quantity"] = value
    await context.update_data(draft=draft)
    await _ask_example(event.message.answer, context)


async def _ask_example(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.example)
    if await _is_single(context):
        await answer(text=texts.STEP_EXAMPLE, attachments=kb.example_kb(), format=Format.MARKDOWN)
        return
    number = len(await _items(context)) + 1
    await answer(text=texts.pos_example(number), attachments=kb.example_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.example, F.message.body.attachments)
async def step_example_photo(event: MessageCreated, context: BaseContext) -> None:
    """Прислали фото товара — сохраняем токен и файл для панели."""
    body = event.message.body
    photo = media.find_photo(body.attachments if body else None)
    if photo is None or photo.payload is None:
        await _ask_example(event.message.answer, context)
        return
    data = await context.get_data()
    draft = dict(data.get("draft") or {})
    draft["photo_token"] = getattr(photo.payload, "token", None)
    draft["photo_file"] = await media.save_photo(event.bot, getattr(photo.payload, "url", None))
    caption = (body.text or "").strip() if body else ""
    if caption:
        draft["link"] = caption[: LIMITS["link"]]
    await context.update_data(draft=draft)
    await _finish_position(event.message.answer, context)


@router.message_created(RequestForm.example, F.message.body.text)
async def step_example_text(event: MessageCreated, context: BaseContext) -> None:
    value = _text(event)
    if value.lower() in {"-", "нет", "пропустить", "skip"}:
        value = ""
    data = await context.get_data()
    draft = dict(data.get("draft") or {})
    draft["link"] = value[: LIMITS["link"]] or None
    await context.update_data(draft=draft)
    await _finish_position(event.message.answer, context)


@router.message_callback(RequestForm.example, F.callback.payload == kb.FORM_SKIP)
async def step_example_skip(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await _finish_position(event.message.answer, context)


async def _finish_position(answer: Answer, context: BaseContext) -> None:
    """Складывает заполненную позицию в список и решает, что дальше."""
    data = await context.get_data()
    items = list(data.get("items") or [])
    draft = dict(data.get("draft") or {})
    if draft.get("name"):
        items.append(draft)
    await context.update_data(items=items, draft={})

    if (data.get("mode") or "one") == "one":
        await _ask_deadline(answer, context)
        return
    if len(items) >= MAX_ITEMS:
        await answer(text=f"В одной заявке не больше {MAX_ITEMS} позиций. Перехожу к сроку.")
        await _ask_deadline(answer, context)
        return
    await _ask_more(answer, context, len(items))


async def _ask_more(answer: Answer, context: BaseContext, count: int) -> None:
    await context.set_state(RequestForm.more)
    await answer(text=texts.ask_more(count), attachments=kb.more_kb())


@router.message_callback(RequestForm.more, F.callback.payload == kb.FORM_MORE)
async def more_add(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await _ask_item(event.message.answer, context)


@router.message_callback(RequestForm.more, F.callback.payload == kb.FORM_DONE)
async def more_done(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await _ask_deadline(event.message.answer, context)


# ------------------------------------------------------------ список разом

async def _ask_list(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.bulk_list)
    await answer(text=texts.ASK_LIST, attachments=kb.cancel_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.bulk_list, F.message.body.text)
async def step_bulk_list(event: MessageCreated, context: BaseContext) -> None:
    raw = _text(event)[: LIMITS["list"]]
    items = parse_items(raw)[:MAX_ITEMS]
    if not items:
        await event.message.answer(text=texts.LIST_EMPTY, attachments=kb.cancel_kb())
        return
    await context.update_data(items=items)
    await event.message.answer(text=texts.list_parsed(items), attachments=kb.list_confirm_kb())


@router.message_callback(RequestForm.bulk_list, F.callback.payload == kb.FORM_LIST_REDO)
async def bulk_redo(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await context.update_data(items=[])
    await _ask_list(event.message.answer, context)


@router.message_callback(RequestForm.bulk_list, F.callback.payload == kb.FORM_LIST_OK)
async def bulk_ok(event: MessageCallback, context: BaseContext) -> None:
    await event.answer()
    await _ask_missing_quantity(event.message.answer, context)


async def _ask_missing_quantity(answer: Answer, context: BaseContext) -> None:
    """Спрашивает количества для позиций, где их не удалось разобрать."""
    items = await _items(context)
    for index, item in enumerate(items):
        if not (item.get("quantity") or "").strip():
            await context.update_data(fix_index=index)
            await context.set_state(RequestForm.fix_quantity)
            await answer(
                text=texts.ask_missing_quantity(index + 1, len(items), item.get("name", "")),
                attachments=kb.cancel_kb(),
                format=Format.MARKDOWN,
            )
            return
    await _ask_deadline(answer, context)


@router.message_created(RequestForm.fix_quantity, F.message.body.text)
async def step_fix_quantity(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "quantity")
    if value is None:
        return
    data = await context.get_data()
    items = list(data.get("items") or [])
    index = int(data.get("fix_index") or 0)
    if 0 <= index < len(items):
        items[index] = {**items[index], "quantity": value}
        await context.update_data(items=items)
    await _ask_missing_quantity(event.message.answer, context)


# --------------------------------------------------- общие поля заявки

async def _ask_deadline(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.deadline)
    text = texts.STEP_DEADLINE if await _is_single(context) else texts.STEP_DEADLINE_PLAIN
    await answer(text=text, attachments=kb.deadline_kb(), format=Format.MARKDOWN)


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


async def _ask_purpose(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.purpose)
    text = texts.STEP_PURPOSE if await _is_single(context) else texts.STEP_PURPOSE_PLAIN
    await answer(text=text, attachments=kb.cancel_kb(), format=Format.MARKDOWN)


@router.message_created(RequestForm.purpose, F.message.body.text)
async def step_purpose(event: MessageCreated, context: BaseContext) -> None:
    value = await _take_text(event, "purpose")
    if value is None:
        return
    await context.update_data(purpose=value)
    await _show_preview(event.message.answer, context)


# --------------------------------------------------- проверка и отправка

async def _show_preview(answer: Answer, context: BaseContext) -> None:
    await context.set_state(RequestForm.confirm)
    draft = await context.get_data()
    items = list(draft.get("items") or [])
    card = texts.render_request(
        {**draft, "id": None, "items": items, "items_count": len(items)},
        with_status=False,
    )
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
    log.info(
        "Создана заявка №%s от user_id=%s, позиций: %s",
        request.id, request.author_user_id, data["items_count"],
    )

    await event.message.answer(
        text=texts.SUBMITTED.format(id=request.id, status=label(request.status)),
        attachments=kb.main_menu_kb(),
    )
    await notify_admins(event.bot, data)

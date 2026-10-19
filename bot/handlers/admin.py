"""Админские команды и быстрая смена статуса кнопками под уведомлением."""

import logging
import secrets

from maxapi import F
from maxapi.dispatcher import Router
from maxapi.filters.command import Command
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

from bot import keyboards as kb
from bot import texts
from bot.handlers.request import display_name
from config import settings
from core import statuses
from core.notifications import notify_author, panel_link
from db import repo

log = logging.getLogger(__name__)
router = Router(router_id="admin")


@router.message_created(Command("admin"))
async def on_admin(event: MessageCreated) -> None:
    """«/admin <код>» — подписаться на уведомления о новых заявках."""
    if not settings.admin_code:
        await event.message.answer(texts.ADMIN_NO_CODE)
        return
    body = event.message.body
    parts = ((body.text or "") if body else "").split(maxsplit=1)
    argument = parts[1].strip() if len(parts) > 1 else ""
    # сравниваем байты: compare_digest не принимает строки с не-ASCII символами
    if not secrets.compare_digest(argument.encode(), settings.admin_code.encode()):
        log.warning("Неверный код администратора от user_id=%s", event.message.sender.user_id)
        await event.message.answer(texts.ADMIN_BAD_CODE)
        return
    added = await repo.add_admin(event.message.sender.user_id, display_name(event.message.sender))
    await event.message.answer(texts.ADMIN_LINKED if added else texts.ADMIN_ALREADY)


@router.message_created(Command("unadmin"))
async def on_unadmin(event: MessageCreated) -> None:
    await repo.remove_admin(event.message.sender.user_id)
    await event.message.answer(texts.ADMIN_UNLINKED)


@router.message_created(Command("id"))
async def on_id(event: MessageCreated) -> None:
    await event.message.answer(f"Ваш user_id: {event.message.sender.user_id}")


@router.message_callback(F.callback.payload.startswith(f"{kb.ADMIN_STATUS}:"))
async def on_status_button(event: MessageCallback) -> None:
    """Кнопки «В работе / На уточнении / Заказано» под уведомлением о заявке."""
    _, _, rest = (event.callback.payload or "").partition(":")
    raw_id, _, status = rest.partition(":")
    if not raw_id.isdigit() or not statuses.is_valid(status):
        await event.answer(notification=texts.STALE_BUTTON)
        return

    user_id = event.callback.user.user_id
    if not await repo.is_admin(user_id, settings.admin_user_ids):
        await event.answer(notification=texts.ADMIN_NO_RIGHTS)
        return

    result = await repo.set_status(int(raw_id), status, actor=f"MAX:{user_id}")
    if result is None:
        await event.answer(notification=texts.REQUEST_NOT_FOUND)
        return

    request, previous = result
    data = repo.to_dict(request)
    await event.edit(
        text=texts.admin_notification(data, panel_link(request.id)),
        attachments=kb.admin_request_kb(request.id, request.status, panel_link(request.id)),
        notification=f"Статус: {statuses.STATUSES[status]['label']}",
    )
    delivered, reason = await notify_author(event.bot, data, previous)
    if not delivered and reason:
        log.warning("Автор заявки №%s не получил уведомление: %s", request.id, reason)

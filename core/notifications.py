"""Уведомления: администраторам о новых заявках, авторам — о смене статуса.

Вызывается и из бота, и из веб-панели, поэтому живёт отдельно от handlers.
"""

import logging
from typing import Any, Mapping

from bot import keyboards as kb
from bot import texts
from config import settings
from db import repo

log = logging.getLogger(__name__)


def panel_link(request_id: int | None = None) -> str:
    """Ссылка на панель (на конкретную заявку, если указан номер)."""
    if not settings.panel_public_url:
        return ""
    return f"{settings.panel_public_url}/#{request_id}" if request_id else settings.panel_public_url


async def recipients() -> list[int]:
    """user_id всех, кому шлём уведомления о новых заявках."""
    stored = await repo.admin_ids()
    return list(dict.fromkeys([*settings.admin_user_ids, *stored]))


async def notify_admins(bot: Any, request: Mapping[str, Any]) -> int:
    """Рассылает карточку новой заявки. Возвращает число доставленных сообщений."""
    targets = await recipients()
    if not targets:
        log.warning(
            "Заявка №%s создана, но получателей уведомлений нет. "
            "Напишите боту «/admin <ADMIN_CODE>» или заполните ADMIN_USER_IDS.",
            request.get("id"),
        )
        return 0

    text = texts.admin_notification(request, panel_link(request["id"]))
    keyboard = kb.admin_request_kb(request["id"], request["status"], panel_link(request["id"]))
    delivered = 0
    for user_id in targets:
        try:
            await bot.send_message(user_id=user_id, text=text, attachments=keyboard)
            delivered += 1
        except Exception as exc:  # noqa: BLE001 — недоступный админ не ломает заявку
            log.warning("Не доставлено админу %s: %s", user_id, exc)
    return delivered


async def _send_to_author(
    bot: Any,
    request: Mapping[str, Any],
    text: str,
) -> tuple[bool, str | None]:
    """Отправляет автору сообщение. Возвращает (успех, причина неудачи).

    Причину возвращаем наверх, чтобы она была видна в панели, а не только в логе.
    """
    if not settings.notify_author:
        return False, "уведомления автору выключены (NOTIFY_AUTHOR=false)"
    author_id = request.get("author_user_id")
    if not author_id:
        return False, "у заявки не сохранён автор"
    if bot is None:
        return False, "бот не запущен"

    request_id = request.get("id")
    errors: list[str] = []

    # Сначала пробуем по user_id, затем по chat_id диалога: разные версии
    # MAX API ведут себя по-разному, а потерять уведомление нельзя.
    targets: list[tuple[str, int]] = [("user_id", int(author_id))]
    chat_id = request.get("author_chat_id")
    if chat_id:
        targets.append(("chat_id", int(chat_id)))

    for field, value in targets:
        try:
            await bot.send_message(**{field: value}, text=text)
        except Exception as exc:  # noqa: BLE001 — панель не должна падать из-за мессенджера
            reason = f"{field}={value} → {type(exc).__name__}: {exc}"
            log.warning("Заявка №%s: уведомление не ушло (%s)", request_id, reason)
            errors.append(reason)
            continue
        log.info("Заявка №%s: уведомление автору отправлено (%s=%s)", request_id, field, value)
        return True, None

    return False, "; ".join(errors) or "не удалось отправить"


async def notify_author(
    bot: Any,
    request: Mapping[str, Any],
    previous_status: str,
    comment: str | None = None,
) -> tuple[bool, str | None]:
    """Пишет автору заявки о новом статусе."""
    if previous_status == request.get("status") and not comment:
        return False, None  # статус не изменился и сказать нечего
    text = texts.author_status_changed(request, previous_status, request["status"], comment)
    return await _send_to_author(bot, request, text)


async def notify_author_comment(
    bot: Any, request: Mapping[str, Any], comment: str
) -> tuple[bool, str | None]:
    """Шлёт автору комментарий закупок, когда статус не менялся."""
    if not comment:
        return False, "пустой комментарий"
    return await _send_to_author(bot, request, texts.author_comment(request, comment))


async def notify_author_deleted(
    bot: Any, request: Mapping[str, Any]
) -> tuple[bool, str | None]:
    """Сообщает автору, что заявку удалили."""
    return await _send_to_author(bot, request, texts.author_request_deleted(request))

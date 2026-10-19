"""Все тексты бота в одном месте — удобно править формулировки."""

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from config import settings
from core.statuses import label

DISPLAY_TZ = timezone(timedelta(hours=settings.tz_offset))

WELCOME = (
    "Привет, {name}! 👋\n\n"
    "Через этого бота оформляются заявки на закупку.\n"
    "Ответьте на несколько вопросов — заявка уйдёт на согласование, "
    "а о смене статуса я напишу вам сюда же.\n\n"
    "Нажмите «Создать заявку», чтобы начать."
)

MAIN_MENU = "Чем займёмся?"

HELP = (
    "Что я умею:\n\n"
    "📝 /new — создать заявку на закупку\n"
    "📋 /my — мои заявки и их статусы\n"
    "❌ /cancel — отменить заполнение\n"
    "ℹ️ /help — это сообщение\n\n"
    "В заявке пять обязательных вопросов (кто заказывает, что, сколько, "
    "к какому сроку, зачем) и один необязательный — пример товара: ссылка или фото."
)

STEP_REQUESTER = (
    "👤 Шаг 1 из 6. **Кто заказывает?**\n\n"
    "Если заявка для вас — нажмите «Это я».\n"
    "Если оформляете для другого сотрудника — «Это не я»."
)
STEP_REQUESTER_OTHER = (
    "✍️ Впишите ФИО того, для кого осуществляется заказ.\n\n"
    "Лучше с отделом — например: «Иванова Мария, бухгалтерия»."
)
STEP_ITEM = (
    "📦 Шаг 2 из 6. **Что нужно заказать?**\n\n"
    "Название товара как можно точнее — например: «Чайник электрический Bosch, 1.7 л»."
)
STEP_QUANTITY = (
    "🔢 Шаг 3 из 6. **Сколько нужно?**\n\n"
    "Например: «1 шт», «5 упаковок», «2 коробки по 10 шт»."
)
STEP_DEADLINE = (
    "📅 Шаг 4 из 6. **К какому сроку нужно?**\n\n"
    "Выберите вариант кнопкой или напишите дату своими словами."
)
STEP_PURPOSE = (
    "🎯 Шаг 5 из 6. **Зачем это нужно?**\n\n"
    "Коротко: для чего и кому — например «для кухни в офисе, старый сломался». "
    "Это главный пункт: по нему решают, нужна ли закупка."
)
STEP_EXAMPLE = (
    "🔗 Шаг 6 из 6. **Пример товара** (необязательно)\n\n"
    "Пришлите ссылку (Ozon, Wildberries, сайт поставщика) или фото.\n"
    "Если примера нет — нажмите «Пропустить»."
)

DEADLINE_CHOICES: dict[str, str] = {
    "urgent": "Срочно, сегодня-завтра",
    "week": "В течение недели",
    "month": "В течение месяца",
    "any": "Не срочно",
}

ASK_CONFIRM = "Проверьте заявку перед отправкой 👇"
SUBMITTED = (
    "✅ Заявка №{id} отправлена!\n\n"
    "Статус: {status}. Как только его изменят, я вам напишу.\n"
    "Посмотреть свои заявки: /my"
)
CANCELLED = "Заполнение отменено. Начать заново: /new"
RESTARTED = "Хорошо, начнём заново."
NOTHING_TO_CANCEL = "Сейчас нечего отменять. Создать заявку: /new"
EMPTY_TEXT = "Нужен текст — напишите ответ сообщением 🙏"
USE_BUTTONS = "Выберите вариант кнопкой выше 👆"
NO_REQUESTS = "У вас пока нет заявок. Создать: /new"
UNKNOWN = "Не понял 🤔 Создать заявку — /new, список команд — /help."
STALE_BUTTON = "Эта кнопка уже неактуальна. Напишите /start"

ADMIN_LINKED = "✅ Готово, теперь вы получаете уведомления о новых заявках."
ADMIN_ALREADY = "Вы и так получаете уведомления о новых заявках."
ADMIN_BAD_CODE = "Неверный код."
ADMIN_UNLINKED = "Больше не присылаю вам уведомления о новых заявках."
ADMIN_NO_CODE = "Команда недоступна: ADMIN_CODE не настроен в .env."
ADMIN_NO_RIGHTS = "Нет прав на смену статуса"
REQUEST_NOT_FOUND = "Заявка не найдена"


def fmt_dt(value: datetime | str | None) -> str:
    """Дата/время в часовом поясе из DISPLAY_TZ_OFFSET: «19.10.2026 14:05»."""
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(DISPLAY_TZ).strftime("%d.%m.%Y %H:%M")


def render_request(
    data: Mapping[str, Any],
    *,
    with_status: bool = True,
    with_author: bool = False,
) -> str:
    """Карточка заявки текстом — и в боте, и в уведомлении администратору."""
    lines: list[str] = [f"Заявка №{data['id']}" if data.get("id") else "Заявка"]
    if with_status and data.get("status"):
        lines.append(f"Статус: {label(data['status'])}")
    lines += [
        "",
        f"👤 Кто заказывает: {data.get('requester') or '—'}",
        f"📦 Что: {data.get('item') or '—'}",
        f"🔢 Сколько: {data.get('quantity') or '—'}",
        f"📅 К сроку: {data.get('deadline') or '—'}",
        f"🎯 Зачем: {data.get('purpose') or '—'}",
    ]
    if data.get("example_url"):
        lines.append(f"🔗 Пример: {data['example_url']}")
    elif data.get("photo_token") or data.get("photo_file"):
        lines.append("🖼 Пример: фото приложено")
    else:
        lines.append("🔗 Пример: не приложен")
    if with_author:
        author = data.get("author_name") or "—"
        if data.get("author_username"):
            author += f" (@{data['author_username']})"
        lines += ["", f"Отправил: {author}", f"Создана: {fmt_dt(data.get('created_at'))}"]
    return "\n".join(lines)


def admin_notification(data: Mapping[str, Any], panel_url: str = "") -> str:
    text = "🔔 Новая заявка на закупку\n\n" + render_request(data, with_author=True)
    if panel_url:
        text += f"\n\nПанель: {panel_url}"
    return text


def author_status_changed(
    data: Mapping[str, Any],
    previous_status: str,
    new_status: str,
    comment: str | None = None,
) -> str:
    lines = [
        f"🔄 Статус заявки №{data['id']} изменён",
        "",
        f"📦 {data.get('item') or '—'}",
        f"Было: {label(previous_status)}",
        f"Стало: {label(new_status)}",
    ]
    if comment:
        lines += ["", f"💬 Комментарий: {comment}"]
    if new_status == "clarify":
        lines += ["", "Ответьте на это сообщение или свяжитесь с закупками, чтобы уточнить детали."]
    return "\n".join(lines)


def author_comment(data: Mapping[str, Any], comment: str) -> str:
    """Комментарий закупок без смены статуса."""
    return "\n".join(
        [
            f"💬 Комментарий к заявке №{data['id']}",
            "",
            f"📦 {data.get('item') or '—'}",
            f"Статус: {label(data.get('status', ''))}",
            "",
            comment,
        ]
    )


def author_request_deleted(data: Mapping[str, Any]) -> str:
    """Заявку удалили из панели."""
    lines = [
        f"🗑 Заявка №{data['id']} удалена",
        "",
        f"📦 {data.get('item') or '—'}",
    ]
    if data.get("admin_comment"):
        lines += ["", f"💬 Причина: {data['admin_comment']}"]
    lines += ["", "Если это ошибка — оформите заявку заново: /new"]
    return "\n".join(lines)


def my_requests(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return NO_REQUESTS
    lines = ["📋 Ваши заявки:", ""]
    for row in rows:
        lines.append(f"№{row['id']} — {row['item']}")
        lines.append(f"   {label(row['status'])} · от {fmt_dt(row['created_at'])}")
        if row.get("admin_comment"):
            lines.append(f"   💬 {row['admin_comment']}")
        lines.append("")
    return "\n".join(lines).strip()

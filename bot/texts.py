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

ASK_MODE = (
    "🧾 **Сколько позиций в заявке?**\n\n"
    "Если нужен один товар — «Одна позиция».\n"
    "Если список — можно добавлять по очереди или вставить всё сразу."
)

STEP_ITEM = (
    "📦 Шаг 2 из 6. **Что нужно заказать?**\n\n"
    "Название товара как можно точнее — например: «Чайник электрический Bosch, 1.7 л»."
)
STEP_QUANTITY = (
    "🔢 Шаг 3 из 6. **Сколько нужно?**\n\n"
    "Например: «1 шт», «5 упаковок», «2 коробки по 10 шт»."
)
STEP_EXAMPLE = (
    "🔗 Шаг 4 из 6. **Пример товара** (необязательно)\n\n"
    "Пришлите ссылку (Ozon, Wildberries, сайт поставщика) или фото.\n"
    "Если примера нет — нажмите «Пропустить»."
)
STEP_DEADLINE = (
    "📅 Шаг 5 из 6. **К какому сроку нужно?**\n\n"
    "Выберите вариант кнопкой или напишите дату своими словами."
)
STEP_PURPOSE = (
    "🎯 Шаг 6 из 6. **Зачем это нужно?**\n\n"
    "Коротко: для чего и кому — например «для кухни в офисе, старый сломался». "
    "Это главный пункт: по нему решают, нужна ли закупка."
)

#: те же вопросы без нумерации — для заявок со списком позиций,
#: где человек не проходил шаги 2-4 по порядку
STEP_DEADLINE_PLAIN = STEP_DEADLINE.replace("📅 Шаг 5 из 6. ", "📅 ")
STEP_PURPOSE_PLAIN = STEP_PURPOSE.replace("🎯 Шаг 6 из 6. ", "🎯 ")

# --- вопросы по каждой позиции, когда их несколько ---

def pos_item(number: int) -> str:
    return (
        f"📦 **Позиция {number}. Что нужно заказать?**\n\n"
        "Название товара как можно точнее."
    )


def pos_quantity(number: int, name: str) -> str:
    return f"🔢 **Позиция {number}. Сколько нужно?**\n\n«{name}»"


def pos_example(number: int) -> str:
    return (
        f"🔗 **Позиция {number}. Ссылка или фото** (необязательно)\n\n"
        "Если примера нет — нажмите «Пропустить»."
    )


def ask_more(count: int) -> str:
    return (
        f"✅ Позиций в заявке: {count}.\n\n"
        "Добавить ещё одну или перейти к сроку и цели?"
    )


ASK_LIST = (
    "📋 **Пришлите список одним сообщением**\n\n"
    "Каждая позиция с новой строки. Ссылку можно вставлять прямо в строку, "
    "количество — в конце, например:\n\n"
    "`Гель для стирки — 10 шт https://ozon.ru/...`\n"
    "`Перчатки х/б, размер 10 — 20 пар`\n"
    "`Чайник Bosch 1.7 л`\n\n"
    "Если количество не укажете, я спрошу отдельно."
)
LIST_EMPTY = (
    "Не получилось разобрать список 🤔\n"
    "Пришлите позиции текстом, каждую с новой строки."
)


def list_parsed(items: list) -> str:
    lines = [f"Я понял так — позиций: {len(items)}", ""]
    lines += render_items(items)
    lines += ["", "Всё верно?"]
    return "\n".join(lines)


def ask_missing_quantity(number: int, total: int, name: str) -> str:
    return (
        f"🔢 Остались количества. **Позиция {number} из {total}:**\n\n"
        f"«{name}» — сколько нужно?"
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


def render_items(items: list) -> list[str]:
    """Нумерованный список позиций для сообщений бота."""
    lines: list[str] = []
    for number, item in enumerate(items, start=1):
        quantity = (item.get("quantity") or "").strip()
        tail = f" — {quantity}" if quantity else ""
        mark = "☑️ " if item.get("bought") else ""
        lines.append(f"{number}. {mark}{item.get('name') or '—'}{tail}")
        if item.get("link"):
            lines.append(f"    🔗 {item['link']}")
        elif item.get("photo_token") or item.get("photo_file"):
            lines.append("    🖼 фото приложено")
    return lines


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
    lines += ["", f"👤 Кто заказывает: {data.get('requester') or '—'}"]

    items = list(data.get("items") or [])
    if len(items) > 1:
        lines += [
            f"📅 К сроку: {data.get('deadline') or '—'}",
            f"🎯 Зачем: {data.get('purpose') or '—'}",
            "",
            f"📦 Позиции ({len(items)}):",
        ]
        lines += render_items(items)
    else:
        single = items[0] if items else {}
        name = single.get("name") or data.get("item") or "—"
        quantity = single.get("quantity") or data.get("quantity") or "—"
        link = single.get("link") or data.get("example_url")
        has_photo = single.get("photo_token") or single.get("photo_file") or data.get("photo_token")
        lines += [
            f"📦 Что: {name}",
            f"🔢 Сколько: {quantity}",
            f"📅 К сроку: {data.get('deadline') or '—'}",
            f"🎯 Зачем: {data.get('purpose') or '—'}",
        ]
        if link:
            lines.append(f"🔗 Пример: {link}")
        elif has_photo:
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


def title(data: Mapping[str, Any]) -> str:
    """Заголовок заявки: первая позиция и сколько ещё."""
    name = data.get("item") or "—"
    extra = (data.get("items_count") or 0) - 1
    return f"{name} и ещё {extra} поз." if extra > 0 else name


def author_status_changed(
    data: Mapping[str, Any],
    previous_status: str,
    new_status: str,
    comment: str | None = None,
) -> str:
    lines = [
        f"🔄 Статус заявки №{data['id']} изменён",
        "",
        f"📦 {title(data)}",
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


def author_bulk_status(items: list, new_status: str, comment: str | None = None) -> str:
    """Одно сообщение автору, когда статус поменяли сразу у нескольких его заявок."""
    lines = [
        f"🔄 Обновление по вашим заявкам ({len(items)})",
        "",
        f"Новый статус: {label(new_status)}",
        "",
    ]
    lines += [f"№{data['id']} — {title(data)}" for data in items]
    if comment:
        lines += ["", f"💬 Комментарий: {comment}"]
    if new_status == "clarify":
        lines += ["", "Ответьте на это сообщение или свяжитесь с закупками, чтобы уточнить детали."]
    return "\n".join(lines)


def my_requests(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return NO_REQUESTS
    lines = ["📋 Ваши заявки:", ""]
    for row in rows:
        extra = row.get("items_count") or 0
        suffix = f" и ещё {extra - 1} поз." if extra > 1 else ""
        lines.append(f"№{row['id']} — {row['item']}{suffix}")
        lines.append(f"   {label(row['status'])} · от {fmt_dt(row['created_at'])}")
        if row.get("admin_comment"):
            lines.append(f"   💬 {row['admin_comment']}")
        lines.append("")
    return "\n".join(lines).strip()

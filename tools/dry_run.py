"""Прогон диалога бота «на сухую»: без токена, без сети, во временной базе.

Запуск:  python -m tools.dry_run
"""

import asyncio
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="zakupki-dry-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/dry.db"
os.environ["MEDIA_DIR"] = f"{_TMP}/media"
os.environ["ADMIN_USER_IDS"] = "999"
os.environ["PANEL_PUBLIC_URL"] = "https://zakupki.example.ru"
os.environ["PANEL_ENABLED"] = "false"

from maxapi.context.context import MemoryContext  # noqa: E402

from bot.handlers import admin, request as form, start  # noqa: E402
from core.statuses import label  # noqa: E402
from db import repo  # noqa: E402
from db.session import init_db  # noqa: E402
from tools.fakes import (  # noqa: E402
    ADMIN,
    CHAT_ID,
    PHOTO_ATTACHMENT,
    USER,
    FakeBot,
    bot_started_event,
    callback_event,
    message_event,
)

LINE = "─" * 64


async def main() -> None:
    await init_db()
    bot = FakeBot(verbose=True)
    context = MemoryContext(CHAT_ID, USER["user_id"])

    script = [
        ("пользователь открыл бота", lambda: start.on_bot_started(bot_started_event(bot), context)),
        ("нажал «Создать заявку»", lambda: start.on_menu_new(callback_event(bot, "menu:new"), context)),
        ("нажал «Это я»", lambda: form.step_requester_self(callback_event(bot, "form:self"), context)),
        ("написал товар", lambda: form.step_item(message_event(bot, "Чайник электрический Bosch, 1.7 л"), context)),
        ("написал количество", lambda: form.step_quantity(message_event(bot, "1 шт"), context)),
        ("выбрал срок кнопкой", lambda: form.step_deadline_button(callback_event(bot, "form:deadline:week"), context)),
        ("написал цель", lambda: form.step_purpose(message_event(bot, "На кухню в бухгалтерии, старый сломался"), context)),
        ("прислал фото товара", lambda: form.step_example_photo(message_event(bot, None, [PHOTO_ATTACHMENT]), context)),
        ("подтвердил отправку", lambda: form.form_submit(callback_event(bot, "form:submit"), context)),
        ("шеф нажал «В работе»", lambda: admin.on_status_button(callback_event(bot, "adm:1:in_progress", ADMIN))),
        ("посмотрел свои заявки", lambda: start.on_my(message_event(bot, "/my"))),
    ]

    for title, step in script:
        print(f"\n{LINE}\n▶ {title}")
        await step()

    print(f"\n{LINE}\n")
    rows = await repo.list_requests()
    print(f"✅ Заявок в базе: {len(rows)}")
    for row in rows:
        print(f"   №{row.id} [{label(row.status)}] {row.item} — {row.quantity}, {row.deadline}")
        print(f"       цель: {row.purpose}")
        print(f"       фото: {row.photo_file} | ссылка: {row.example_url}")
    print("\n📜 История заявки №1:")
    for item in await repo.history(1):
        print(f"   {item.actor}: {item.from_status} → {item.to_status} {item.comment or ''}")
    print(f"\n(временная база: {_TMP})")


if __name__ == "__main__":
    asyncio.run(main())

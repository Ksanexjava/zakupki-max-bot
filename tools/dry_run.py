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
        ("выбрал «Вставлю списком»", lambda: form.mode_list(callback_event(bot, "form:mode:list"), context)),
        ("прислал список позиций", lambda: form.step_bulk_list(message_event(
            bot,
            "Гель для стирки Ariel — 10 шт https://ozon.ru/t/gel\n"
            "Пемолюкс Лимон порошок 480г https://ozon.ru/t/pem\n"
            "Перчатки х/б с ПВХ-точкой, размер 10 — 20 пар",
        ), context)),
        ("подтвердил разбор", lambda: form.bulk_ok(callback_event(bot, "form:list:ok"), context)),
        ("дописал недостающее количество", lambda: form.step_fix_quantity(message_event(bot, "10 шт"), context)),
        ("выбрал срок кнопкой", lambda: form.step_deadline_button(callback_event(bot, "form:deadline:urgent"), context)),
        ("написал цель", lambda: form.step_purpose(message_event(bot, "Расходники для уборки в отделениях"), context)),
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
        print(f"   №{row.id} [{label(row.status)}] {row.deadline} · цель: {row.purpose}")
        for item in row.items:
            link = f" | {item.link}" if item.link else ""
            print(f"       {item.position}. {item.name} — {item.quantity}{link}")
    print("\n📜 История заявки №1:")
    for item in await repo.history(1):
        print(f"   {item.actor}: {item.from_status} → {item.to_status} {item.comment or ''}")
    print(f"\n(временная база: {_TMP})")


if __name__ == "__main__":
    asyncio.run(main())

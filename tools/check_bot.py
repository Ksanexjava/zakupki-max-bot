"""Диагностика связи с MAX: токен, адрес API, получатели, пробная отправка.

Запуск:
    python -m tools.check_bot              # проверить токен и показать, кому уходят уведомления
    python -m tools.check_bot 123456789    # плюс отправить тестовое сообщение этому user_id
    python -m tools.check_bot --author 1   # плюс отправить автору заявки №1

Важно: запускать там же, где работает бот — скрипту нужен доступ к max.ru.
"""

import asyncio
import sys
import traceback

from maxapi import Bot

from config import settings
from db import repo
from db.session import init_db

LINE = "─" * 64


def head(title: str) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}")


async def main(argv: list[str]) -> int:
    head("1. Настройки")
    if not settings.bot_token:
        print("❌ MAX_BOT_TOKEN не задан в .env — бот работать не будет")
        return 1
    print(f"✅ токен задан, длина {len(settings.bot_token)} символов")
    print(f"   адрес API: {settings.api_url or 'по умолчанию (platform-api2.max.ru)'}")
    print(f"   NOTIFY_AUTHOR: {settings.notify_author}")

    bot = Bot(token=settings.bot_token)
    if settings.api_url:
        bot.set_api_url(settings.api_url)

    head("2. Связь с MAX (GET /me)")
    try:
        me = await bot.get_me()
    except Exception as exc:  # noqa: BLE001 — показываем пользователю всё как есть
        print(f"❌ не удалось: {type(exc).__name__}: {exc}\n")
        traceback.print_exc()
        print(
            "\nЧто проверить:\n"
            "  • верный ли токен (перевыпустить: @MasterBot → /token);\n"
            "  • есть ли с этой машины доступ к max.ru;\n"
            "  • не нужен ли другой домен — задайте MAX_API_BASE в .env."
        )
        await bot.close_session()
        return 1
    print(f"✅ бот: {me.first_name or me.name} (@{me.username}, user_id={me.user_id})")

    head("3. Кому уходят уведомления о новых заявках")
    await init_db()
    admins = await repo.admin_ids()
    print(f"   из базы (команда /admin): {admins or 'никого'}")
    print(f"   из .env ADMIN_USER_IDS:   {list(settings.admin_user_ids) or 'никого'}")
    if not admins and not settings.admin_user_ids:
        print("⚠️  Получателей нет — напишите боту в MAX: /admin <ADMIN_CODE>")

    head("4. Авторы существующих заявок")
    requests = await repo.list_requests(limit=10)
    if not requests:
        print("   заявок пока нет")
    for row in requests:
        print(f"   №{row.id}: {row.author_name} (user_id={row.author_user_id}) — {row.item[:40]}")

    target: int | None = None
    if "--author" in argv:
        index = argv.index("--author")
        if index + 1 < len(argv) and argv[index + 1].isdigit():
            found = await repo.get_request(int(argv[index + 1]))
            if found is None:
                print(f"\n❌ заявки №{argv[index + 1]} нет")
                await bot.close_session()
                return 1
            target = found.author_user_id
    else:
        digits = [arg for arg in argv if arg.lstrip("-").isdigit()]
        if digits:
            target = int(digits[0])

    if target is None:
        head("5. Пробная отправка")
        print("   пропущена — запустите с user_id, например:")
        if admins:
            print(f"   python -m tools.check_bot {admins[0]}")
        else:
            print("   python -m tools.check_bot ВАШ_USER_ID   (узнать: команда /id боту)")
        await bot.close_session()
        return 0

    head(f"5. Пробная отправка сообщения user_id={target}")
    try:
        await bot.send_message(
            user_id=target,
            text="🔧 Проверка связи. Если вы это видите — уведомления из панели работают.",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"❌ не отправилось: {type(exc).__name__}: {exc}\n")
        traceback.print_exc()
        print(
            "\nЧастые причины:\n"
            "  • этот пользователь ни разу не открывал бота (нет диалога);\n"
            "  • user_id не тот — проверьте командой /id в самом боте;\n"
            "  • бот заблокирован пользователем."
        )
        await bot.close_session()
        return 1
    print("✅ отправлено — проверьте чат с ботом в MAX")
    await bot.close_session()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))

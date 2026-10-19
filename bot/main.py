"""Точка входа: long polling MAX + веб-панель заявок в одном процессе."""

import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.context.context import MemoryContext

from bot.handlers import routers
from config import settings
from db.session import init_db
from panel.server import start_panel

log = logging.getLogger("bot")

RETRY_MIN_DELAY = 5
RETRY_MAX_DELAY = 300


def build_dispatcher() -> Dispatcher:
    """Где хранить шаги заявки: Redis (переживает перезапуск) или память."""
    if settings.redis_url:
        from maxapi.context.context import RedisContext
        from redis.asyncio import Redis

        dp = Dispatcher(storage=RedisContext, redis_client=Redis.from_url(settings.redis_url))
        log.info("Шаги заявок хранятся в Redis")
    else:
        dp = Dispatcher(storage=MemoryContext)
        log.info("REDIS_URL не задан — шаги заявок хранятся в памяти")
    dp.include_routers(*routers)
    return dp


def _check_panel_config() -> None:
    if not settings.panel_enabled:
        return
    if not settings.panel_users:
        log.warning(
            'PANEL_USERS не задан — войти в панель будет нельзя. '
            'Добавьте в .env строку вида PANEL_USERS="mike:пароль".'
        )
    if settings.secret_key_generated:
        log.warning(
            "SECRET_KEY не задан — сгенерирован временный ключ, после перезапуска "
            "придётся войти в панель заново."
        )


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    if not settings.bot_token and not settings.panel_enabled:
        raise SystemExit("Не задан MAX_BOT_TOKEN. Скопируйте .env.example в .env и впишите токен.")

    await init_db()
    _check_panel_config()

    bot = Bot(token=settings.bot_token) if settings.bot_token else None
    if bot and settings.api_url:
        bot.set_api_url(settings.api_url)
        log.info("Адрес MAX API переопределён: %s", settings.api_url)

    panel = await start_panel(bot) if settings.panel_enabled else None

    try:
        if bot is None:
            log.warning("MAX_BOT_TOKEN не задан — работает только панель")
            await asyncio.Event().wait()
            return

        dp = build_dispatcher()
        await _log_recipients()
        log.info("Бот запущен, жду сообщения…")
        await _polling_with_retries(dp, bot)
    finally:
        if panel is not None:
            await panel.cleanup()
        if bot is not None:
            await bot.close_session()


async def _polling_with_retries(dp: Dispatcher, bot: Bot) -> None:
    """Держит бота живым при обрывах связи с MAX.

    Библиотека после нескольких неудачных попыток бросает исключение; без этой
    обёртки вместе с ботом падала бы и панель, которая от MAX не зависит.
    """
    delay = RETRY_MIN_DELAY
    while True:
        try:
            await dp.start_polling(bot)
            return  # штатная остановка
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — сеть может отвалиться по-разному
            log.error("Связь с MAX потеряна (%s). Повтор через %s с.", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_DELAY)


async def _log_recipients() -> None:
    from core.notifications import recipients

    targets = await recipients()
    if targets:
        log.info("Уведомления о заявках получают: %s", ", ".join(map(str, targets)))
    elif settings.admin_code:
        log.warning("Получателей уведомлений нет. Напишите боту в MAX: /admin %s", settings.admin_code)
    else:
        log.warning("Получателей уведомлений нет: задайте ADMIN_CODE или ADMIN_USER_IDS.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

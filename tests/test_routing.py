"""Проверка маршрутизации: события проходят через настоящий Dispatcher с фильтрами и FSM."""

import asyncio

from maxapi import Dispatcher
from maxapi.context.context import MemoryContext

from bot.handlers import routers
from db import repo
from db.session import init_db
from tools.fakes import ADMIN, USER, FakeBot, bot_started_event, callback_event, message_event


def build(bot: FakeBot) -> Dispatcher:
    dp = Dispatcher(storage=MemoryContext)
    dp.include_routers(*routers)
    dp.bot = bot
    return dp


def test_dialog_through_dispatcher():
    """Полный путь: кнопки и тексты попадают в нужные обработчики, заявка сохраняется."""

    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)
        events = [
            bot_started_event(bot),
            callback_event(bot, "menu:new"),
            callback_event(bot, "form:self"),
            callback_event(bot, "form:mode:one"),
            message_event(bot, "Лампа настольная Xiaomi"),
            message_event(bot, "3 шт"),
            message_event(bot, "https://ozon.ru/product/lampa"),
            callback_event(bot, "form:deadline:month"),
            message_event(bot, "В переговорную, темно по вечерам"),
            callback_event(bot, "form:submit"),
        ]
        for event in events:
            await dp.handle(event)

        rows = await repo.list_requests(query="Лампа настольная Xiaomi")
        assert len(rows) == 1
        request = rows[0]
        assert request.quantity == "3 шт"
        assert request.deadline == "В течение месяца"
        assert request.purpose == "В переговорную, темно по вечерам"
        assert request.example_url == "https://ozon.ru/product/lampa"

    asyncio.run(scenario())


def test_commands_are_routed():
    """/help и /my доходят до обработчиков, а не до fallback."""

    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)

        await dp.handle(message_event(bot, "/help"))
        assert "Что я умею" in bot.messages[-1]["text"]

        await dp.handle(message_event(bot, "/my"))
        assert "заявк" in bot.messages[-1]["text"].lower()

    asyncio.run(scenario())


def test_unknown_text_goes_to_fallback():
    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)
        await dp.handle(message_event(bot, "привет, как дела"))
        assert "Не понял" in bot.messages[-1]["text"]

    asyncio.run(scenario())


def test_cancel_during_form():
    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)
        await dp.handle(callback_event(bot, "menu:new"))
        await dp.handle(callback_event(bot, "form:self"))
        await dp.handle(message_event(bot, "/cancel"))
        assert "отменено" in bot.messages[-1]["text"].lower()

        # после отмены обычный текст снова обрабатывает fallback
        await dp.handle(message_event(bot, "что-то постороннее"))
        assert "Не понял" in bot.messages[-1]["text"]

    asyncio.run(scenario())


def test_admin_command_subscribes_and_button_works():
    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)

        await dp.handle(message_event(bot, "/admin неверный-код"))
        assert bot.messages[-1]["text"] == "Неверный код."

        # ADMIN_CODE задан в tests/conftest.py
        await dp.handle(message_event(bot, "/admin test-code"))
        assert "уведомления" in bot.messages[-1]["text"]
        assert USER["user_id"] in await repo.admin_ids()

        await repo.remove_admin(USER["user_id"])

    asyncio.run(scenario())


def test_new_request_notifies_admin_from_env():
    """ADMIN_USER_IDS из .env получает карточку новой заявки с кнопками статусов."""

    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)
        for event in [
            callback_event(bot, "menu:new"),
            callback_event(bot, "form:self"),
            callback_event(bot, "form:mode:one"),
            message_event(bot, "Бумага А4"),
            message_event(bot, "5 пачек"),
            callback_event(bot, "form:skip"),
            callback_event(bot, "form:deadline:urgent"),
            message_event(bot, "Закончилась в принтере"),
            callback_event(bot, "form:submit"),
        ]:
            await dp.handle(event)

        to_admin = [m for m in bot.messages if m["user_id"] == ADMIN["user_id"]]
        assert to_admin, "админ должен получить уведомление"
        assert "Новая заявка" in to_admin[-1]["text"]
        assert any("В работе" in button for button in to_admin[-1]["buttons"])

    asyncio.run(scenario())


def test_requester_other_person():
    """«Это не я» → бот просит ФИО, следующий текст становится заказчиком."""

    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)

        await dp.handle(callback_event(bot, "menu:new"))
        await dp.handle(callback_event(bot, "form:other"))
        assert "Впишите ФИО" in bot.messages[-1]["text"]

        await dp.handle(message_event(bot, "Иванова Мария, бухгалтерия"))
        # дальше идёт развилка о количестве позиций — значит ФИО приняли
        assert "Сколько позиций" in bot.messages[-1]["text"]

        for event in [
            callback_event(bot, "form:mode:one"),
            message_event(bot, "Степлер"),
            message_event(bot, "1 шт"),
            callback_event(bot, "form:skip"),
            callback_event(bot, "form:deadline:any"),
            message_event(bot, "Нечем скреплять документы"),
            callback_event(bot, "form:submit"),
        ]:
            await dp.handle(event)

        rows = await repo.list_requests(query="Степлер")
        assert rows[0].requester == "Иванова Мария, бухгалтерия"
        assert rows[0].author_name == "Иван Петров", "автором остаётся тот, кто оформлял"

    asyncio.run(scenario())


def test_requester_self_button_still_works():
    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)
        await dp.handle(callback_event(bot, "menu:new"))
        await dp.handle(callback_event(bot, "form:self"))
        assert "Сколько позиций" in bot.messages[-1]["text"]
        await dp.handle(callback_event(bot, "form:mode:one"))
        assert "Что нужно заказать" in bot.messages[-1]["text"]

    asyncio.run(scenario())

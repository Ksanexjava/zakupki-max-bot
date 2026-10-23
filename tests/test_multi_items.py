"""Несколько позиций в одной заявке: по очереди и списком."""

import asyncio

from maxapi import Dispatcher
from maxapi.context.context import MemoryContext

from bot.handlers import routers
from core.parsing import parse_items
from db import repo
from db.session import init_db
from tools.fakes import USER, FakeBot, callback_event, message_event


def build(bot: FakeBot) -> Dispatcher:
    dp = Dispatcher(storage=MemoryContext)
    dp.include_routers(*routers)
    dp.bot = bot
    return dp


def test_several_positions_one_by_one():
    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)

        for event in [
            callback_event(bot, "menu:new"),
            callback_event(bot, "form:self"),
            callback_event(bot, "form:mode:many"),
            # позиция 1
            message_event(bot, "Гель для стирки Ariel"),
            message_event(bot, "10 шт"),
            message_event(bot, "https://ozon.ru/t/gel"),
            callback_event(bot, "form:more"),
            # позиция 2
            message_event(bot, "Перчатки х/б с ПВХ, размер 10"),
            message_event(bot, "20 пар"),
            callback_event(bot, "form:skip"),
            callback_event(bot, "form:done"),
            # общее
            callback_event(bot, "form:deadline:urgent"),
            message_event(bot, "Уборка в отделениях"),
            callback_event(bot, "form:submit"),
        ]:
            await dp.handle(event)

        rows = await repo.list_requests(author_user_id=USER["user_id"], limit=1)
        request = rows[0]
        assert len(request.items) == 2
        first, second = request.items
        assert (first.name, first.quantity, first.link) == (
            "Гель для стирки Ariel", "10 шт", "https://ozon.ru/t/gel",
        )
        assert (second.name, second.quantity, second.link) == (
            "Перчатки х/б с ПВХ, размер 10", "20 пар", None,
        )
        # срок и цель — общие на всю заявку, спрошены один раз
        assert request.deadline == "Срочно, сегодня-завтра"
        assert request.purpose == "Уборка в отделениях"
        # заголовок заявки — первая позиция
        assert request.item == "Гель для стирки Ariel"

    asyncio.run(scenario())


def test_list_mode_parses_and_asks_missing_quantity():
    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)

        await dp.handle(callback_event(bot, "menu:new"))
        await dp.handle(callback_event(bot, "form:self"))
        await dp.handle(callback_event(bot, "form:mode:list"))
        assert "Пришлите список" in bot.messages[-1]["text"]

        await dp.handle(message_event(
            bot,
            "Пемолюкс Лимон порошок 480г — 10 шт https://ozon.ru/t/pem\n"
            "MR PROPER Моющая жидкость 1.5л https://ozon.ru/t/mp\n"
            "Жидкое мыло ABSOLUT 5 л — 2 шт",
        ))
        parsed = bot.messages[-1]["text"]
        assert "позиций: 3" in parsed
        assert "Пемолюкс" in parsed

        await dp.handle(callback_event(bot, "form:list:ok"))
        # у второй позиции количества не было — бот спрашивает именно его
        assert "Позиция 2 из 3" in bot.messages[-1]["text"]
        await dp.handle(message_event(bot, "10 шт"))

        await dp.handle(callback_event(bot, "form:deadline:week"))
        await dp.handle(message_event(bot, "Уборка"))
        await dp.handle(callback_event(bot, "form:submit"))

        rows = await repo.list_requests(query="MR PROPER")
        request = rows[0]
        assert [i.quantity for i in request.items] == ["10 шт", "10 шт", "2 шт"]
        assert request.items[1].link == "https://ozon.ru/t/mp"

    asyncio.run(scenario())


def test_list_mode_rejects_empty_text():
    async def scenario():
        await init_db()
        bot = FakeBot()
        dp = build(bot)
        await dp.handle(callback_event(bot, "menu:new"))
        await dp.handle(callback_event(bot, "form:self"))
        await dp.handle(callback_event(bot, "form:mode:list"))
        await dp.handle(message_event(bot, "   "))
        assert "Не получилось разобрать" in bot.messages[-1]["text"]

    asyncio.run(scenario())


def test_parser_keeps_name_and_link_apart():
    items = parse_items(
        "Гель д/стирки — 10 шт https://ozon.ru/t/abc\n"
        "• Средство AOS Османтус, 4,8 кг https://ozon.ru/t/V2fR8Ue 5 шт\n"
        "Матрасы медицинские, 200*90"
    )
    assert [i["name"] for i in items] == [
        "Гель д/стирки",
        "Средство AOS Османтус, 4,8 кг",
        "Матрасы медицинские, 200*90",
    ]
    assert [i["quantity"] for i in items] == ["10 шт", "5 шт", ""]
    assert items[0]["link"] == "https://ozon.ru/t/abc"
    assert items[2]["link"] is None


def test_bought_mark_does_not_touch_status():
    async def scenario():
        await init_db()
        created = await repo.create_request({
            "requester": "Склад", "author_user_id": 7, "purpose": "Уборка",
            "items": [{"name": "Швабра", "quantity": "2 шт"},
                      {"name": "Ведро", "quantity": "2 шт"}],
        })
        await repo.set_item_bought(created.items[0].id, True)
        data = repo.to_dict(await repo.get_request(created.id))
        assert data["bought_count"] == 1 and data["items_count"] == 2
        assert data["status"] == "new", "отметка «куплено» статус заявки не меняет"

        await repo.set_item_bought(created.items[0].id, False)
        data = repo.to_dict(await repo.get_request(created.id))
        assert data["bought_count"] == 0

    asyncio.run(scenario())

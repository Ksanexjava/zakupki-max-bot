"""Склад: приём, выдача, роли, наклейки."""

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from config import settings
from core.quantities import format_quantity, normalize_name, parse_quantity
from db import repo
from db.session import init_db
from panel.server import create_app
from tools.fakes import FakeBot

ADMIN_LOGIN, ADMIN_PASS = "boss", "пароль-закупок"
STOCK_LOGIN, STOCK_PASS = "sklad", "пароль-склада"


def run(coro):
    return asyncio.run(coro)


async def _client(bot=None) -> TestClient:
    await init_db()
    settings.panel_users[ADMIN_LOGIN] = {"password": ADMIN_PASS, "role": "admin"}
    settings.panel_users[STOCK_LOGIN] = {"password": STOCK_PASS, "role": "stock"}
    client = TestClient(TestServer(create_app(bot=bot)))
    await client.start_server()
    return client


async def _login(client: TestClient, login: str, password: str) -> dict:
    response = await client.post("/api/login", json={"login": login, "password": password})
    assert response.status == 200
    return await response.json()


async def _queue_of(request_id: int, kind: str = "pending") -> list[dict]:
    """Очередь склада только по одной заявке — тесты делят общую базу."""
    rows = await repo.stock_queue(kind)
    return [row for row in rows if row["request_id"] == request_id]


async def _ordered_request(**overrides):
    """Заявка, уехавшая на склад: две позиции, обе отмечены купленными."""
    data = {
        "requester": "ЛуЧиК СвЕтА",
        "purpose": "Уборка",
        "deadline": "Срочно",
        "author_user_id": 4242,
        "author_name": "Светлана Лучик",
        "items": [
            {"name": "Гель для стирки Ariel", "quantity": "10 шт"},
            {"name": "Перчатки х/б", "quantity": "20 пар"},
        ],
    }
    data.update(overrides)
    created = await repo.create_request(data)
    await repo.mark_items_bought(created.id)
    return created


# ----------------------------------------------------------- разбор количеств

def test_quantity_parsing():
    assert parse_quantity("10 шт") == (10.0, "шт")
    assert parse_quantity("2,5 кг") == (2.5, "кг")
    assert parse_quantity("20 пар") == (20.0, "пар")
    # «2 коробки по 10 шт» — берём только явное число в начале
    assert parse_quantity("2 коробки по 10 шт") == (2.0, "коробки")
    assert parse_quantity("не указано")[0] is None
    assert format_quantity(10.0, "шт") == "10 шт"
    assert normalize_name("  Гель  для Стирки, ") == "гель для стирки"


# ------------------------------------------------------------------ очереди

def test_only_bought_items_reach_stock():
    async def scenario():
        await init_db()
        created = await repo.create_request({
            "requester": "Склад", "author_user_id": 1, "purpose": "x",
            "items": [{"name": "Швабра", "quantity": "2 шт"}],
        })
        assert await _queue_of(created.id) == []
        await repo.mark_items_bought(created.id)
        queue = await _queue_of(created.id)
        assert [row["name"] for row in queue] == ["Швабра"]
        assert queue[0]["stock_code"] == f"ZK-{created.id}-01"

    run(scenario())


def test_partial_receipt_then_full():
    async def scenario():
        await init_db()
        created = await _ordered_request()
        item = (await _queue_of(created.id))[0]

        result = await repo.record_movement(item["id"], "in", 7, actor_name="Иванов")
        assert result["item"]["received"] == 7
        assert result["item"]["received_done"] is False
        assert result["request_arrived"] is False

        result = await repo.record_movement(item["id"], "in", 3, actor_name="Иванов")
        assert result["item"]["received_done"] is True, "10 из 10 — позиция закрыта"

        # вторая позиция ещё не принята, значит заявка не собрана
        assert result["request_arrived"] is False

    run(scenario())


def test_arrival_and_completion_close_the_request():
    async def scenario():
        bot = FakeBot()
        client = await _client(bot)
        try:
            created = await _ordered_request()
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            queue = await _queue_of(created.id)

            bot.messages.clear()
            for row in queue[:-1]:
                await client.post("/api/stock/movement", json={
                    "kind": "in", "item_id": row["id"], "quantity": row["qty_number"],
                    "close": True, "actor_name": "Иванов",
                })
            assert not bot.messages, "пока приехало не всё — автору не пишем"

            last = await client.post("/api/stock/movement", json={
                "kind": "in", "item_id": queue[-1]["id"], "quantity": queue[-1]["qty_number"],
                "close": True, "actor_name": "Иванов",
            })
            body = await last.json()
            assert body["request_arrived"] is True
            assert "на складе" in bot.messages[-1]["text"]
            assert bot.messages[-1]["user_id"] == 4242

            # повторное событие не должно писать автору второй раз
            assert (await repo.get_request(created.id)).arrived_notified is True

            on_hand = await _queue_of(created.id, "on_hand")
            assert len(on_hand) == 2
            for row in on_hand:
                await client.post("/api/stock/movement", json={
                    "kind": "out", "item_id": row["id"], "quantity": row["on_hand"],
                    "close": True, "actor_name": "Иванов", "recipient_name": "Светлана Лучик",
                })

            request = await repo.get_request(created.id)
            assert request.status == "done", "всё выдано — заявка закрывается сама"
            history = await repo.history(created.id)
            assert history[-1].comment == "Все позиции выданы со склада"
        finally:
            await client.close()

    run(scenario())


def test_recipient_can_differ_from_author():
    async def scenario():
        client = await _client()
        try:
            created = await _ordered_request()
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            employee = await repo.add_employee("Петров Пётр", "хозчасть")

            row = (await _queue_of(created.id))[0]
            await client.post("/api/stock/movement", json={
                "kind": "in", "item_id": row["id"], "quantity": row["qty_number"],
                "close": True, "actor_name": "Иванов",
            })
            await client.post("/api/stock/movement", json={
                "kind": "out", "item_id": row["id"], "quantity": row["qty_number"],
                "close": True, "actor_name": "Иванов",
                "recipient_employee_id": employee["id"], "recipient_name": employee["full_name"],
            })
            last = (await repo.movements_history(1))[0]
            assert last["kind"] == "out"
            assert last["recipient_name"] == "Петров Пётр"
        finally:
            await client.close()

    run(scenario())


def test_products_directory_builds_itself():
    async def scenario():
        await init_db()
        first = await _ordered_request()
        second = await _ordered_request()

        for created in (first, second):
            item = next(
                row for row in await _queue_of(created.id)
                if row["name"] == "Гель для стирки Ariel"
            )
            await repo.record_movement(item["id"], "in", 10, actor_name="Иванов", close=True)

        # одинаковое название из двух заявок — один товар в справочнике
        from sqlalchemy import select
        from db.models import Product
        from db.session import Session
        async with Session() as session:
            products = (await session.execute(select(Product))).scalars().all()
            gels = [p for p in products if p.norm_name == "гель для стирки ariel"]
            assert len(gels) == 1

    run(scenario())


# -------------------------------------------------------------------- роли

def test_stock_role_cannot_touch_requests():
    async def scenario():
        client = await _client()
        try:
            created = await _ordered_request()
            data = await _login(client, STOCK_LOGIN, STOCK_PASS)
            assert data["role"] == "stock"

            # склад не меняет статусы, не удаляет и не видит список заявок
            assert (await client.post(f"/api/requests/{created.id}/status",
                                      json={"status": "done"})).status == 403
            assert (await client.delete(f"/api/requests/{created.id}")).status == 403
            assert (await client.get("/api/requests")).status == 403

            # зато склад работает со своими экранами
            assert (await client.get("/api/stock/queue")).status == 200
            assert (await client.get("/api/employees")).status == 200
            assert (await client.get("/labels?request=%s" % created.id)).status == 200
        finally:
            await client.close()

    run(scenario())


def test_admin_role_keeps_full_access():
    async def scenario():
        client = await _client()
        try:
            created = await _ordered_request()
            data = await _login(client, ADMIN_LOGIN, ADMIN_PASS)
            assert data["role"] == "admin"
            assert (await client.get("/api/requests")).status == 200
            assert (await client.post(f"/api/requests/{created.id}/status",
                                      json={"status": "clarify"})).status == 200
            assert (await client.get("/api/stock/queue")).status == 200
        finally:
            await client.close()

    run(scenario())


def test_ordered_status_sends_items_to_stock():
    async def scenario():
        client = await _client()
        try:
            created = await repo.create_request({
                "requester": "Отдел", "author_user_id": 5, "purpose": "x",
                "items": [{"name": "Стулья", "quantity": "4 шт"},
                          {"name": "Стол", "quantity": "1 шт"}],
            })
            await _login(client, ADMIN_LOGIN, ADMIN_PASS)
            assert await _queue_of(created.id) == []

            await client.post(f"/api/requests/{created.id}/status", json={"status": "ordered"})
            queue = await _queue_of(created.id)
            assert {row["name"] for row in queue} == {"Стулья", "Стол"}
        finally:
            await client.close()

    run(scenario())


# ---------------------------------------------------------------- наклейки

def test_labels_sheet_has_qr_and_codes():
    async def scenario():
        client = await _client()
        try:
            created = await _ordered_request()
            await _login(client, ADMIN_LOGIN, ADMIN_PASS)

            response = await client.get(f"/labels?request={created.id}")
            assert response.status == 200
            page = await response.text()
            assert page.count("<svg") == 2, "по QR на каждую позицию"
            assert f"ZK-{created.id}-01" in page
            assert "Гель для стирки Ariel" in page

            assert (await client.get("/labels?request=999999")).status == 404
        finally:
            await client.close()

    run(scenario())


def test_find_item_by_stock_code():
    async def scenario():
        client = await _client()
        try:
            created = await _ordered_request()
            await _login(client, STOCK_LOGIN, STOCK_PASS)

            code = f"ZK-{created.id}-02"
            found = await (await client.get(f"/api/stock/find?code={code.lower()}")).json()
            assert found["item"]["name"] == "Перчатки х/б"
            assert found["request"]["id"] == created.id
            assert (await client.get("/api/stock/find?code=ZK-999-99")).status == 404
        finally:
            await client.close()

    run(scenario())

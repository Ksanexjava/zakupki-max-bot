"""Проверка HTTP-панели: авторизация, список, смена статуса."""

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from config import settings
from db import repo
from db.session import init_db
from panel.server import create_app
from tools.fakes import FakeBot

LOGIN = "tester"
PASSWORD = "пароль-с-кириллицей"


def run(coro):
    return asyncio.run(coro)


async def _client(bot=None) -> TestClient:
    await init_db()
    settings.panel_users[LOGIN] = PASSWORD
    client = TestClient(TestServer(create_app(bot=bot)))
    await client.start_server()
    return client


async def _make_request(**overrides):
    data = {
        "requester": "Панель Тест",
        "item": "Коврик для мыши",
        "quantity": "1 шт",
        "deadline": "Не срочно",
        "purpose": "Старый протёрся",
        "author_user_id": 31337,
        "author_name": "Панель Тест",
    }
    data.update(overrides)
    return await repo.create_request(data)


async def _login(client: TestClient) -> None:
    response = await client.post("/api/login", json={"login": LOGIN, "password": PASSWORD})
    assert response.status == 200


def test_requires_auth():
    async def scenario():
        client = await _client()
        try:
            assert (await client.get("/api/requests")).status == 401
            assert (await client.get("/healthz")).status == 200
            bad = await client.post("/api/login", json={"login": LOGIN, "password": "не тот"})
            assert bad.status == 401
        finally:
            await client.close()

    run(scenario())


def test_list_and_status_change():
    async def scenario():
        client = await _client()
        try:
            created = await repo.create_request(
                {
                    "requester": "Панель Тест",
                    "item": "Коврик для мыши",
                    "quantity": "1 шт",
                    "deadline": "Не срочно",
                    "purpose": "Старый протёрся",
                    "author_user_id": 31337,
                    "author_name": "Панель Тест",
                }
            )
            await _login(client)

            listing = await (await client.get("/api/requests")).json()
            assert any(row["id"] == created.id for row in listing["requests"])
            assert listing["counts"]["new"] >= 1

            changed = await client.post(
                f"/api/requests/{created.id}/status",
                data=json.dumps({"status": "ordered", "comment": "Купили в ближайшем магазине"}),
                headers={"Content-Type": "application/json"},
            )
            body = await changed.json()
            assert body["ok"] and body["request"]["status_label"] == "Заказано"
            # бота нет — значит и уведомления автору быть не должно
            assert body["author_notified"] is False
            assert body["notify_error"] == "бот не запущен"

            detail = await (await client.get(f"/api/requests/{created.id}")).json()
            assert detail["request"]["admin_comment"] == "Купили в ближайшем магазине"
            assert [item["to_status"] for item in detail["history"]] == ["new", "ordered"]

            assert (await client.post(f"/api/requests/{created.id}/status",
                                      json={"status": "выдуманный"})).status == 400
            assert (await client.get("/api/requests/999999")).status == 404
        finally:
            await client.close()

    run(scenario())


def test_media_path_traversal_blocked():
    async def scenario():
        client = await _client()
        try:
            await _login(client)
            response = await client.get("/media/..%2F..%2Fconfig.py")
            assert response.status == 404
        finally:
            await client.close()

    run(scenario())


def test_delete_request():
    async def scenario():
        bot = FakeBot()
        client = await _client(bot)
        try:
            created = await _make_request(item="Заявка на удаление")
            await _login(client)

            response = await client.delete(f"/api/requests/{created.id}")
            body = await response.json()
            assert body["ok"] and body["author_notified"] is True

            assert await repo.get_request(created.id) is None
            assert (await client.get(f"/api/requests/{created.id}")).status == 404
            assert (await client.delete(f"/api/requests/{created.id}")).status == 404

            # автору ушло сообщение об удалении
            assert "удалена" in bot.messages[-1]["text"]
        finally:
            await client.close()

    run(scenario())


def test_comment_is_sent_to_author():
    async def scenario():
        bot = FakeBot()
        client = await _client(bot)
        try:
            created = await _make_request(item="Заявка с комментарием")
            await _login(client)

            response = await client.post(
                f"/api/requests/{created.id}/comment",
                json={"comment": "Нашли дешевле, уточните цвет"},
            )
            body = await response.json()
            assert body["ok"] and body["author_notified"] is True
            assert "Нашли дешевле" in bot.messages[-1]["text"]
            assert bot.messages[-1]["user_id"] == 31337

            # пустой комментарий не принимаем
            assert (await client.post(f"/api/requests/{created.id}/comment",
                                      json={"comment": "   "})).status == 400
        finally:
            await client.close()

    run(scenario())


def test_done_status_available():
    async def scenario():
        bot = FakeBot()
        client = await _client(bot)
        try:
            created = await _make_request(item="Заявка для статуса Выполнено")
            await _login(client)

            meta = await (await client.get("/api/meta")).json()
            assert "done" in [status["key"] for status in meta["statuses"]]

            response = await client.post(
                f"/api/requests/{created.id}/status", json={"status": "done"}
            )
            body = await response.json()
            assert body["request"]["status_label"] == "Выполнено"
            assert body["author_notified"] is True
            assert "Выполнено" in bot.messages[-1]["text"]
        finally:
            await client.close()

    run(scenario())

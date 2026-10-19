"""Проверка слоя доступа к данным и справочника статусов."""

import asyncio

from core.statuses import DEFAULT_STATUS, STATUSES, is_valid, label
from db import repo
from db.session import init_db

SAMPLE = {
    "requester": "Тестов Тест, отдел",
    "item": "Степлер",
    "quantity": "2 шт",
    "deadline": "Не срочно",
    "purpose": "Нечем скреплять документы",
    "author_user_id": 4242,
    "author_name": "Тестов Тест",
}


def test_statuses_reference():
    assert DEFAULT_STATUS in STATUSES
    assert is_valid("ordered") and not is_valid("нет-такого")
    assert label("clarify") == "❓ На уточнении"


def test_create_set_status_and_history():
    async def scenario():
        await init_db()
        created = await repo.create_request(dict(SAMPLE))
        assert created.status == DEFAULT_STATUS

        result = await repo.set_status(created.id, "clarify", "admin", "Какой нужен — ручной?")
        assert result is not None
        updated, previous = result
        assert previous == "new"
        assert updated.status == "clarify"
        assert updated.admin_comment == "Какой нужен — ручной?"

        history = await repo.history(created.id)
        assert len(history) == 2
        assert history[-1].actor == "admin"

        counts = await repo.counts_by_status()
        assert counts.get("clarify", 0) >= 1

    asyncio.run(scenario())


def test_search_and_filters():
    async def scenario():
        await init_db()
        created = await repo.create_request({**SAMPLE, "item": "Уникальный маркер XYZ"})
        found = await repo.list_requests(query="XYZ")
        assert any(row.id == created.id for row in found)

        by_author = await repo.list_requests(author_user_id=SAMPLE["author_user_id"])
        assert all(row.author_user_id == SAMPLE["author_user_id"] for row in by_author)

        by_number = await repo.list_requests(query=str(created.id))
        assert any(row.id == created.id for row in by_number)

    asyncio.run(scenario())


def test_admins():
    async def scenario():
        await init_db()
        assert await repo.add_admin(555, "Первый") is True
        assert await repo.add_admin(555, "Первый") is False
        assert 555 in await repo.admin_ids()
        assert await repo.is_admin(555)
        assert await repo.is_admin(777, extra=[777])
        await repo.remove_admin(555)
        assert not await repo.is_admin(555)

    asyncio.run(scenario())


def test_missing_request():
    async def scenario():
        await init_db()
        assert await repo.get_request(999999) is None
        assert await repo.set_status(999999, "ordered", "admin") is None
        assert await repo.add_comment(999999, "admin", "привет") is None

    asyncio.run(scenario())

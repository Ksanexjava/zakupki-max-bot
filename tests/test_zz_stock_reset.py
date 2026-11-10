"""Очистка склада. Файл назван так, чтобы идти последним: чистка трогает всю общую тестовую базу."""

import asyncio

from db import repo
from tests.test_stock import _ordered_request
from tools.stock_reset import reset_stock


def run(coro):
    return asyncio.run(coro)


def test_reset_keeps_chosen_and_returns_items_to_pending():
    async def scenario():
        from db.session import init_db
        await init_db()
        created = await _ordered_request(items=[
            {"name": "Стиральная машина (сброс)", "quantity": "1 шт"},
            {"name": "Салфетки (сброс)", "quantity": "5 уп"},
        ])
        machine, wipes = (await repo.get_request(created.id)).items
        for item in (machine, wipes):
            await repo.record_movement(item.id, "in", item.qty_number, "Кладовщик", close=True)
        await repo.receive_manual(name="Маркеры (сброс)", quantity=1)

        plan = await reset_stock(["салфетки (сброс)", "нет такого"])
        assert plan["unmatched"] == ["нет такого"] and plan["applied"] is False

        plan = await reset_stock(["Салфетки (сброс)"])          # только план
        assert plan["applied"] is False
        assert any(name == "Маркеры (сброс)" for name, _, _ in plan["drop"])
        assert (await repo.receiving_queue())["items"]           # пока всё на месте

        plan = await reset_stock(["Салфетки (сброс)"], apply=True)
        assert plan["applied"] is True and "Маркеры (сброс)" in plan["orphans"]

        zone = await repo.receiving_queue()
        assert [i["name"] for i in zone["items"]] == ["Салфетки (сброс)"]
        assert zone["instances"] == []
        pending = [row["name"] for row in await repo.stock_queue("pending") if row["request_id"] == created.id]
        assert pending == ["Стиральная машина (сброс)"]           # вернулась в «Ждём поставку»
        assert all(p["name"] != "Маркеры (сброс)" for p in await repo.products_catalog())

    run(scenario())

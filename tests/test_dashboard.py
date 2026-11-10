"""Дашборд склада, отчёт по сотруднику, приём без заявки."""

import asyncio
from datetime import date, timedelta

from db import analytics, repo
from tests.test_stock import ADMIN_LOGIN, ADMIN_PASS, STOCK_LOGIN, STOCK_PASS, _client, _login
from tests.test_storage import _category_id


def run(coro):
    return asyncio.run(coro)


def test_period_defaults_and_buckets():
    start, end = analytics.parse_period(None, None)
    assert (end - start).days == 29
    start, end = analytics.parse_period("2026-03-10", "2026-03-01")   # перепутали — поправим
    assert start < end
    assert analytics._buckets(date(2026, 1, 1), date(2026, 1, 10))[0] == "day"
    assert analytics._buckets(date(2026, 1, 1), date(2026, 3, 1))[0] == "week"
    kind, buckets = analytics._buckets(date(2025, 1, 15), date(2026, 1, 10))
    assert kind == "month" and buckets[0][0] == date(2025, 1, 15) and len(buckets) == 13


def test_manual_receipt_goes_to_zone_with_chosen_category():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            office = await _category_id("Канцелярия")
            response = await client.post("/api/stock/receive-manual", json={
                "name": "Скрепки цветные (вручную)", "quantity": 4, "unit": "уп",
                "category_id": office, "note": "передала бухгалтерия", "actor_name": "Кладовщик",
            })
            result = await response.json()
            assert result["ok"] is True and result["instances_created"] == []

            zone = await (await client.get("/api/stock/receiving")).json()
            row = next(i for i in zone["items"] if i["name"] == "Скрепки цветные (вручную)")
            assert row["quantity"] == 4 and row["category_id"] == office

            history = await (await client.get("/api/stock/history?limit=5")).json()
            mine = next(m for m in history["movements"] if m["item_name"] == "Скрепки цветные (вручную)")
            assert mine["kind"] == "in" and mine["note"] == "передала бухгалтерия"

            # крупный товар без заявки тоже получает номера
            response = await client.post("/api/stock/receive-manual", json={
                "name": "Кровать функциональная (вручную)", "quantity": 2,
            })
            assert len((await response.json())["instances_created"]) == 2

            bad = await client.post("/api/stock/receive-manual", json={"name": " ", "quantity": 1})
            assert bad.status == 400

            suggestion = await (await client.get("/api/stock/classify", params={"name": "Перчатки нитриловые"})).json()
            assert suggestion["category_id"] is not None
        finally:
            await client.close()

    run(scenario())


def test_dashboard_counts_and_recipients():
    async def scenario():
        client = await _client()
        try:
            await _login(client, ADMIN_LOGIN, ADMIN_PASS)
            medicine = await _category_id("Медицина")
            consumables = await _category_id("Медицина", "Расходники")
            await repo.receive_manual(name="Бинт стерильный (дашборд)", quantity=10, unit="шт",
                                      category_id=consumables)
            product = next(p for p in await repo.products_catalog() if p["name"] == "Бинт стерильный (дашборд)")
            box = await repo.create_location("box", "Бинты", category_ids=[consumables])
            zone = await repo.receiving_queue()
            await repo.place(product_id=product["id"], quantity=10, to_location_id=box["id"])
            employee = await repo.add_employee("Сидорова Ольга (дашборд)", "Процедурный")
            for quantity in (2, 1):
                await repo.issue_from_stock(
                    product_id=product["id"], quantity=quantity, location_id=box["id"],
                    recipient_name=employee["full_name"], recipient_employee_id=employee["id"],
                )
            await repo.issue_from_stock(product_id=product["id"], quantity=3, location_id=box["id"],
                                        recipient_name="Сидорова Ольга (дашборд)")   # вписали вручную
            assert zone is not None

            response = await client.get("/api/stock/dashboard", params={"top": medicine})
            data = await response.json()
            assert data["level"] == "subcategories"
            group = next(g for g in data["groups"] if g["name"] == "Расходники")
            assert group["issues"] >= 3 and group["issued"] >= 6
            assert len(data["series_out"]) == len(data["labels"]) == 30
            assert any(s["code"] == box["code"] and s["assigned"] for s in data["shelves"])
            history_names = [h["name"] for h in data["history"]]
            assert "Бинт стерильный (дашборд)" in history_names

            response = await client.get("/api/stock/dashboard", params={"top": medicine, "sub": consumables})
            data = await response.json()
            assert data["level"] == "products"
            row = next(g for g in data["groups"] if g["name"] == "Бинт стерильный (дашборд)")
            assert row["on_hand"] == 4 and row["issued"] == 6

            people = await (await client.get("/api/stock/recipients")).json()
            person = next(r for r in people["recipients"] if r["name"] == "Сидорова Ольга (дашборд)")
            report = await (await client.get("/api/stock/recipient", params={"key": person["key"]})).json()
            # и выбранная из списка, и вписанная вручную выдача — её
            assert report["issues"] == 3 and report["units"] == 6
            assert report["by_category"][0]["name"] == "Медицина"
            assert report["top_products"][0]["name"] == "Бинт стерильный (дашборд)"

            old = (date.today() - timedelta(days=400)).isoformat()
            report = await (await client.get("/api/stock/recipient", params={
                "key": person["key"], "from": old, "to": old,
            })).json()
            assert report["issues"] == 0
            assert (await client.get("/api/stock/recipient", params={"key": "e999999"})).status == 404
        finally:
            await client.close()

    run(scenario())


def test_dashboard_is_admin_only():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            for path in ("/api/stock/dashboard", "/api/stock/recipients", "/api/stock/recipient?key=e1"):
                assert (await client.get(path)).status == 403, path
        finally:
            await client.close()

    run(scenario())


def test_labels_show_name_category_code():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            result = await repo.receive_manual(name="Кровать функциональная (этикетка)", quantity=1)
            code = result["instances_created"][0]
            html = await (await client.get("/labels", params={"codes": code})).text()
            assert "Кровать функциональная (этикетка)" in html
            assert "Медицина → Медицинская мебель" in html
            assert "инвентарный номер" not in html
        finally:
            await client.close()

    run(scenario())

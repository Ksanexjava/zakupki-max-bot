"""Хранение: категории, полки и коробки, размещение, выдача, сканер, наклейки."""

import asyncio

from core.categories import classify, parse_keywords
from db import repo
from tests.test_stock import (
    ADMIN_LOGIN, ADMIN_PASS, STOCK_LOGIN, STOCK_PASS, _client, _login, _ordered_request,
)


def run(coro):
    return asyncio.run(coro)


async def _category_id(top: str, sub: str | None = None) -> int:
    for node in await repo.list_categories():
        if node["name"] != top:
            continue
        if sub is None:
            return node["id"]
        for child in node["children"]:
            if child["name"] == sub:
                return child["id"]
    raise AssertionError(f"нет категории {top} → {sub}")


async def _receive_all(client, request_id: int) -> dict[str, dict]:
    """Принимает все позиции заявки и возвращает их по названию."""
    found = await repo.get_request(request_id)
    result = {}
    for item in found.items:
        response = await client.post("/api/stock/movement", json={
            "kind": "in", "item_id": item.id, "quantity": item.qty_number, "close": True,
            "actor_name": "Кладовщик",
        })
        assert response.status == 200
        result[item.name] = await response.json()
    return result


# ------------------------------------------------------------ классификатор

def test_keyword_syntax_and_weights():
    rules = [
        *parse_keywords(1, "перчат", 0),             # начало слова
        *parse_keywords(2, "перчат+нитрил", 1),      # обе части — вес больше
        *parse_keywords(3, "=чай", 2),               # слово целиком
        *parse_keywords(4, "для стирки", 3),         # фраза
    ]
    assert classify("Перчатки х/б", rules) == 1
    assert classify("Перчатки нитриловые M", rules) == 2
    assert classify("Чай чёрный", rules) == 3
    assert classify("Чайник электрический", rules) is None
    assert classify("Гель для стирки", rules) == 4
    assert classify("Стиральный порошок", rules) is None


def test_default_dictionary_sorts_real_names():
    async def scenario():
        client = await _client()
        try:
            await _login(client, ADMIN_LOGIN, ADMIN_PASS)
            created = await _ordered_request(items=[
                {"name": "Спиртовые салфетки для инъекций (хран)", "quantity": "10 уп"},
                {"name": "Кровать функциональная медицинская (хран)", "quantity": "1 шт"},
                {"name": "Гель для стирки Ariel (хран)", "quantity": "3 шт"},
            ])
            await _receive_all(client, created.id)
            catalog = {p["name"]: p for p in await repo.products_catalog()}
            assert catalog["Спиртовые салфетки для инъекций (хран)"]["path"] == "Медицина → Расходники"
            bed = catalog["Кровать функциональная медицинская (хран)"]
            assert bed["path"] == "Медицина → Медицинская мебель"
            assert bed["serialized"] is True
            assert catalog["Гель для стирки Ariel (хран)"]["path"] == "Бытовая химия → Стирка"
        finally:
            await client.close()

    run(scenario())


def test_manual_category_survives_reclassification():
    async def scenario():
        client = await _client()
        try:
            await _login(client, ADMIN_LOGIN, ADMIN_PASS)
            created = await _ordered_request(items=[{"name": "Загадочная штука", "quantity": "1 шт"}])
            await _receive_all(client, created.id)
            product = next(p for p in await repo.products_catalog() if p["name"] == "Загадочная штука")
            assert product["category_id"] is None

            office = await _category_id("Канцелярия")
            response = await client.post(f"/api/stock/products/{product['id']}", json={"category_id": office})
            assert response.status == 200
            await repo.classify_unassigned_products()
            product = next(p for p in await repo.products_catalog() if p["name"] == "Загадочная штука")
            assert product["category_id"] == office
            assert product["category_manual"] is True
        finally:
            await client.close()

    run(scenario())


# ----------------------------------------------------------- места хранения

def test_shelves_boxes_and_purposes():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            medicine = await _category_id("Медицина")
            consumables = await _category_id("Медицина", "Расходники")
            furniture = await _category_id("Медицина", "Медицинская мебель")

            # полка — целиком под раздел; подраздел ей назначить нельзя
            response = await client.post("/api/stock/locations", json={
                "kind": "shelf", "name": "Полка медицины", "category_ids": [consumables],
            })
            assert (response.status, (await response.json())["error"]) == (400, "bad_category")
            response = await client.post("/api/stock/locations", json={
                "kind": "shelf", "name": "Полка медицины", "category_ids": [medicine],
            })
            shelf = (await response.json())["location"]
            assert shelf["code"].startswith("SH-") and shelf["category_ids"] == [medicine]

            # коробка и место на полке — под подраздел
            response = await client.post("/api/stock/locations", json={
                "kind": "box", "name": "Салфетки", "parent_id": shelf["id"], "category_ids": [medicine],
            })
            assert (await response.json())["error"] == "bad_category"
            response = await client.post("/api/stock/locations", json={
                "kind": "box", "name": "Салфетки", "parent_id": shelf["id"], "category_ids": [consumables],
            })
            box = (await response.json())["location"]
            assert box["code"].startswith("BX-") and box["parent_id"] == shelf["id"]

            response = await client.post("/api/stock/locations", json={
                "kind": "lot", "name": "Место под кровати", "parent_id": shelf["id"], "category_ids": [furniture],
            })
            lot = (await response.json())["location"]
            assert lot["code"].startswith("LT-") and lot["parent_id"] == shelf["id"]

            # место на полке без полки не бывает, и родителем может быть только полка
            response = await client.post("/api/stock/locations", json={"kind": "lot", "name": "Без полки"})
            assert (await response.json())["error"] == "bad_parent"
            response = await client.post("/api/stock/locations", json={
                "kind": "lot", "name": "В коробке", "parent_id": box["id"],
            })
            assert (await response.json())["error"] == "bad_parent"

            found = await (await client.get("/api/stock/resolve", params={"code": lot["code"]})).json()
            assert found["type"] == "lot" and found["details"]["location"]["id"] == lot["id"]
            contents = await (await client.get(f"/api/stock/locations/{shelf['id']}")).json()
            assert {b["code"] for b in contents["boxes"]} == {box["code"], lot["code"]}

            # переименовали, не трогая назначение — категории остаются
            response = await client.post(f"/api/stock/locations/{shelf['id']}", json={"name": "Стеллаж 1"})
            assert (await response.json())["location"]["category_ids"] == [medicine]
            # коробку сняли с полки, а место на полке снять нельзя
            response = await client.post(f"/api/stock/locations/{box['id']}", json={"parent_id": None})
            assert (await response.json())["location"]["parent_id"] is None
            response = await client.post(f"/api/stock/locations/{lot['id']}", json={"parent_id": None})
            assert response.status == 400

            assert (await client.post("/api/stock/locations", json={"kind": "shelf", "name": " "})).status == 400
            assert (await client.post("/api/stock/locations", json={"kind": "zone", "name": "X"})).status == 400
        finally:
            await client.close()

    run(scenario())


def test_old_shelf_purposes_move_to_sections():
    async def scenario():
        from db import migrate
        from db.models import LocationCategory
        from db.session import Session
        from sqlalchemy import select

        await _client()
        medicine = await _category_id("Медицина")
        consumables = await _category_id("Медицина", "Расходники")
        furniture = await _category_id("Медицина", "Медицинская мебель")
        shelf = await repo.create_location("shelf", "Старая полка")
        async with Session() as session:      # как было до обновления: полка с подразделами
            session.add(LocationCategory(location_id=shelf["id"], category_id=consumables))
            session.add(LocationCategory(location_id=shelf["id"], category_id=furniture))
            await session.commit()
            await migrate.normalize_shelf_purposes(session)
            links = (await session.execute(
                select(LocationCategory).where(LocationCategory.location_id == shelf["id"])
            )).scalars().all()
        assert [link.category_id for link in links] == [medicine]

    run(scenario())


# ------------------------------------------------- размещение и выдача

def test_receive_place_issue_balances():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            created = await _ordered_request(items=[{"name": "Нашатырные салфетки (баланс)", "quantity": "10 уп"}])
            await _receive_all(client, created.id)

            zone = await (await client.get("/api/stock/receiving")).json()
            row = next(i for i in zone["items"] if i["name"] == "Нашатырные салфетки (баланс)")
            assert row["quantity"] == 10
            product_id = row["product_id"]

            shelf = await repo.create_location("shelf", "Полка баланса")
            box = await repo.create_location("box", "Коробка баланса", parent_id=shelf["id"])

            # больше, чем лежит в приёмке, положить нельзя
            response = await client.post("/api/stock/place", json={
                "product_id": product_id, "quantity": 11, "to_location_id": box["id"],
            })
            assert response.status == 400
            assert (await response.json()) == {"ok": False, "error": "not_enough", "available": 10}

            for target, quantity in ((box, 6), (shelf, 4)):
                response = await client.post("/api/stock/place", json={
                    "product_id": product_id, "quantity": quantity, "to_location_id": target["id"],
                    "actor_name": "Кладовщик",
                })
                assert (await response.json())["to"] == target["code"]

            overview = await (await client.get("/api/stock/overview")).json()
            row = next(p for p in overview["products"] if p["product_id"] == product_id)
            assert row["total"] == 10
            assert {p["code"]: p["quantity"] for p in row["places"]} == {box["code"]: 6, shelf["code"]: 4}

            # выдача без заявки — из конкретной коробки
            response = await client.post("/api/stock/issue", json={
                "product_id": product_id, "location_id": box["id"], "quantity": 3,
                "recipient_name": "Процедурный кабинет", "actor_name": "Кладовщик",
            })
            assert (await response.json()) == {"ok": True, "issued": 3}
            response = await client.post("/api/stock/issue", json={
                "product_id": product_id, "location_id": box["id"], "quantity": 4,
            })
            assert (await response.json())["available"] == 3

            contents = await (await client.get(f"/api/stock/locations/{box['id']}")).json()
            assert [(i["name"], i["quantity"]) for i in contents["items"]] == [("Нашатырные салфетки (баланс)", 3)]

            history = await (await client.get("/api/stock/history?limit=20")).json()
            mine = [m for m in history["movements"] if m["item_name"] == "Нашатырные салфетки (баланс)"]
            assert [m["kind"] for m in mine] == ["out", "move", "move", "in"]
            assert mine[0]["from_code"] == box["code"]
            assert mine[0]["recipient_name"] == "Процедурный кабинет"
        finally:
            await client.close()

    run(scenario())


def test_serialized_items_get_codes_and_move_one_by_one():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            created = await _ordered_request(items=[{"name": "Кровать функциональная (поштучно)", "quantity": "2 шт"}])
            received = await _receive_all(client, created.id)
            codes = received["Кровать функциональная (поштучно)"]["instances_created"]
            assert len(codes) == 2 and all(code.startswith("IN-") for code in codes)

            shelf = await repo.create_location("shelf", "Крупное")
            first = await (await client.get(f"/api/stock/resolve?code={codes[0]}")).json()
            assert first["type"] == "instance"
            assert first["details"]["location_code"] == "ZONE-IN"

            # «скан товара → скан полки»
            response = await client.post("/api/stock/place", json={
                "instance_id": first["id"], "to_location_id": shelf["id"],
            })
            assert (await response.json())["to"] == shelf["code"]

            item = (await repo.get_request(created.id)).items[0]
            response = await client.post("/api/stock/movement", json={
                "kind": "out", "item_id": item.id, "quantity": 1, "instance_ids": [first["id"]],
                "recipient_name": "Палата 4",
            })
            assert response.status == 200

            instances = {i["code"]: i for i in await repo.list_instances(item_id=item.id)}
            assert instances[codes[0]]["status"] == "issued"
            assert instances[codes[0]]["issued_to"] == "Палата 4"
            assert instances[codes[1]]["status"] == "stock"
            assert instances[codes[1]]["location_code"] == "ZONE-IN"

            # выданный экземпляр больше не переложить
            response = await client.post("/api/stock/place", json={
                "instance_id": first["id"], "to_location_id": shelf["id"],
            })
            assert (await response.json())["error"] == "no_instance"
        finally:
            await client.close()

    run(scenario())


# ------------------------------------------------------- сканер и наклейки

def test_resolve_understands_links_and_case():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            shelf = await repo.create_location("shelf", "Для сканера")
            code = shelf["code"]
            for raw in (code, code.lower(), f"https://zakupki.example.ru/s/{code}", f"http://x/s/{code}/"):
                found = await (await client.get("/api/stock/resolve", params={"code": raw})).json()
                assert (found["type"], found["code"]) == ("shelf", code), raw
                assert found["details"]["location"]["id"] == shelf["id"]
            assert (await client.get("/api/stock/resolve", params={"code": "NOPE-1"})).status == 404

            response = await client.get(f"/s/{code}", allow_redirects=False)
            assert response.status == 302
            assert response.headers["Location"] == f"/sklad#/scan/{code}"
        finally:
            await client.close()

    run(scenario())


def test_labels_for_shelves_boxes_and_instances():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            medicine = await _category_id("Медицина")
            consumables = await _category_id("Медицина", "Расходники")
            shelf = await repo.create_location("shelf", "Полка наклеек", category_ids=[medicine])
            box = await repo.create_location("box", "Коробка наклеек", parent_id=shelf["id"], category_ids=[consumables])
            created = await _ordered_request(items=[{"name": "Кровать функциональная (наклейка)", "quantity": "1 шт"}])
            received = await _receive_all(client, created.id)
            instance_code = received["Кровать функциональная (наклейка)"]["instances_created"][0]

            response = await client.get("/labels", params={"codes": f"{shelf['code']},{box['code']},{instance_code}"})
            assert response.status == 200
            html = await response.text()
            assert html.count("<svg") == 3
            for code in (shelf["code"], box["code"], instance_code):
                assert code in html
            assert "Медицина → Расходники" in html

            response = await client.get("/labels", params={"locations": str(box["id"])})
            assert box["code"] in await response.text()
            assert (await client.get("/labels", params={"codes": "NOPE-1"})).status == 404
        finally:
            await client.close()

    run(scenario())


def test_dictionary_is_admin_only():
    async def scenario():
        client = await _client()
        try:
            consumables = await _category_id("Медицина", "Расходники")
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            response = await client.post(f"/api/stock/categories/{consumables}/keywords", json={"keywords": "x"})
            assert response.status == 403

            await _login(client, ADMIN_LOGIN, ADMIN_PASS)
            tree = await (await client.get("/api/stock/categories")).json()
            before = next(c for t in tree["categories"] for c in t["children"] if c["id"] == consumables)["keywords"]
            response = await client.post(
                f"/api/stock/categories/{consumables}/keywords", json={"keywords": before + ", пробирк"}
            )
            assert response.status == 200
            tree = await (await client.get("/api/stock/categories")).json()
            after = next(c for t in tree["categories"] for c in t["children"] if c["id"] == consumables)["keywords"]
            assert after.endswith("пробирк")
        finally:
            await client.close()

    run(scenario())


def test_portal_pages_by_role():
    async def scenario():
        client = await _client()
        try:
            await _login(client, STOCK_LOGIN, STOCK_PASS)
            assert (await client.get("/")).status == 200
            assert (await client.get("/sklad")).status == 200
            response = await client.get("/zayavki", allow_redirects=False)
            assert response.status == 302 and response.headers["Location"] == "/"

            await _login(client, ADMIN_LOGIN, ADMIN_PASS)
            response = await client.get("/zayavki")
            assert response.status == 200
            assert response.headers["Cache-Control"].startswith("no-cache")
        finally:
            await client.close()

    run(scenario())

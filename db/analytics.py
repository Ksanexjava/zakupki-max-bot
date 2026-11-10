"""Аналитика склада для дашборда: остатки, приход и выдача, кто что забирал.

Данных немного (сотни движений), поэтому всё считается в Python по выборке
из базы — так проще и понятнее, чем городить агрегаты в SQL.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from config import settings
from db.models import Category, Employee, Location, LocationCategory, Movement, Product
from db.repo import _balances, _category_path
from db.session import Session

NO_CATEGORY = "Без категории"


def _local_tz() -> timezone:
    return timezone(timedelta(hours=settings.tz_offset))


def _local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_local_tz())


def parse_period(raw_from: str | None, raw_to: str | None) -> tuple[date, date]:
    """Период в местных датах, обе границы включительно. По умолчанию — 30 дней."""
    today = datetime.now(_local_tz()).date()

    def parse(value: str | None) -> date | None:
        try:
            return date.fromisoformat(value) if value else None
        except ValueError:
            return None

    end = parse(raw_to) or today
    start = parse(raw_from) or (end - timedelta(days=29))
    if start > end:
        start, end = end, start
    return start, end


def _buckets(start: date, end: date) -> tuple[str, list[tuple[date, date, str]]]:
    """Разбивка периода для графика: по дням, неделям или месяцам."""
    days = (end - start).days + 1
    buckets: list[tuple[date, date, str]] = []
    if days <= 31:
        current = start
        while current <= end:
            buckets.append((current, current, current.strftime("%d.%m")))
            current += timedelta(days=1)
        return "day", buckets
    if days <= 182:
        current = start - timedelta(days=start.weekday())
        while current <= end:
            last = current + timedelta(days=6)
            buckets.append((max(current, start), min(last, end), current.strftime("%d.%m")))
            current = last + timedelta(days=1)
        return "week", buckets
    current = start.replace(day=1)
    while current <= end:
        following = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        buckets.append((max(current, start), min(following - timedelta(days=1), end), current.strftime("%m.%Y")))
        current = following
    return "month", buckets


def _bucket_index(buckets: list[tuple[date, date, str]], day: date) -> int | None:
    for index, (first, last, _) in enumerate(buckets):
        if first <= day <= last:
            return index
    return None


def _recipient_key(movement: Movement) -> str:
    if movement.recipient_employee_id:
        return f"e{movement.recipient_employee_id}"
    name = (movement.recipient_name or "").strip()
    return f"n{name.lower()}" if name else ""


async def _load(session) -> dict[str, Any]:
    return {
        "categories": {c.id: c for c in (await session.execute(select(Category))).scalars().all()},
        "products": {p.id: p for p in (await session.execute(select(Product))).scalars().all()},
        "locations": {l.id: l for l in (await session.execute(select(Location))).scalars().all()},
        "links": (await session.execute(select(LocationCategory))).scalars().all(),
        "employees": {e.id: e for e in (await session.execute(select(Employee))).scalars().all()},
        "balances": await _balances(session),
        "movements": (await session.execute(select(Movement).order_by(Movement.id))).scalars().all(),
    }


def _top_of(category: Category | None, categories: dict[int, Category]) -> Category | None:
    if category is None:
        return None
    return categories.get(category.parent_id) if category.parent_id else category


async def dashboard(
    top_id: int | None = None,
    sub_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Всё для дашборда по выбранной части склада и периоду.

    Без фильтра группы — разделы склада; выбран раздел — его подкатегории;
    выбрана подкатегория — сами товары.
    """
    start, end = (start, end) if start and end else parse_period(None, None)
    async with Session() as session:
        data = await _load(session)
    categories: dict[int, Category] = data["categories"]
    products: dict[int, Product] = data["products"]
    locations: dict[int, Location] = data["locations"]
    zone_ids = {l.id for l in locations.values() if l.kind == "zone"}

    # какие товары попадают в выборку и в какую группу
    def group_of(product: Product) -> tuple[str, str] | None:
        category = categories.get(product.category_id) if product.category_id else None
        top = _top_of(category, categories)
        if sub_id is not None:
            if product.category_id != sub_id:
                return None
            return f"p{product.id}", product.name
        if top_id is not None:
            if top is None or top.id != top_id:
                return None
            if category is not None and category.parent_id:
                return f"c{category.id}", category.name
            return "direct", "Без подкатегории"
        if top is None:
            return "none", NO_CATEGORY
        return f"c{top.id}", top.name

    chosen: dict[int, tuple[str, str]] = {}
    for product in products.values():
        group = group_of(product)
        if group is not None:
            chosen[product.id] = group

    # заготовки групп в порядке дерева категорий, чтобы пустые тоже были видны
    kind, buckets = _buckets(start, end)
    groups: dict[str, dict[str, Any]] = {}

    def ensure(key: str, name: str) -> dict[str, Any]:
        if key not in groups:
            groups[key] = {
                "key": key, "name": name, "products": 0, "on_hand": 0.0, "low": 0,
                "received": 0.0, "issued": 0.0, "issues": 0, "series": [0.0] * len(buckets),
            }
        return groups[key]

    tree = sorted(categories.values(), key=lambda c: c.position)
    if sub_id is None and top_id is not None:
        for child in (c for c in tree if c.parent_id == top_id):
            ensure(f"c{child.id}", child.name)
    elif sub_id is None and top_id is None:
        for top in (c for c in tree if c.parent_id is None):
            ensure(f"c{top.id}", top.name)

    # остатки
    on_hand: dict[int, float] = defaultdict(float)
    shelves: dict[int, set[int]] = defaultdict(set)
    for (product_id, location_id), quantity in data["balances"].items():
        if product_id in chosen and quantity > 0:
            on_hand[product_id] += quantity
            if location_id not in zone_ids:
                shelves[location_id].add(product_id)
    waiting = {
        product_id for (product_id, location_id), quantity in data["balances"].items()
        if product_id in chosen and quantity > 0 and location_id in zone_ids
    }

    low_products = []
    for product_id, (key, name) in chosen.items():
        quantity = on_hand.get(product_id, 0.0)
        if quantity <= 0:
            continue
        product = products[product_id]
        group = ensure(key, name)
        group["products"] += 1
        group["on_hand"] += quantity
        if product.min_stock is not None and quantity < product.min_stock:
            group["low"] += 1
            low_products.append({
                "product_id": product_id, "name": product.name, "unit": product.unit,
                "quantity": quantity, "min_stock": product.min_stock,
            })

    # движения за период
    received_units = issued_units = 0.0
    received_ops = issued_ops = 0
    series_in = [0.0] * len(buckets)
    series_out = [0.0] * len(buckets)
    recipients: dict[str, dict[str, Any]] = {}
    history = []
    for movement in data["movements"]:
        if movement.product_id not in chosen:
            continue
        when = _local(movement.created_at)
        if when is None or not (start <= when.date() <= end):
            continue
        key, name = chosen[movement.product_id]
        group = ensure(key, name)
        index = _bucket_index(buckets, when.date())
        quantity = float(movement.quantity or 0)
        if movement.kind == "in":
            received_units += quantity
            received_ops += 1
            group["received"] += quantity
            if index is not None:
                series_in[index] += quantity
        elif movement.kind == "out":
            issued_units += quantity
            issued_ops += 1
            group["issued"] += quantity
            group["issues"] += 1
            if index is not None:
                series_out[index] += quantity
                group["series"][index] += quantity
            recipient = _recipient_key(movement)
            if recipient:
                employee = data["employees"].get(movement.recipient_employee_id)
                row = recipients.setdefault(recipient, {
                    "key": recipient,
                    "employee_id": movement.recipient_employee_id,
                    "name": employee.full_name if employee else movement.recipient_name,
                    "department": employee.department if employee else "",
                    "issues": 0, "units": 0.0,
                })
                row["issues"] += 1
                row["units"] += quantity
        history.append(movement)

    product_paths = {pid: _category_path(categories.get(p.category_id), categories)["path"]
                     for pid, p in products.items()}

    def history_row(movement: Movement) -> dict[str, Any]:
        product = products.get(movement.product_id)
        source = locations.get(movement.from_location_id)
        target = locations.get(movement.to_location_id)
        employee = data["employees"].get(movement.recipient_employee_id)
        return {
            "id": movement.id,
            "kind": movement.kind,
            "quantity": movement.quantity,
            "name": product.name if product else "",
            "unit": product.unit if product else "",
            "path": product_paths.get(movement.product_id, ""),
            "from_code": source.code if source else "",
            "to_code": target.code if target else "",
            "actor_name": movement.actor_name,
            "recipient_name": employee.full_name if employee else movement.recipient_name,
            "note": movement.note,
            "created_at": _local(movement.created_at).strftime("%d.%m.%Y %H:%M"),
        }

    # полки: где лежит фактически и какие назначены под эти категории
    category_ids: set[int] = set()
    if sub_id is not None:
        category_ids = {sub_id}
    elif top_id is not None:
        category_ids = {top_id} | {c.id for c in categories.values() if c.parent_id == top_id}
    purposes: dict[int, list[int]] = defaultdict(list)
    for link in data["links"]:
        purposes[link.location_id].append(link.category_id)
    shelf_rows = []
    for location in sorted(locations.values(), key=lambda l: l.code):
        if location.kind == "zone" or not location.active:
            continue
        assigned = bool(category_ids & set(purposes.get(location.id, [])))
        if not shelves.get(location.id) and not assigned:
            continue
        parent = locations.get(location.parent_id) if location.parent_id else None
        shelf_rows.append({
            "id": location.id,
            "code": location.code,
            "name": location.name,
            "kind": location.kind,
            "parent_code": parent.code if parent else "",
            "products": len(shelves.get(location.id, ())),
            "assigned": assigned,
        })

    ordered = list(groups.values())
    if sub_id is not None:
        ordered.sort(key=lambda g: (-g["on_hand"], g["name"]))
    top_recipients = sorted(recipients.values(), key=lambda r: (-r["issues"], -r["units"], r["name"]))

    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "step": kind},
        "level": "products" if sub_id is not None else "subcategories" if top_id is not None else "categories",
        "totals": {
            "products": sum(1 for q in on_hand.values() if q > 0),
            "units": sum(on_hand.values()),
            "low": len(low_products),
            "waiting": len(waiting),
            "received_units": received_units,
            "received_ops": received_ops,
            "issued_units": issued_units,
            "issued_ops": issued_ops,
            "recipients": len(recipients),
        },
        "labels": [label for _, _, label in buckets],
        "series_in": series_in,
        "series_out": series_out,
        "groups": ordered,
        "recipients": top_recipients[:10],
        "low_products": sorted(low_products, key=lambda r: r["quantity"] / (r["min_stock"] or 1)),
        "shelves": shelf_rows,
        "history": [history_row(m) for m in reversed(history[-80:])],
    }


async def recipients_list() -> list[dict[str, Any]]:
    """Все, кому что-то выдавали, и все сотрудники — для выбора в дашборде."""
    async with Session() as session:
        data = await _load(session)
    counts: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for movement in data["movements"]:
        if movement.kind != "out":
            continue
        key = _recipient_key(movement)
        if key:
            counts[key] += 1
            names.setdefault(key, movement.recipient_name)
    rows = []
    for employee in data["employees"].values():
        if not employee.active and not counts.get(f"e{employee.id}"):
            continue
        rows.append({
            "key": f"e{employee.id}", "employee_id": employee.id, "name": employee.full_name,
            "department": employee.department, "issues": counts.get(f"e{employee.id}", 0),
        })
    known = {employee.full_name.strip().lower() for employee in data["employees"].values()}
    for key, issues in counts.items():
        if key.startswith("n") and key[1:] not in known:
            rows.append({"key": key, "employee_id": None, "name": names[key], "department": "", "issues": issues})
    rows.sort(key=lambda r: (-r["issues"], r["name"]))
    return rows


async def recipient_report(key: str, start: date, end: date) -> dict[str, Any] | None:
    """Что забирал конкретный человек: итоги, по категориям, по товарам и история."""
    async with Session() as session:
        data = await _load(session)
    employee = None
    if key.startswith("e") and key[1:].isdigit():
        employee = data["employees"].get(int(key[1:]))
        if employee is None:
            return None
    elif not key.startswith("n") or len(key) < 2:
        return None
    name_key = employee.full_name.strip().lower() if employee else key[1:]

    def matches(movement: Movement) -> bool:
        if movement.kind != "out":
            return False
        if employee is not None and movement.recipient_employee_id == employee.id:
            return True
        # выдачи, где человека вписали вручную, тоже считаем его
        return not movement.recipient_employee_id and (movement.recipient_name or "").strip().lower() == name_key

    categories = data["categories"]
    products = data["products"]
    locations = data["locations"]
    by_category: dict[str, float] = defaultdict(float)
    by_product: dict[int, dict[str, Any]] = {}
    history = []
    units = 0.0
    display_name = employee.full_name if employee else ""
    for movement in data["movements"]:
        if not matches(movement):
            continue
        when = _local(movement.created_at)
        if when is None or not (start <= when.date() <= end):
            continue
        display_name = display_name or movement.recipient_name
        product = products.get(movement.product_id)
        category = categories.get(product.category_id) if product and product.category_id else None
        top = _top_of(category, categories)
        quantity = float(movement.quantity or 0)
        units += quantity
        by_category[top.name if top else NO_CATEGORY] += quantity
        row = by_product.setdefault(movement.product_id, {
            "product_id": movement.product_id, "name": product.name if product else "",
            "unit": product.unit if product else "", "units": 0.0, "issues": 0,
        })
        row["units"] += quantity
        row["issues"] += 1
        source = locations.get(movement.from_location_id)
        history.append({
            "id": movement.id,
            "name": product.name if product else "",
            "unit": product.unit if product else "",
            "quantity": quantity,
            "path": _category_path(category, categories)["path"],
            "from_code": source.code if source else "",
            "actor_name": movement.actor_name,
            "note": movement.note,
            "created_at": when.strftime("%d.%m.%Y %H:%M"),
        })
    return {
        "key": key,
        "name": display_name or key[1:],
        "department": employee.department if employee else "",
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "issues": len(history),
        "units": units,
        "by_category": sorted(
            ({"name": name, "units": value} for name, value in by_category.items()),
            key=lambda r: -r["units"],
        ),
        "top_products": sorted(by_product.values(), key=lambda r: (-r["issues"], -r["units"]))[:10],
        "history": list(reversed(history))[:200],
    }

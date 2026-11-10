"""Досоздание колонок в уже существующих таблицах.

`Base.metadata.create_all` умеет создавать таблицы, но не умеет добавлять
колонки в те, что уже есть. Поэтому новые поля добавляются здесь — по одному,
с проверкой, что их ещё нет. Повторные запуски безопасны.
"""

import logging
import re

from sqlalchemy import inspect, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from core.quantities import parse_quantity

log = logging.getLogger(__name__)

#: имя колонки -> определение для ALTER TABLE
ITEM_COLUMNS = {
    "qty_number": "FLOAT",
    "qty_unit": "VARCHAR(30) DEFAULT ''",
    "product_id": "INTEGER REFERENCES products(id)",
    "stock_code": "VARCHAR(40)",
    "received_done": "BOOLEAN DEFAULT {false}",
    "issued_done": "BOOLEAN DEFAULT {false}",
}
REQUEST_COLUMNS = {
    "arrived_notified": "BOOLEAN DEFAULT {false}",
}
PRODUCT_COLUMNS = {
    "category_id": "INTEGER REFERENCES categories(id)",
    "category_manual": "BOOLEAN DEFAULT {false}",
    "serialized": "BOOLEAN",
    "min_stock": "FLOAT",
}
MOVEMENT_COLUMNS = {
    "from_location_id": "INTEGER REFERENCES locations(id)",
    "to_location_id": "INTEGER REFERENCES locations(id)",
    "instance_id": "INTEGER REFERENCES instances(id)",
}

#: служебная зона, куда попадает всё принятое до размещения по полкам
RECEIVING_ZONE_CODE = "ZONE-IN"


async def ensure_columns(conn: AsyncConnection, table: str, columns: dict[str, str]) -> list[str]:
    """Добавляет недостающие колонки. Возвращает список добавленных."""
    false_literal = "FALSE" if conn.dialect.name != "sqlite" else "0"

    def _existing(sync_conn) -> set[str]:
        inspector = inspect(sync_conn)
        if table not in inspector.get_table_names():
            return set()
        return {column["name"] for column in inspector.get_columns(table)}

    existing = await conn.run_sync(_existing)
    if not existing:
        return []

    added: list[str] = []
    for name, ddl in columns.items():
        if name in existing:
            continue
        await conn.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN {name} {ddl.format(false=false_literal)}"
        )
        added.append(name)
    return added


async def rebuild_movements(conn: AsyncConnection) -> bool:
    """Делает movements.item_id необязательным.

    Нужно для движений не по заявке: инвентаризация, перемещение между полками.
    SQLite не умеет снимать NOT NULL с колонки, поэтому таблица пересобирается:
    старая переименовывается, создаётся новая по текущей модели, данные
    переливаются. Запускается только если колонка ещё обязательная.
    """
    from db.models import Movement  # локальный импорт: модели импортируют migrate

    if conn.dialect.name != "sqlite":
        def _alter(sync_conn):
            columns = {c["name"]: c for c in inspect(sync_conn).get_columns("movements")}
            if columns.get("item_id", {}).get("nullable") is False:
                sync_conn.exec_driver_sql("ALTER TABLE movements ALTER COLUMN item_id DROP NOT NULL")
                return True
            return False
        return await conn.run_sync(_alter)

    rows = (await conn.exec_driver_sql("PRAGMA table_info(movements)")).all()
    if not rows:
        return False
    item_column = next((row for row in rows if row[1] == "item_id"), None)
    if item_column is None or not item_column[3]:   # row[3] — notnull
        return False

    old_columns = [row[1] for row in rows]
    await conn.exec_driver_sql("ALTER TABLE movements RENAME TO movements__old")
    # индексы при переименовании остаются со старыми именами — убираем,
    # иначе новая таблица не сможет создать свои
    indexes = (
        await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='movements__old' AND name NOT LIKE 'sqlite_%'"
        )
    ).all()
    for (name,) in indexes:
        await conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{name}"')

    await conn.run_sync(lambda sync_conn: Movement.__table__.create(sync_conn))
    new_columns = {column.name for column in Movement.__table__.columns}
    common = [name for name in old_columns if name in new_columns]
    column_list = ", ".join(common)
    await conn.exec_driver_sql(
        f"INSERT INTO movements ({column_list}) SELECT {column_list} FROM movements__old"
    )
    await conn.exec_driver_sql("DROP TABLE movements__old")
    return True


async def run(conn: AsyncConnection) -> None:
    """Все доработки схемы, которые нужны поверх create_all."""
    added = await ensure_columns(conn, "items", ITEM_COLUMNS)
    added += await ensure_columns(conn, "requests", REQUEST_COLUMNS)
    added += await ensure_columns(conn, "products", PRODUCT_COLUMNS)
    if await rebuild_movements(conn):
        log.info("Таблица движений перестроена: движения теперь бывают не по заявке")
    added += await ensure_columns(conn, "movements", MOVEMENT_COLUMNS)
    if added:
        log.info("Добавлены колонки: %s", ", ".join(added))


async def backfill(session) -> None:
    """Заполняет новые поля у старых записей: числа количеств и складские коды."""
    from db.models import Item, Request  # локальный импорт: избегаем круговой зависимости

    items = (await session.execute(select(Item))).scalars().all()
    changed_qty = 0
    changed_code = 0
    for item in items:
        if item.qty_number is None and (item.quantity or "").strip():
            number, unit = parse_quantity(item.quantity)
            if number is not None:
                item.qty_number = number
                item.qty_unit = unit
                changed_qty += 1
        if not item.stock_code:
            item.stock_code = make_stock_code(item.request_id, item.position)
            changed_code += 1
    if changed_qty or changed_code:
        await session.commit()
        log.info(
            "Заполнено: количеств числом %s, складских кодов %s", changed_qty, changed_code
        )


URL_IN_TEXT_RE = re.compile(r"\s*https?://\S+")


def split_link(name: str) -> tuple[str, str | None]:
    """«Хлорка… https://ozon.ru/t/x» -> («Хлорка…», «https://ozon.ru/t/x»)."""
    match = re.search(r"https?://\S+", name or "")
    if not match:
        return name, None
    link = match.group(0).rstrip(".,;)")
    cleaned = URL_IN_TEXT_RE.sub(" ", name).strip(" ,;-–—")
    return re.sub(r"\s{2,}", " ", cleaned) or name, link


async def seed_catalog(session) -> None:
    """Категории из стартового словаря и служебная зона приёмки — один раз."""
    from core.categories import SEED
    from db.models import Category, Location

    if (await session.execute(select(Category.id).limit(1))).first() is None:
        for top_index, (name, serialized, subs) in enumerate(SEED, start=1):
            parent = Category(name=name, position=top_index, serialized=serialized)
            session.add(parent)
            await session.flush()
            for sub_index, (sub_name, sub_serialized, keywords) in enumerate(subs, start=1):
                session.add(
                    Category(
                        name=sub_name,
                        parent_id=parent.id,
                        position=sub_index,
                        serialized=sub_serialized,
                        keywords=keywords,
                    )
                )
        await session.commit()
        log.info("Заведён справочник категорий: %s разделов", len(SEED))

    zone = (
        await session.execute(select(Location).where(Location.code == RECEIVING_ZONE_CODE))
    ).scalar_one_or_none()
    if zone is None:
        session.add(Location(kind="zone", code=RECEIVING_ZONE_CODE, name="Зона приёмки"))
        await session.commit()


async def backfill_locations(session) -> None:
    """Старые приходы и выдачи считаем прошедшими через зону приёмки."""
    from db.models import Location, Movement

    zone = (
        await session.execute(select(Location).where(Location.code == RECEIVING_ZONE_CODE))
    ).scalar_one()
    moved = 0
    for movement in (
        await session.execute(
            select(Movement).where(
                or_(
                    (Movement.kind == "in") & Movement.to_location_id.is_(None),
                    (Movement.kind == "out") & Movement.from_location_id.is_(None),
                )
            )
        )
    ).scalars():
        if movement.kind == "in":
            movement.to_location_id = zone.id
        else:
            movement.from_location_id = zone.id
        moved += 1
    if moved:
        await session.commit()
        log.info("Старые движения привязаны к зоне приёмки: %s", moved)


async def normalize_shelf_purposes(session) -> None:
    """Полка теперь целиком под раздел: подкатегории в её назначении меняем на их раздел."""
    from db.models import Category, Location, LocationCategory

    categories = {c.id: c for c in (await session.execute(select(Category))).scalars().all()}
    shelves = {l.id for l in (await session.execute(select(Location).where(Location.kind == "shelf"))).scalars().all()}
    links = (await session.execute(select(LocationCategory))).scalars().all()
    existing = {(link.location_id, link.category_id) for link in links}
    changed = 0
    for link in links:
        if link.location_id not in shelves:
            continue
        category = categories.get(link.category_id)
        if category is None or category.parent_id is None:
            continue
        top = (link.location_id, category.parent_id)
        if top in existing:
            await session.delete(link)
        else:
            link.category_id = category.parent_id
            existing.add(top)
        changed += 1
    if changed:
        await session.commit()
        log.info("Назначения полок переведены на разделы: %s", changed)


async def backfill_links(session) -> None:
    """Вынимает ссылки, застрявшие в названиях позиций, в отдельное поле."""
    from db.models import Item, Request

    fixed = 0
    for item in (
        await session.execute(select(Item).where(Item.name.like("%http%")))
    ).scalars():
        name, link = split_link(item.name)
        if link is None:
            continue
        item.name = name
        if not item.link:
            item.link = link
        if item.position == 1:
            request = await session.get(Request, item.request_id)
            if request is not None:
                request.item = name
        fixed += 1
    if fixed:
        await session.commit()
        log.info("Ссылки вынесены из названий позиций: %s", fixed)
    await _clean_product_names(session)


async def _clean_product_names(session) -> None:
    """Убирает ссылки из названий товаров в справочнике.

    Если после чистки название совпало с уже существующим товаром — это один
    и тот же товар: переносим на него позиции, движения и экземпляры, а
    дубликат удаляем.
    """
    from core.quantities import normalize_name
    from db.models import Instance, Item, Movement, Product

    cleaned = merged = 0
    for product in (
        await session.execute(select(Product).where(Product.name.like("%http%")))
    ).scalars().all():
        name, link = split_link(product.name)
        if link is None:
            continue
        key = normalize_name(name)
        twin = (
            await session.execute(
                select(Product).where(Product.norm_name == key, Product.id != product.id)
            )
        ).scalar_one_or_none()
        if twin is None:
            product.name = name
            product.norm_name = key
            cleaned += 1
            continue
        for model in (Item, Movement, Instance):
            for row in (
                await session.execute(select(model).where(model.product_id == product.id))
            ).scalars():
                row.product_id = twin.id
        await session.delete(product)
        merged += 1
    if cleaned or merged:
        await session.commit()
        log.info("Названия товаров очищены от ссылок: %s, объединено дублей: %s", cleaned, merged)


def make_stock_code(request_id: int, position: int) -> str:
    """Складской номер позиции: ZK-12-03 — заявка 12, позиция 3.

    Только латиница и цифры: такой код легко набрать руками, если наклейка
    затёрлась и QR не читается.
    """
    return f"ZK-{request_id}-{position:02d}"

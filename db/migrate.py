"""Досоздание колонок в уже существующих таблицах.

`Base.metadata.create_all` умеет создавать таблицы, но не умеет добавлять
колонки в те, что уже есть. Поэтому новые поля добавляются здесь — по одному,
с проверкой, что их ещё нет. Повторные запуски безопасны.
"""

import logging

from sqlalchemy import inspect, select, text
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


async def run(conn: AsyncConnection) -> None:
    """Все доработки схемы, которые нужны поверх create_all."""
    added = await ensure_columns(conn, "items", ITEM_COLUMNS)
    added += await ensure_columns(conn, "requests", REQUEST_COLUMNS)
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


def make_stock_code(request_id: int, position: int) -> str:
    """Складской номер позиции: ZK-12-03 — заявка 12, позиция 3.

    Только латиница и цифры: такой код легко набрать руками, если наклейка
    затёрлась и QR не читается.
    """
    return f"ZK-{request_id}-{position:02d}"

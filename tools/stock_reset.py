"""Очистка склада: убрать со склада всё, кроме нескольких товаров.

Сначала показывает план, ничего не меняя:

    python -m tools.stock_reset --keep "Стиральная машина" --keep "Хлорка"

Выполнить план:

    python -m tools.stock_reset --keep "Стиральная машина" --keep "Хлорка" --apply

--keep — часть названия товара (регистр не важен); товары, которые подходят,
остаются как есть. С остальными товарами:

- удаляются их движения (приход, перемещения, выдачи) и инвентарные номера;
- принятые позиции заявок возвращаются в «Ждём поставку» — их можно принять заново;
- товары, заведённые без заявки, удаляются из справочника.

Заявки, их статусы, полки, коробки и сотрудники не трогаются.
Перед --apply сделайте копию папки data.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import delete, select

from db.models import Instance, Item, Movement, Product, Request
from db.session import Session


async def reset_stock(keep: list[str], apply: bool = False) -> dict[str, Any]:
    patterns = [p.strip().lower() for p in keep if p.strip()]
    async with Session() as session:
        products = (await session.execute(select(Product))).scalars().all()
        movements = (await session.execute(select(Movement))).scalars().all()
        instances = (await session.execute(select(Instance))).scalars().all()
        items = (await session.execute(select(Item))).scalars().all()

        unmatched = [p for p in patterns if not any(p in product.name.lower() for product in products)]
        keep_ids = {product.id for product in products if any(p in product.name.lower() for p in patterns)}

        touched = {m.product_id for m in movements} | {i.product_id for i in instances}
        drop_ids = {pid for pid in touched if pid is not None and pid not in keep_ids}
        with_items = {item.product_id for item in items if item.product_id is not None}
        orphan_ids = {pid for pid in drop_ids if pid not in with_items}

        revert = [item for item in items if item.product_id in drop_ids and (item.received_done or item.issued_done)]
        names = {product.id: product.name for product in products}
        plan = {
            "unmatched": unmatched,
            "keep": sorted(names[pid] for pid in keep_ids),
            "drop": sorted(
                (names.get(pid, "?"),
                 sum(1 for m in movements if m.product_id == pid),
                 sum(1 for i in instances if i.product_id == pid))
                for pid in drop_ids
            ),
            "revert_items": [(item.request_id, item.name) for item in revert],
            "orphans": sorted(names.get(pid, "?") for pid in orphan_ids),
            "applied": False,
        }
        if not apply or unmatched:
            return plan

        await session.execute(delete(Movement).where(Movement.product_id.in_(drop_ids)))
        await session.execute(delete(Instance).where(Instance.product_id.in_(drop_ids)))
        request_ids = set()
        for item in revert:
            item.received_done = False
            item.issued_done = False
            request_ids.add(item.request_id)
        for request_id in request_ids:
            request = await session.get(Request, request_id)
            if request is not None:
                # чтобы при настоящем приходе заказчик снова получил сообщение
                request.arrived_notified = False
        await session.execute(delete(Product).where(Product.id.in_(orphan_ids)))
        await session.commit()
        plan["applied"] = True
        return plan


def _print(plan: dict[str, Any]) -> None:
    if plan["unmatched"]:
        print("Не нашёл товаров по запросу:", ", ".join(plan["unmatched"]))
        print("Ничего не изменено. Проверьте названия в разделе «Товары».")
        return
    print("Остаются на складе:")
    for name in plan["keep"] or ["— ничего —"]:
        print("  +", name)
    print("Убираются со склада (движений / инвентарных номеров):")
    for name, moves, codes in plan["drop"] or [("— ничего —", 0, 0)]:
        print(f"  - {name}  ({moves} / {codes})")
    if plan["revert_items"]:
        print("Вернутся в «Ждём поставку»:")
        for request_id, name in plan["revert_items"]:
            print(f"  заявка №{request_id}: {name}")
    if plan["orphans"]:
        print("Удаляются из справочника (принимались без заявки):")
        for name in plan["orphans"]:
            print("  x", name)
    print()
    print("Готово, изменения сохранены." if plan["applied"] else "Это только план. Чтобы выполнить, добавьте --apply")


def main() -> None:
    parser = argparse.ArgumentParser(description="Очистка склада, кроме выбранных товаров")
    parser.add_argument("--keep", action="append", default=[], help="часть названия товара, который оставить")
    parser.add_argument("--apply", action="store_true", help="выполнить, а не только показать план")
    args = parser.parse_args()
    _print(asyncio.run(reset_stock(args.keep, args.apply)))


if __name__ == "__main__":
    main()

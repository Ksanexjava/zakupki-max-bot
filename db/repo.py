"""Доступ к данным: заявки, история, админы. Всё остальное работает через эти функции."""

from typing import Any, Sequence

from sqlalchemy import func, inspect as sa_inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.statuses import DEFAULT_STATUS
from core.quantities import normalize_name, parse_quantity
from db.migrate import make_stock_code
from db.models import (
    Admin,
    Attachment,
    Employee,
    Item,
    Movement,
    Product,
    Request,
    StatusHistory,
    utcnow,
)
from db.session import Session

# ------------------------------------------------------------------ заявки

FORM_FIELDS = (
    "requester", "item", "quantity", "deadline", "purpose",
    "example_url", "photo_token", "photo_file",
    "author_user_id", "author_name", "author_username", "author_chat_id",
)


def normalize_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Приводит позиции к единому виду.

    Заявка может прийти со списком `items`, а может — в старом формате,
    где товар лежал прямо в полях заявки. Второй вариант превращаем
    в список из одной позиции.
    """
    raw = data.get("items")
    if not raw:
        raw = [
            {
                "name": data.get("item") or "",
                "quantity": data.get("quantity") or "",
                "link": data.get("example_url"),
                "photo_token": data.get("photo_token"),
                "photo_file": data.get("photo_file"),
            }
        ]
    items: list[dict[str, Any]] = []
    for number, item in enumerate(raw, start=1):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        quantity = (item.get("quantity") or "").strip()
        qty_number, qty_unit = parse_quantity(quantity)
        items.append(
            {
                "position": number,
                "name": name,
                "quantity": quantity,
                "qty_number": qty_number,
                "qty_unit": qty_unit,
                "link": item.get("link") or None,
                "photo_token": item.get("photo_token"),
                "photo_file": item.get("photo_file"),
            }
        )
    return items


async def create_request(data: dict[str, Any]) -> Request:
    """Создаёт заявку со статусом «Не просмотрено» и первой записью в истории."""
    payload = {key: data.get(key) for key in FORM_FIELDS}
    for key in ("quantity", "deadline", "purpose"):
        payload[key] = payload.get(key) or ""

    items = normalize_items(data)
    if items:
        # заголовок заявки — первая позиция
        payload["item"] = items[0]["name"]
        payload["quantity"] = items[0]["quantity"]
        if len(items) == 1:
            payload["example_url"] = items[0]["link"]
            payload["photo_token"] = items[0]["photo_token"]
            payload["photo_file"] = items[0]["photo_file"]

    async with Session() as session:
        request = Request(**payload, status=DEFAULT_STATUS)
        for item in items:
            request.items.append(Item(**item))
        request.history.append(
            StatusHistory(
                actor=data.get("author_name") or "бот",
                from_status=None,
                to_status=DEFAULT_STATUS,
                comment="Заявка создана",
            )
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)
        for item in request.items:
            item.stock_code = make_stock_code(request.id, item.position)
        await session.commit()
        await session.refresh(request)
        return request


async def get_request(request_id: int) -> Request | None:
    async with Session() as session:
        return await session.get(Request, request_id)


async def list_requests(
    status: str | None = None,
    query: str | None = None,
    author_user_id: int | None = None,
    limit: int = 500,
) -> Sequence[Request]:
    stmt = select(Request).order_by(Request.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(Request.status == status)
    if author_user_id is not None:
        stmt = stmt.where(Request.author_user_id == author_user_id)
    if query:
        like = f"%{query}%"
        conditions = [
            Request.item.ilike(like),
            Request.requester.ilike(like),
            Request.purpose.ilike(like),
            Request.author_name.ilike(like),
            # ищем и по названиям позиций внутри заявки
            Request.id.in_(select(Item.request_id).where(Item.name.ilike(like))),
        ]
        if query.isdigit():
            conditions.append(Request.id == int(query))
        stmt = stmt.where(or_(*conditions))
    async with Session() as session:
        return (await session.execute(stmt)).scalars().all()


async def set_status(
    request_id: int,
    status: str,
    actor: str,
    comment: str | None = None,
) -> tuple[Request, str] | None:
    """Меняет статус. Возвращает (заявка, прежний статус) или None, если заявки нет."""
    async with Session() as session:
        request = await session.get(Request, request_id)
        if request is None:
            return None
        previous = request.status
        request.status = status
        request.updated_at = utcnow()
        if comment:
            request.admin_comment = comment
        session.add(
            StatusHistory(
                request_id=request.id,
                actor=actor,
                from_status=previous,
                to_status=status,
                comment=comment,
            )
        )
        await session.commit()
        await session.refresh(request)
        return request, previous


async def add_comment(request_id: int, actor: str, comment: str) -> Request | None:
    async with Session() as session:
        request = await session.get(Request, request_id)
        if request is None:
            return None
        request.admin_comment = comment
        request.updated_at = utcnow()
        session.add(StatusHistory(request_id=request.id, actor=actor, comment=comment))
        await session.commit()
        await session.refresh(request)
        return request


async def delete_request(request_id: int) -> dict[str, Any] | None:
    """Удаляет заявку с историей и вложениями.

    Возвращает её данные плюс `files` — имена файлов, которые надо стереть с диска.
    """
    async with Session() as session:
        request = await session.get(Request, request_id)
        if request is None:
            return None
        data = to_dict(request)
        data["files"] = [item.filename for item in request.attachments]
        data["files"] += [item.photo_file for item in request.items if item.photo_file]
        if request.photo_file:
            data["files"].append(request.photo_file)
        await session.delete(request)
        await session.commit()
        return data


async def history(request_id: int) -> Sequence[StatusHistory]:
    stmt = select(StatusHistory).where(StatusHistory.request_id == request_id).order_by(StatusHistory.id)
    async with Session() as session:
        return (await session.execute(stmt)).scalars().all()


async def counts_by_status() -> dict[str, int]:
    stmt = select(Request.status, func.count()).group_by(Request.status)
    async with Session() as session:
        return {status: count for status, count in (await session.execute(stmt)).all()}


# ------------------------------------------------------------------ админы

async def add_admin(user_id: int, name: str | None) -> bool:
    """True — админ добавлен впервые, False — уже был."""
    async with Session() as session:
        existing = await session.get(Admin, user_id)
        if existing:
            existing.name = name
            await session.commit()
            return False
        session.add(Admin(user_id=user_id, name=name))
        await session.commit()
        return True


async def remove_admin(user_id: int) -> None:
    async with Session() as session:
        admin = await session.get(Admin, user_id)
        if admin:
            await session.delete(admin)
            await session.commit()


async def admin_ids() -> list[int]:
    stmt = select(Admin.user_id).order_by(Admin.added_at)
    async with Session() as session:
        return list((await session.execute(stmt)).scalars().all())


async def is_admin(user_id: int, extra: Sequence[int] = ()) -> bool:
    if user_id in set(extra):
        return True
    async with Session() as session:
        return await session.get(Admin, user_id) is not None


# -------------------------------------------------- сериализация для панели

def item_to_dict(item: Item) -> dict[str, Any]:
    unloaded = sa_inspect(item).unloaded
    movements = [] if "movements" in unloaded else item.movements
    received = sum(m.quantity for m in movements if m.kind == "in")
    issued = sum(m.quantity for m in movements if m.kind == "out")
    return {
        "id": item.id,
        "position": item.position,
        "name": item.name,
        "quantity": item.quantity,
        "qty_number": item.qty_number,
        "qty_unit": item.qty_unit,
        "link": item.link,
        "photo_file": item.photo_file,
        "photo_url": f"/media/{item.photo_file}" if item.photo_file else None,
        "bought": bool(item.bought),
        "stock_code": item.stock_code,
        "product_id": item.product_id,
        "received": received,
        "issued": issued,
        "on_hand": received - issued,
        "received_done": bool(item.received_done),
        "issued_done": bool(item.issued_done),
    }


def to_dict(request: Request) -> dict[str, Any]:
    """Заявка в виде обычного словаря — для JSON панели и текстов бота."""
    # связи могут быть ещё не подгружены (например, сразу после создания)
    unloaded = sa_inspect(request).unloaded
    attachments_count = 0 if "attachments" in unloaded else len(request.attachments)
    items = [] if "items" in unloaded else [item_to_dict(i) for i in request.items]
    return {
        "attachments_count": attachments_count,
        "items": items,
        "items_count": len(items),
        "bought_count": sum(1 for i in items if i["bought"]),
        "id": request.id,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
        "status": request.status,
        "requester": request.requester,
        "item": request.item,
        "quantity": request.quantity,
        "deadline": request.deadline,
        "purpose": request.purpose,
        "example_url": request.example_url,
        "photo_token": request.photo_token,
        "photo_file": request.photo_file,
        "author_user_id": request.author_user_id,
        "author_name": request.author_name,
        "author_username": request.author_username,
        "author_chat_id": request.author_chat_id,
        "admin_comment": request.admin_comment,
    }


def history_to_dict(item: StatusHistory) -> dict[str, Any]:
    return {
        "id": item.id,
        "at": item.at,
        "actor": item.actor,
        "from_status": item.from_status,
        "to_status": item.to_status,
        "comment": item.comment,
    }


# ------------------------------------------------------------- вложения

async def add_attachment(
    request_id: int,
    filename: str,
    original_name: str | None,
    uploaded_by: str,
) -> dict[str, Any] | None:
    async with Session() as session:
        if await session.get(Request, request_id) is None:
            return None
        item = Attachment(
            request_id=request_id,
            filename=filename,
            original_name=original_name,
            uploaded_by=uploaded_by,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return attachment_to_dict(item)


async def list_attachments(request_id: int) -> list[dict[str, Any]]:
    stmt = select(Attachment).where(Attachment.request_id == request_id).order_by(Attachment.id)
    async with Session() as session:
        rows = (await session.execute(stmt)).scalars().all()
        return [attachment_to_dict(item) for item in rows]


async def delete_attachment(attachment_id: int) -> dict[str, Any] | None:
    async with Session() as session:
        item = await session.get(Attachment, attachment_id)
        if item is None:
            return None
        data = attachment_to_dict(item)
        await session.delete(item)
        await session.commit()
        return data


def attachment_to_dict(item: Attachment) -> dict[str, Any]:
    return {
        "id": item.id,
        "request_id": item.request_id,
        "filename": item.filename,
        "original_name": item.original_name,
        "uploaded_by": item.uploaded_by,
        "uploaded_at": item.uploaded_at,
        "url": f"/media/{item.filename}",
    }


# ------------------------------------------------------------- позиции

async def set_item_bought(item_id: int, bought: bool) -> dict[str, Any] | None:
    """Отмечает позицию купленной (или снимает отметку). Статус заявки не трогает."""
    async with Session() as session:
        item = await session.get(Item, item_id)
        if item is None:
            return None
        item.bought = bought
        item.bought_at = utcnow() if bought else None
        await session.commit()
        await session.refresh(item)
        return {**item_to_dict(item), "request_id": item.request_id}


# --------------------------------------------------- массовые операции

async def bulk_set_status(
    request_ids: Sequence[int],
    status: str,
    actor: str,
    comment: str | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """Меняет статус у нескольких заявок за один заход.

    Возвращает список пар (заявка после изменения, прежний статус) —
    только для тех, где статус действительно поменялся или добавлен комментарий.
    """
    changed: list[tuple[dict[str, Any], str]] = []
    if not request_ids:
        return changed
    async with Session() as session:
        found = (
            await session.execute(select(Request).where(Request.id.in_(list(request_ids))))
        ).scalars().all()
        for request in found:
            previous = request.status
            if previous == status and not comment:
                continue
            request.status = status
            request.updated_at = utcnow()
            if comment:
                request.admin_comment = comment
            session.add(
                StatusHistory(
                    request_id=request.id,
                    actor=actor,
                    from_status=previous,
                    to_status=status,
                    comment=comment,
                )
            )
            changed.append((to_dict(request), previous))
        await session.commit()
    return changed


async def bulk_delete(request_ids: Sequence[int]) -> list[dict[str, Any]]:
    """Удаляет несколько заявок. Возвращает их данные (там же список файлов)."""
    deleted: list[dict[str, Any]] = []
    for request_id in request_ids:
        data = await delete_request(request_id)
        if data is not None:
            deleted.append(data)
    return deleted


# ============================================================ СКЛАД

def movement_to_dict(movement: Movement, item: Item | None = None) -> dict[str, Any]:
    data = {
        "id": movement.id,
        "item_id": movement.item_id,
        "kind": movement.kind,
        "quantity": movement.quantity,
        "actor_name": movement.actor_name,
        "recipient_name": movement.recipient_name,
        "note": movement.note,
        "created_at": movement.created_at,
    }
    if item is not None:
        data["item_name"] = item.name
        data["request_id"] = item.request_id
        data["stock_code"] = item.stock_code
    return data


def employee_to_dict(employee: Employee) -> dict[str, Any]:
    return {
        "id": employee.id,
        "full_name": employee.full_name,
        "department": employee.department,
        "is_stock": bool(employee.is_stock),
        "max_user_id": employee.max_user_id,
    }


async def _get_or_create_product(session: AsyncSession, name: str, unit: str) -> Product:
    """Ищет товар по нормализованному названию, при необходимости заводит новый."""
    key = normalize_name(name)
    product = (
        await session.execute(select(Product).where(Product.norm_name == key))
    ).scalar_one_or_none()
    if product is not None:
        return product
    product = Product(name=name.strip(), norm_name=key, unit=unit or "")
    session.add(product)
    await session.flush()
    return product


async def list_employees(only_active: bool = True) -> list[dict[str, Any]]:
    stmt = select(Employee).order_by(Employee.is_stock.desc(), Employee.full_name)
    if only_active:
        stmt = stmt.where(Employee.active.is_(True))
    async with Session() as session:
        rows = (await session.execute(stmt)).scalars().all()
        return [employee_to_dict(row) for row in rows]


async def add_employee(full_name: str, department: str = "", is_stock: bool = False) -> dict[str, Any]:
    """Заводит сотрудника. Если такой уже есть — возвращает его."""
    async with Session() as session:
        existing = (
            await session.execute(select(Employee).where(Employee.full_name == full_name))
        ).scalar_one_or_none()
        if existing is not None:
            if is_stock and not existing.is_stock:
                existing.is_stock = True
                await session.commit()
            return employee_to_dict(existing)
        employee = Employee(full_name=full_name.strip(), department=department.strip(), is_stock=is_stock)
        session.add(employee)
        await session.commit()
        await session.refresh(employee)
        return employee_to_dict(employee)


async def find_item_by_code(code: str) -> dict[str, Any] | None:
    """Поиск позиции по складскому номеру — для сканера и ручного ввода."""
    cleaned = (code or "").strip().upper()
    if not cleaned:
        return None
    async with Session() as session:
        item = (
            await session.execute(select(Item).where(Item.stock_code == cleaned))
        ).scalar_one_or_none()
        if item is None:
            return None
        request = await session.get(Request, item.request_id)
        return {"item": item_to_dict(item), "request": to_dict(request) if request else None}


async def find_item_by_id(item_id: int) -> dict[str, Any] | None:
    """Позиция вместе с номером заявки — нужна для печати наклеек."""
    async with Session() as session:
        item = await session.get(Item, item_id)
        if item is None:
            return None
        return {**item_to_dict(item), "request_id": item.request_id}


async def stock_queue(kind: str = "pending", limit: int = 300) -> list[dict[str, Any]]:
    """Очереди склада.

    pending — отмечено «куплено», но ещё не принято полностью;
    on_hand — принято и не выдано до конца.
    """
    stmt = select(Item).where(Item.bought.is_(True)).order_by(Item.request_id.desc(), Item.position)
    if kind == "pending":
        stmt = stmt.where(Item.received_done.is_(False))
    else:
        stmt = stmt.where(Item.received_done.is_(True), Item.issued_done.is_(False))
    stmt = stmt.limit(limit)

    async with Session() as session:
        items = (await session.execute(stmt)).scalars().all()
        request_ids = {item.request_id for item in items}
        requests = {
            request.id: request
            for request in (
                await session.execute(select(Request).where(Request.id.in_(request_ids)))
            ).scalars().all()
        }
        rows: list[dict[str, Any]] = []
        for item in items:
            request = requests.get(item.request_id)
            rows.append(
                {
                    **item_to_dict(item),
                    "request_id": item.request_id,
                    "requester": request.requester if request else "",
                    "deadline": request.deadline if request else "",
                    "purpose": request.purpose if request else "",
                    "author_name": request.author_name if request else "",
                }
            )
        return rows


async def record_movement(
    item_id: int,
    kind: str,
    quantity: float,
    actor_name: str,
    actor_employee_id: int | None = None,
    recipient_name: str = "",
    recipient_employee_id: int | None = None,
    note: str = "",
    close: bool = False,
) -> dict[str, Any] | None:
    """Проводит приход или выдачу.

    close=True закрывает позицию целиком («принял всё», «выдал всё») — так
    склад может закрыть позицию, даже если количество не было числом.
    """
    if kind not in {"in", "out"}:
        return None

    arrived = completed = False
    request_id: int | None = None
    movement_id: int | None = None

    async with Session() as session:
        item = await session.get(Item, item_id)
        if item is None:
            return None
        request_id = item.request_id

        if item.product_id is None:
            product = await _get_or_create_product(session, item.name, item.qty_unit)
            item.product_id = product.id

        movement = Movement(
            item_id=item.id,
            product_id=item.product_id,
            kind=kind,
            quantity=float(quantity or 0),
            actor_name=actor_name,
            actor_employee_id=actor_employee_id,
            recipient_name=recipient_name,
            recipient_employee_id=recipient_employee_id,
            note=note,
        )
        session.add(movement)
        await session.flush()
        movement_id = movement.id

        # суммы считаем запросом, а не через связь: так не зависим от того,
        # успела ли коллекция позиции обновиться после вставки
        totals = dict(
            (
                await session.execute(
                    select(Movement.kind, func.sum(Movement.quantity))
                    .where(Movement.item_id == item.id)
                    .group_by(Movement.kind)
                )
            ).all()
        )
        received = float(totals.get("in") or 0)
        issued = float(totals.get("out") or 0)
        target = item.qty_number

        if kind == "in":
            item.received_done = bool(close or (target is not None and received >= target))
        else:
            item.issued_done = bool(close or (target is not None and issued >= target))
            if item.issued_done:
                item.received_done = True

        request = await session.get(Request, item.request_id)
        if request is not None:
            siblings = request.items
            if siblings and all(i.received_done for i in siblings):
                arrived = not request.arrived_notified
            if siblings and all(i.issued_done for i in siblings):
                completed = request.status != "done"
                if completed:
                    previous = request.status
                    request.status = "done"
                    request.updated_at = utcnow()
                    session.add(
                        StatusHistory(
                            request_id=request.id,
                            actor=actor_name or "склад",
                            from_status=previous,
                            to_status="done",
                            comment="Все позиции выданы со склада",
                        )
                    )
        await session.commit()

    # читаем результат отдельной сессией — без возни с истёкшими объектами
    fresh_request = await get_request(request_id) if request_id else None
    fresh_item = None
    if fresh_request is not None:
        fresh_item = next((i for i in fresh_request.items if i.id == item_id), None)

    return {
        "movement_id": movement_id,
        "item": item_to_dict(fresh_item) if fresh_item is not None else None,
        "request": to_dict(fresh_request) if fresh_request is not None else None,
        "request_arrived": arrived,
        "request_completed": completed,
    }


async def mark_arrived_notified(request_id: int) -> None:
    async with Session() as session:
        request = await session.get(Request, request_id)
        if request is not None and not request.arrived_notified:
            request.arrived_notified = True
            await session.commit()


async def movements_history(limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(Movement).order_by(Movement.id.desc()).limit(limit)
    async with Session() as session:
        movements = (await session.execute(stmt)).scalars().all()
        item_ids = {m.item_id for m in movements}
        items = {
            item.id: item
            for item in (
                await session.execute(select(Item).where(Item.id.in_(item_ids)))
            ).scalars().all()
        }
        return [movement_to_dict(m, items.get(m.item_id)) for m in movements]


async def mark_items_bought(request_id: int) -> int:
    """Отмечает все позиции заявки купленными — так заявка уезжает на склад."""
    async with Session() as session:
        request = await session.get(Request, request_id)
        if request is None:
            return 0
        changed = 0
        for item in request.items:
            if not item.bought:
                item.bought = True
                item.bought_at = utcnow()
                changed += 1
        if changed:
            await session.commit()
        return changed

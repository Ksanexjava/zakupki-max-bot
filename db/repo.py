"""Доступ к данным: заявки, история, админы. Всё остальное работает через эти функции."""

from typing import Any, Sequence

from sqlalchemy import func, inspect as sa_inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.statuses import DEFAULT_STATUS
from core.categories import classify, parse_keywords
from core.quantities import normalize_name, parse_quantity
from db.migrate import make_stock_code
from db.models import (
    Admin,
    Attachment,
    Category,
    Employee,
    Instance,
    Item,
    Location,
    LocationCategory,
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
    rules = await _load_rules(session)
    product = Product(
        name=name.strip(),
        norm_name=key,
        unit=unit or "",
        category_id=classify(name, rules),
    )
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
    from_location_id: int | None = None,
    instance_ids: list[int] | None = None,
) -> dict[str, Any] | None:
    """Проводит приход или выдачу по позиции заявки.

    close=True закрывает позицию целиком («принял всё», «выдал всё») — так
    склад может закрыть позицию, даже если количество не было числом.

    Приход всегда падает в зону приёмки — оттуда товар раскладывают по полкам.
    Для крупного товара (поштучный учёт) на каждую принятую единицу
    заводится экземпляр со своим кодом.
    """
    if kind not in {"in", "out"}:
        return None

    arrived = completed = False
    request_id: int | None = None
    movement_id: int | None = None
    created_instances: list[str] = []

    async with Session() as session:
        item = await session.get(Item, item_id)
        if item is None:
            return None
        request_id = item.request_id

        if item.product_id is None:
            product = await _get_or_create_product(session, item.name, item.qty_unit)
            item.product_id = product.id

        product = await session.get(Product, item.product_id)
        serialized = await _is_serialized(session, product) if product else False
        zone = await receiving_zone(session)

        if kind == "in":
            movement = await _write_move(
                session, kind="in", product_id=item.product_id, quantity=float(quantity or 0),
                actor_name=actor_name, actor_employee_id=actor_employee_id,
                to_location_id=zone.id, item_id=item.id, note=note,
            )
            movement_id = movement.id
            if serialized:
                for _ in range(int(round(float(quantity or 0)))):
                    instance = Instance(
                        code=await _next_code(session, "IN", 5, Instance, Instance.code),
                        product_id=item.product_id,
                        item_id=item.id,
                        location_id=zone.id,
                    )
                    session.add(instance)
                    await session.flush()
                    created_instances.append(instance.code)
        else:
            if serialized:
                # выдаём конкретные экземпляры: выбранные вручную или самые ранние
                stmt = select(Instance).where(
                    Instance.item_id == item.id, Instance.status == "stock"
                ).order_by(Instance.id)
                if instance_ids:
                    stmt = stmt.where(Instance.id.in_(instance_ids))
                pool = (await session.execute(stmt)).scalars().all()
                take = pool if instance_ids else pool[: int(round(float(quantity or 0)))]
                for instance in take:
                    movement = await _write_move(
                        session, kind="out", product_id=item.product_id, quantity=1,
                        actor_name=actor_name, actor_employee_id=actor_employee_id,
                        from_location_id=instance.location_id, instance_id=instance.id,
                        item_id=item.id, recipient_name=recipient_name,
                        recipient_employee_id=recipient_employee_id, note=note,
                    )
                    movement_id = movement.id
                    instance.status = "issued"
                    instance.issued_to = recipient_name
                    instance.issued_at = utcnow()
                    instance.location_id = None
                quantity = len(take)
            else:
                if from_location_id is None:
                    # берём оттуда, где этого товара больше всего; зона приёмки — первой
                    balances = await _balances(session)
                    places = sorted(
                        ((loc, qty) for (pid, loc), qty in balances.items()
                         if pid == item.product_id and qty > 0),
                        key=lambda pair: (pair[0] != zone.id, -pair[1]),
                    )
                    from_location_id = places[0][0] if places else zone.id
                movement = await _write_move(
                    session, kind="out", product_id=item.product_id, quantity=float(quantity or 0),
                    actor_name=actor_name, actor_employee_id=actor_employee_id,
                    from_location_id=from_location_id, item_id=item.id,
                    recipient_name=recipient_name, recipient_employee_id=recipient_employee_id,
                    note=note,
                )
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
        "instances_created": created_instances,
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
        item_ids = {m.item_id for m in movements if m.item_id}
        items = {
            item.id: item
            for item in (
                await session.execute(select(Item).where(Item.id.in_(item_ids)))
            ).scalars().all()
        } if item_ids else {}
        products = {p.id: p for p in (await session.execute(select(Product))).scalars().all()}
        locations = {l.id: l for l in (await session.execute(select(Location))).scalars().all()}
        instances = {i.id: i for i in (await session.execute(select(Instance))).scalars().all()}

    rows = []
    for movement in movements:
        data = movement_to_dict(movement, items.get(movement.item_id))
        product = products.get(movement.product_id)
        if not data.get("item_name") and product is not None:
            data["item_name"] = product.name
        source = locations.get(movement.from_location_id)
        target = locations.get(movement.to_location_id)
        data["from_code"] = source.code if source else ""
        data["to_code"] = target.code if target else ""
        instance = instances.get(movement.instance_id)
        data["instance_code"] = instance.code if instance else ""
        rows.append(data)
    return rows


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


# ====================================================== КАТЕГОРИИ

async def _load_rules(session: AsyncSession) -> list:
    """Правила классификатора из справочника в базе, в порядке дерева."""
    categories = (await session.execute(select(Category))).scalars().all()
    by_id = {c.id: c for c in categories}

    def sort_key(category: Category) -> tuple:
        parent = by_id.get(category.parent_id) if category.parent_id else None
        return (parent.position if parent else category.position,
                category.position if parent else 0)

    rules = []
    for order, category in enumerate(sorted(categories, key=sort_key)):
        rules += parse_keywords(category.id, category.keywords, order)
    return rules


async def classify_unassigned_products() -> int:
    """Раскладывает по категориям товары, которым категорию ещё не назначили."""
    async with Session() as session:
        rules = await _load_rules(session)
        products = (
            await session.execute(
                select(Product).where(
                    Product.category_id.is_(None), Product.category_manual.is_(False)
                )
            )
        ).scalars().all()
        assigned = 0
        for product in products:
            category_id = classify(product.name, rules)
            if category_id is not None:
                product.category_id = category_id
                assigned += 1
        if assigned:
            await session.commit()
        return assigned


def _serialized_from(product: Product, categories: dict[int, Category]) -> bool:
    """То же, что _is_serialized, но по уже загруженному справочнику категорий."""
    if product.serialized is not None:
        return bool(product.serialized)
    category = categories.get(product.category_id)
    if category is None:
        return False
    if category.serialized:
        return True
    parent = categories.get(category.parent_id) if category.parent_id else None
    return bool(parent and parent.serialized)


def _category_path(category: Category | None, by_id: dict) -> dict[str, Any]:
    if category is None:
        return {"category_id": None, "category": "Без категории", "subcategory": "", "path": "Без категории"}
    parent = by_id.get(category.parent_id) if category.parent_id else None
    if parent is None:
        return {"category_id": category.id, "category": category.name, "subcategory": "",
                "path": category.name}
    return {"category_id": category.id, "category": parent.name, "subcategory": category.name,
            "path": f"{parent.name} → {category.name}"}


async def list_categories() -> list[dict[str, Any]]:
    """Дерево категорий: разделы с подкатегориями."""
    async with Session() as session:
        categories = (await session.execute(select(Category))).scalars().all()
    tops = sorted((c for c in categories if c.parent_id is None), key=lambda c: c.position)
    tree = []
    for top in tops:
        children = sorted((c for c in categories if c.parent_id == top.id), key=lambda c: c.position)
        tree.append({
            "id": top.id,
            "name": top.name,
            "serialized": bool(top.serialized),
            "children": [
                {"id": c.id, "name": c.name, "serialized": bool(c.serialized), "keywords": c.keywords}
                for c in children
            ],
        })
    return tree


async def set_product_category(product_id: int, category_id: int | None) -> bool:
    """Ручная категория товара — запоминается, автоклассификатор её не трогает."""
    async with Session() as session:
        product = await session.get(Product, product_id)
        if product is None:
            return False
        product.category_id = category_id
        product.category_manual = True
        await session.commit()
        return True


async def update_category_keywords(category_id: int, keywords: str) -> bool:
    async with Session() as session:
        category = await session.get(Category, category_id)
        if category is None:
            return False
        category.keywords = keywords.strip()
        await session.commit()
    # новые слова сразу применяем к ещё не разложенным товарам
    await classify_unassigned_products()
    return True


async def _is_serialized(session: AsyncSession, product: Product) -> bool:
    """Поштучный учёт: ручная настройка товара важнее настройки категории."""
    if product.serialized is not None:
        return bool(product.serialized)
    if product.category_id is None:
        return False
    category = await session.get(Category, product.category_id)
    if category is None:
        return False
    if category.serialized:
        return True
    if category.parent_id:
        parent = await session.get(Category, category.parent_id)
        return bool(parent and parent.serialized)
    return False


# ====================================================== МЕСТА ХРАНЕНИЯ

async def _next_code(session: AsyncSession, prefix: str, width: int, model, column) -> str:
    existing = {
        code for (code,) in (
            await session.execute(select(column).where(column.like(f"{prefix}-%")))
        ).all()
    }
    number = len(existing) + 1
    while f"{prefix}-{number:0{width}d}" in existing:
        number += 1
    return f"{prefix}-{number:0{width}d}"


async def receiving_zone(session: AsyncSession) -> Location:
    from db.migrate import RECEIVING_ZONE_CODE
    return (
        await session.execute(select(Location).where(Location.code == RECEIVING_ZONE_CODE))
    ).scalar_one()


def location_to_dict(location: Location, category_ids: list[int] | None = None) -> dict[str, Any]:
    return {
        "id": location.id,
        "kind": location.kind,
        "code": location.code,
        "name": location.name,
        "parent_id": location.parent_id,
        "note": location.note,
        "category_ids": category_ids or [],
    }


#: виды мест: полка под раздел; коробка и место на полке — под подраздел
LOCATION_KINDS = {"shelf": ("SH", 2), "box": ("BX", 3), "lot": ("LT", 3)}
ON_SHELF = {"box", "lot"}


async def _check_place(session: AsyncSession, kind: str, parent_id: int | None,
                       category_ids: list[int] | None) -> list[int]:
    """Полке назначают только разделы, коробке и месту на полке — только подразделы.

    Место на полке без полки не бывает; коробка может стоять и отдельно.
    """
    if kind == "lot" and not parent_id:
        raise ValueError("parent")
    if parent_id:
        parent = await session.get(Location, parent_id)
        if parent is None or parent.kind != "shelf":
            raise ValueError("parent")
    ids = [int(c) for c in category_ids or []]
    for category_id in ids:
        category = await session.get(Category, category_id)
        if category is None:
            raise ValueError("category")
        if kind == "shelf" and category.parent_id is not None:
            raise ValueError("category")
        if kind in ON_SHELF and category.parent_id is None:
            raise ValueError("category")
    return ids


async def create_location(
    kind: str,
    name: str,
    parent_id: int | None = None,
    category_ids: list[int] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Новая полка (SH-01), коробка (BX-001) или место на полке (LT-001)."""
    if kind not in LOCATION_KINDS:
        raise ValueError("kind")
    async with Session() as session:
        parent_id = parent_id if kind in ON_SHELF else None
        ids = await _check_place(session, kind, parent_id, category_ids)
        prefix, width = LOCATION_KINDS[kind]
        location = Location(
            kind=kind,
            code=await _next_code(session, prefix, width, Location, Location.code),
            name=name.strip(),
            parent_id=parent_id,
            note=note.strip(),
        )
        session.add(location)
        await session.flush()
        for category_id in ids:
            session.add(LocationCategory(location_id=location.id, category_id=category_id))
        await session.commit()
        await session.refresh(location)
        return location_to_dict(location, ids)


async def update_location(
    location_id: int,
    name: str | None = None,
    parent_id: int | None = None,
    category_ids: list[int] | None = None,
    note: str | None = None,
    active: bool | None = None,
) -> dict[str, Any] | None:
    """parent_id: None — не трогать, 0 — снять с полки."""
    async with Session() as session:
        location = await session.get(Location, location_id)
        if location is None or location.kind == "zone":
            return None
        new_parent = location.parent_id
        if location.kind in ON_SHELF and parent_id is not None:
            new_parent = parent_id or None
        ids = await _check_place(session, location.kind, new_parent, category_ids)
        if name is not None:
            location.name = name.strip()
        if note is not None:
            location.note = note.strip()
        if active is not None:
            location.active = active
        location.parent_id = new_parent
        if category_ids is not None:
            await session.execute(
                LocationCategory.__table__.delete().where(LocationCategory.location_id == location_id)
            )
            for category_id in ids:
                session.add(LocationCategory(location_id=location_id, category_id=category_id))
        await session.commit()
        await session.refresh(location)
        links = (
            await session.execute(select(LocationCategory).where(LocationCategory.location_id == location_id))
        ).scalars().all()
        return location_to_dict(location, [link.category_id for link in links])


async def _balances(session: AsyncSession) -> dict[tuple[int, int], float]:
    """Остаток по каждой паре (товар, место): пришло туда минус ушло оттуда."""
    totals: dict[tuple[int, int], float] = {}
    incoming = await session.execute(
        select(Movement.product_id, Movement.to_location_id, func.sum(Movement.quantity))
        .where(Movement.to_location_id.is_not(None), Movement.product_id.is_not(None))
        .group_by(Movement.product_id, Movement.to_location_id)
    )
    for product_id, location_id, quantity in incoming.all():
        totals[(product_id, location_id)] = totals.get((product_id, location_id), 0) + float(quantity or 0)
    outgoing = await session.execute(
        select(Movement.product_id, Movement.from_location_id, func.sum(Movement.quantity))
        .where(Movement.from_location_id.is_not(None), Movement.product_id.is_not(None))
        .group_by(Movement.product_id, Movement.from_location_id)
    )
    for product_id, location_id, quantity in outgoing.all():
        totals[(product_id, location_id)] = totals.get((product_id, location_id), 0) - float(quantity or 0)
    return {key: value for key, value in totals.items() if abs(value) > 1e-9}


async def list_locations() -> list[dict[str, Any]]:
    """Полки с коробками, назначением и тем, сколько позиций в каждой лежит."""
    async with Session() as session:
        locations = (await session.execute(select(Location).where(Location.active.is_(True)))).scalars().all()
        links = (await session.execute(select(LocationCategory))).scalars().all()
        balances = await _balances(session)
        instances = (
            await session.execute(
                select(Instance.location_id, func.count())
                .where(Instance.status == "stock")
                .group_by(Instance.location_id)
            )
        ).all()
    cats_by_location: dict[int, list[int]] = {}
    for link in links:
        cats_by_location.setdefault(link.location_id, []).append(link.category_id)
    products_by_location: dict[int, int] = {}
    for (product_id, location_id), quantity in balances.items():
        if quantity > 0:
            products_by_location[location_id] = products_by_location.get(location_id, 0) + 1
    instance_counts = {location_id: count for location_id, count in instances}

    rows = []
    order = {"zone": 0, "shelf": 1, "box": 2, "lot": 3}
    for location in sorted(locations, key=lambda l: (order.get(l.kind, 9), l.code)):
        data = location_to_dict(location, cats_by_location.get(location.id, []))
        data["products"] = products_by_location.get(location.id, 0)
        data["instances"] = instance_counts.get(location.id, 0)
        rows.append(data)
    return rows


async def resolve_code(code: str) -> dict[str, Any] | None:
    """Что за код отсканировали: полка, коробка, экземпляр или позиция заявки."""
    cleaned = (code or "").strip()
    # QR может содержать ссылку вида …/s/SH-01 — берём хвост
    if "/" in cleaned:
        cleaned = cleaned.rstrip("/").rsplit("/", 1)[-1]
    cleaned = cleaned.upper()
    if not cleaned:
        return None

    async with Session() as session:
        location = (
            await session.execute(select(Location).where(Location.code == cleaned))
        ).scalar_one_or_none()
        if location is not None:
            return {"type": location.kind, "code": cleaned, "id": location.id}
        instance = (
            await session.execute(select(Instance).where(Instance.code == cleaned))
        ).scalar_one_or_none()
        if instance is not None:
            return {"type": "instance", "code": cleaned, "id": instance.id}
        item = (
            await session.execute(select(Item).where(Item.stock_code == cleaned))
        ).scalar_one_or_none()
        if item is not None:
            return {"type": "position", "code": cleaned, "id": item.id}
    return None


# ====================================================== ОСТАТКИ И ДВИЖЕНИЯ

def instance_to_dict(instance: Instance, product: Product | None = None,
                     location: Location | None = None) -> dict[str, Any]:
    return {
        "id": instance.id,
        "code": instance.code,
        "product_id": instance.product_id,
        "product_name": product.name if product else "",
        "category_id": product.category_id if product else None,
        "location_id": instance.location_id,
        "location_code": location.code if location else "",
        "location_name": location.name if location else "",
        "status": instance.status,
        "issued_to": instance.issued_to,
    }


async def location_contents(location_id: int) -> dict[str, Any] | None:
    """Что лежит в месте: товары количеством и экземпляры поштучно."""
    async with Session() as session:
        location = await session.get(Location, location_id)
        if location is None:
            return None
        balances = await _balances(session)
        product_ids = [pid for (pid, lid), qty in balances.items() if lid == location_id and qty > 0]
        products = {
            p.id: p for p in (
                await session.execute(select(Product).where(Product.id.in_(product_ids)))
            ).scalars().all()
        } if product_ids else {}
        categories = {c.id: c for c in (await session.execute(select(Category))).scalars().all()}
        instances = (
            await session.execute(
                select(Instance).where(Instance.location_id == location_id, Instance.status == "stock")
            )
        ).scalars().all()
        instance_products = {
            p.id: p for p in (
                await session.execute(
                    select(Product).where(Product.id.in_([i.product_id for i in instances]))
                )
            ).scalars().all()
        } if instances else {}
        children = (
            await session.execute(select(Location).where(Location.parent_id == location_id))
        ).scalars().all()
        links = (
            await session.execute(select(LocationCategory).where(LocationCategory.location_id == location_id))
        ).scalars().all()

        items = []
        for product_id in product_ids:
            product = products[product_id]
            items.append({
                "product_id": product_id,
                "name": product.name,
                "unit": product.unit,
                "quantity": balances[(product_id, location_id)],
                **_category_path(categories.get(product.category_id), categories),
            })
        items.sort(key=lambda row: (row["path"], row["name"]))
        return {
            "location": location_to_dict(location, [link.category_id for link in links]),
            "items": items,
            "instances": [instance_to_dict(i, instance_products.get(i.product_id), location) for i in instances],
            "boxes": [location_to_dict(child) for child in children if child.active],
        }


async def stock_overview() -> list[dict[str, Any]]:
    """Остатки по товарам: сколько всего и где лежит. Основа вкладки «Хранение»."""
    async with Session() as session:
        balances = await _balances(session)
        products = {p.id: p for p in (await session.execute(select(Product))).scalars().all()}
        locations = {l.id: l for l in (await session.execute(select(Location))).scalars().all()}
        categories = {c.id: c for c in (await session.execute(select(Category))).scalars().all()}

    by_product: dict[int, dict[str, Any]] = {}
    for (product_id, location_id), quantity in balances.items():
        if quantity <= 0 or product_id not in products:
            continue
        product = products[product_id]
        row = by_product.setdefault(product_id, {
            "product_id": product_id,
            "name": product.name,
            "unit": product.unit,
            "min_stock": product.min_stock,
            "serialized": _serialized_from(product, categories),
            "total": 0.0,
            "places": [],
            **_category_path(categories.get(product.category_id), categories),
        })
        location = locations.get(location_id)
        row["total"] += quantity
        row["places"].append({
            "location_id": location_id,
            "code": location.code if location else "",
            "name": location.name if location else "",
            "kind": location.kind if location else "",
            "quantity": quantity,
        })
    rows = list(by_product.values())
    for row in rows:
        row["low"] = row["min_stock"] is not None and row["total"] < row["min_stock"]
        row["places"].sort(key=lambda place: (place["kind"] != "zone", place["code"]))
    rows.sort(key=lambda row: (row["category"] == "Без категории", row["path"], row["name"]))
    return rows


async def receiving_queue() -> list[dict[str, Any]]:
    """Что лежит в зоне приёмки и ждёт размещения по полкам."""
    async with Session() as session:
        zone = await receiving_zone(session)
    contents = await location_contents(zone.id)
    return contents or {"items": [], "instances": []}


async def _write_move(
    session: AsyncSession,
    *,
    kind: str,
    product_id: int,
    quantity: float,
    actor_name: str,
    from_location_id: int | None = None,
    to_location_id: int | None = None,
    instance_id: int | None = None,
    item_id: int | None = None,
    recipient_name: str = "",
    recipient_employee_id: int | None = None,
    actor_employee_id: int | None = None,
    note: str = "",
) -> Movement:
    movement = Movement(
        kind=kind,
        product_id=product_id,
        quantity=float(quantity),
        actor_name=actor_name,
        actor_employee_id=actor_employee_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        instance_id=instance_id,
        item_id=item_id,
        recipient_name=recipient_name,
        recipient_employee_id=recipient_employee_id,
        note=note,
    )
    session.add(movement)
    await session.flush()
    return movement


async def place(
    *,
    product_id: int | None = None,
    quantity: float = 0,
    instance_id: int | None = None,
    to_location_id: int,
    from_location_id: int | None = None,
    actor_name: str = "",
) -> dict[str, Any]:
    """Размещение или перемещение: переложить товар из одного места в другое.

    По умолчанию берём из зоны приёмки. Для крупного товара указывается
    экземпляр — он переезжает целиком.
    """
    async with Session() as session:
        target = await session.get(Location, to_location_id)
        if target is None:
            return {"ok": False, "error": "no_location"}

        if instance_id is not None:
            instance = await session.get(Instance, instance_id)
            if instance is None or instance.status != "stock":
                return {"ok": False, "error": "no_instance"}
            source_id = instance.location_id
            await _write_move(
                session, kind="move", product_id=instance.product_id, quantity=1,
                actor_name=actor_name, from_location_id=source_id,
                to_location_id=to_location_id, instance_id=instance.id,
            )
            instance.location_id = to_location_id
            await session.commit()
            return {"ok": True, "moved": 1, "to": target.code}

        if product_id is None or quantity <= 0:
            return {"ok": False, "error": "bad_request"}
        if from_location_id is None:
            from_location_id = (await receiving_zone(session)).id
        available = (await _balances(session)).get((product_id, from_location_id), 0)
        if quantity > available + 1e-9:
            return {"ok": False, "error": "not_enough", "available": available}
        await _write_move(
            session, kind="move", product_id=product_id, quantity=quantity,
            actor_name=actor_name, from_location_id=from_location_id, to_location_id=to_location_id,
        )
        await session.commit()
        return {"ok": True, "moved": quantity, "to": target.code}


async def issue_from_stock(
    *,
    product_id: int | None = None,
    quantity: float = 0,
    location_id: int | None = None,
    instance_id: int | None = None,
    actor_name: str = "",
    actor_employee_id: int | None = None,
    recipient_name: str = "",
    recipient_employee_id: int | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Выдача со склада без заявки — так разбирают расходники на нужды."""
    async with Session() as session:
        if instance_id is not None:
            instance = await session.get(Instance, instance_id)
            if instance is None or instance.status != "stock":
                return {"ok": False, "error": "no_instance"}
            await _write_move(
                session, kind="out", product_id=instance.product_id, quantity=1,
                actor_name=actor_name, actor_employee_id=actor_employee_id,
                from_location_id=instance.location_id, instance_id=instance.id,
                item_id=instance.item_id, recipient_name=recipient_name,
                recipient_employee_id=recipient_employee_id, note=note,
            )
            instance.status = "issued"
            instance.issued_to = recipient_name
            instance.issued_at = utcnow()
            instance.location_id = None
            await session.commit()
            return {"ok": True, "issued": 1}

        if product_id is None or location_id is None or quantity <= 0:
            return {"ok": False, "error": "bad_request"}
        available = (await _balances(session)).get((product_id, location_id), 0)
        if quantity > available + 1e-9:
            return {"ok": False, "error": "not_enough", "available": available}
        await _write_move(
            session, kind="out", product_id=product_id, quantity=quantity,
            actor_name=actor_name, actor_employee_id=actor_employee_id,
            from_location_id=location_id, recipient_name=recipient_name,
            recipient_employee_id=recipient_employee_id, note=note,
        )
        await session.commit()
        return {"ok": True, "issued": quantity}


async def get_instance(instance_id: int) -> dict[str, Any] | None:
    async with Session() as session:
        instance = await session.get(Instance, instance_id)
        if instance is None:
            return None
        product = await session.get(Product, instance.product_id)
        location = await session.get(Location, instance.location_id) if instance.location_id else None
        return instance_to_dict(instance, product, location)


async def list_instances(item_id: int | None = None, product_id: int | None = None) -> list[dict[str, Any]]:
    stmt = select(Instance).order_by(Instance.id)
    if item_id is not None:
        stmt = stmt.where(Instance.item_id == item_id)
    if product_id is not None:
        stmt = stmt.where(Instance.product_id == product_id)
    async with Session() as session:
        instances = (await session.execute(stmt)).scalars().all()
        products = {p.id: p for p in (await session.execute(select(Product))).scalars().all()}
        locations = {l.id: l for l in (await session.execute(select(Location))).scalars().all()}
    return [
        instance_to_dict(i, products.get(i.product_id), locations.get(i.location_id))
        for i in instances
    ]


async def products_catalog() -> list[dict[str, Any]]:
    """Справочник товаров с категориями — для ручной правки."""
    async with Session() as session:
        products = (await session.execute(select(Product).order_by(Product.name))).scalars().all()
        categories = {c.id: c for c in (await session.execute(select(Category))).scalars().all()}
        result = []
        for product in products:
            result.append({
                "id": product.id,
                "name": product.name,
                "unit": product.unit,
                "category_manual": bool(product.category_manual),
                "serialized": await _is_serialized(session, product),
                "serialized_override": product.serialized,
                "min_stock": product.min_stock,
                **_category_path(categories.get(product.category_id), categories),
            })
        return result


async def update_product(
    product_id: int,
    *,
    category_id: int | None | str = "keep",
    serialized: bool | None | str = "keep",
    min_stock: float | None | str = "keep",
) -> bool:
    async with Session() as session:
        product = await session.get(Product, product_id)
        if product is None:
            return False
        if category_id != "keep":
            product.category_id = category_id
            product.category_manual = True
        if serialized != "keep":
            product.serialized = serialized
        if min_stock != "keep":
            product.min_stock = min_stock
        await session.commit()
        return True


async def receive_manual(
    *,
    name: str,
    quantity: float,
    unit: str = "",
    category_id: int | None = None,
    note: str = "",
    actor_name: str = "",
    actor_employee_id: int | None = None,
) -> dict[str, Any]:
    """Приём товара без заявки: принесли, передали, купили сами.

    Товар ищется по названию среди известных или заводится новый. Категорию
    можно указать сразу — тогда она запоминается как ручная. Приход падает в
    зону приёмки, как и обычный, поштучный товар получает номера.
    """
    name = (name or "").strip()
    quantity = float(quantity or 0)
    if not name or quantity <= 0:
        return {"ok": False, "error": "bad_request"}
    created: list[str] = []
    async with Session() as session:
        product = await _get_or_create_product(session, name, unit.strip())
        if category_id is not None and product.category_id != category_id:
            product.category_id = category_id
            product.category_manual = True
        if unit.strip() and not product.unit:
            product.unit = unit.strip()
        zone = await receiving_zone(session)
        await _write_move(
            session, kind="in", product_id=product.id, quantity=quantity,
            actor_name=actor_name, actor_employee_id=actor_employee_id,
            to_location_id=zone.id, note=note.strip() or "без заявки",
        )
        if await _is_serialized(session, product):
            for _ in range(int(round(quantity))):
                instance = Instance(
                    code=await _next_code(session, "IN", 5, Instance, Instance.code),
                    product_id=product.id,
                    location_id=zone.id,
                )
                session.add(instance)
                await session.flush()
                created.append(instance.code)
        product_id = product.id
        await session.commit()
    return {"ok": True, "product_id": product_id, "item": {"product_id": product_id}, "instances_created": created}


async def suggest_category(name: str) -> int | None:
    """Какую категорию классификатор дал бы товару с таким названием."""
    key = normalize_name(name or "")
    async with Session() as session:
        product = (
            await session.execute(select(Product).where(Product.norm_name == key))
        ).scalar_one_or_none()
        if product is not None and product.category_id is not None:
            return product.category_id
        return classify(name or "", await _load_rules(session))


async def product_paths() -> dict[int, str]:
    """Путь категории для каждого товара — для подписей на наклейках."""
    async with Session() as session:
        products = (await session.execute(select(Product))).scalars().all()
        categories = {c.id: c for c in (await session.execute(select(Category))).scalars().all()}
    return {p.id: _category_path(categories.get(p.category_id), categories)["path"] for p in products}

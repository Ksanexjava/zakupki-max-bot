"""Доступ к данным: заявки, история, админы. Всё остальное работает через эти функции."""

from typing import Any, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.statuses import DEFAULT_STATUS
from db.models import Admin, Request, StatusHistory, utcnow
from db.session import Session

# ------------------------------------------------------------------ заявки

FORM_FIELDS = (
    "requester", "item", "quantity", "deadline", "purpose",
    "example_url", "photo_token", "photo_file",
    "author_user_id", "author_name", "author_username", "author_chat_id",
)


async def create_request(data: dict[str, Any]) -> Request:
    """Создаёт заявку со статусом «Не просмотрено» и первой записью в истории."""
    payload = {key: data.get(key) for key in FORM_FIELDS}
    for key in ("quantity", "deadline", "purpose"):
        payload[key] = payload.get(key) or ""
    async with Session() as session:
        request = Request(**payload, status=DEFAULT_STATUS)
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
    """Удаляет заявку вместе с историей. Возвращает её данные (для уведомления)."""
    async with Session() as session:
        request = await session.get(Request, request_id)
        if request is None:
            return None
        data = to_dict(request)
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

def to_dict(request: Request) -> dict[str, Any]:
    """Заявка в виде обычного словаря — для JSON панели и текстов бота."""
    return {
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

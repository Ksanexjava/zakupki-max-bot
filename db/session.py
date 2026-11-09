"""Подключение к базе и создание таблиц."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db import migrate
from db.models import Base, Employee, Item, Request

log = logging.getLogger(__name__)


def _prepare_sqlite_dir(url: str) -> None:
    """Для SQLite создаёт папку под файл базы, иначе первый запуск падает."""
    prefix = "sqlite+aiosqlite:///"
    if url.startswith(prefix):
        path = Path(url[len(prefix):])
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_dir(settings.database_url)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Создаёт таблицы, если их ещё нет.

    Для такого маленького проекта миграции Alembic избыточны: таблицы
    создаются при первом запуске. Если меняете модели — удалите файл базы
    (или том docker) и запустите заново.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate.run(conn)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    await migrate_items()
    async with Session() as session:
        await migrate.backfill(session)
    await seed_employees()
    log.info("База готова: %s", settings.database_url)


async def migrate_items() -> None:
    """Переносит старые заявки в формат со списком позиций.

    До появления таблицы items товар хранился прямо в заявке. Здесь для каждой
    такой заявки создаётся одна позиция. Повторные запуски ничего не делают.
    """
    async with Session() as session:
        without_items = (
            await session.execute(
                select(Request).where(~Request.items.any()).order_by(Request.id)
            )
        ).scalars().all()
        if not without_items:
            return
        for request in without_items:
            session.add(
                Item(
                    request_id=request.id,
                    position=1,
                    name=request.item,
                    quantity=request.quantity or "",
                    link=request.example_url,
                    photo_token=request.photo_token,
                    photo_file=request.photo_file,
                )
            )
        await session.commit()
        log.info("Перенесено заявок в формат позиций: %s", len(without_items))


async def seed_employees() -> None:
    """Заводит сотрудников по авторам заявок — чтобы справочник не был пустым."""
    async with Session() as session:
        known = {
            name for (name,) in (await session.execute(select(Employee.full_name))).all()
        }
        rows = (
            await session.execute(
                select(Request.author_name, Request.author_user_id).distinct()
            )
        ).all()
        added = 0
        for full_name, max_user_id in rows:
            if not full_name or full_name in known:
                continue
            session.add(Employee(full_name=full_name, max_user_id=max_user_id))
            known.add(full_name)
            added += 1
        if added:
            await session.commit()
            log.info("Добавлено сотрудников из заявок: %s", added)

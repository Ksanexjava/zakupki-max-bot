"""Подключение к базе и создание таблиц."""

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db.models import Base

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
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    log.info("База готова: %s", settings.database_url)

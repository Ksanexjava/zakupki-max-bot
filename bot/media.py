"""Работа с фотографиями из заявок."""

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings

log = logging.getLogger(__name__)


def find_photo(attachments: list[Any] | None) -> Any | None:
    """Первое вложение-изображение в сообщении, если оно есть."""
    for attachment in attachments or []:
        if getattr(attachment, "type", None) == "image":
            return attachment
    return None


async def save_photo(bot: Any, url: str | None) -> str | None:
    """Скачивает фото в media_dir и возвращает имя файла (его отдаёт панель)."""
    if not url:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}-{secrets.token_hex(4)}.jpg"
    try:
        settings.media_dir.mkdir(parents=True, exist_ok=True)
        path = await bot.download_file(url, settings.media_dir, filename=filename)
        return path.name
    except Exception as exc:  # noqa: BLE001 — без фото заявка всё равно должна сохраниться
        log.warning("Не удалось скачать фото: %s", exc)
        return None


def remove_photo(filename: str | None) -> None:
    """Удаляет файл фото вместе с заявкой."""
    if not filename:
        return
    path = settings.media_dir / Path(filename).name
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # noqa: PERF203 — файл мог быть уже удалён вручную
        log.warning("Не удалось удалить фото %s: %s", path, exc)

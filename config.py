"""Настройки приложения. Читаются из переменных окружения и файла .env."""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Читает .env из корня проекта, если он есть (для запуска без Docker).

    Уже заданные переменные окружения не перезаписываются.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on", "да"}


def _parse_users(raw: str) -> dict[str, str]:
    """PANEL_USERS="mike:pass1,ivan:pass2" -> {"mike": "pass1", ...}"""
    users: dict[str, str] = {}
    for chunk in raw.split(","):
        login, _, password = chunk.strip().partition(":")
        if login.strip() and password.strip():
            users[login.strip()] = password.strip()
    return users


def _parse_ids(raw: str) -> tuple[int, ...]:
    return tuple(
        int(chunk.strip())
        for chunk in raw.replace(";", ",").split(",")
        if chunk.strip().lstrip("-").isdigit()
    )


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # бот
    bot_token: str
    api_url: str
    # хранилища
    database_url: str
    redis_url: str
    media_dir: Path
    # кто получает уведомления о новых заявках
    admin_code: str
    admin_user_ids: tuple[int, ...]
    # панель
    panel_enabled: bool
    panel_host: str
    panel_port: int
    panel_users: dict[str, str]
    panel_public_url: str
    secret_key: str
    secret_key_generated: bool
    session_days: int
    secure_cookie: bool
    # поведение
    notify_author: bool
    tz_offset: float
    log_level: str
    seed_demo: bool = field(default=False)


_secret = os.environ.get("SECRET_KEY", "").strip()

settings = Settings(
    bot_token=os.environ.get("MAX_BOT_TOKEN", "").strip(),
    api_url=os.environ.get("MAX_API_BASE", "").strip(),
    database_url=os.environ.get("DATABASE_URL")
    or f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'purchases.db'}",
    redis_url=os.environ.get("REDIS_URL", "").strip(),
    media_dir=Path(os.environ.get("MEDIA_DIR") or BASE_DIR / "data" / "media"),
    admin_code=os.environ.get("ADMIN_CODE", "").strip(),
    admin_user_ids=_parse_ids(os.environ.get("ADMIN_USER_IDS", "")),
    panel_enabled=_bool("PANEL_ENABLED", True),
    panel_host=os.environ.get("PANEL_HOST", "127.0.0.1"),
    panel_port=int(os.environ.get("PANEL_PORT", "8080")),
    panel_users=_parse_users(os.environ.get("PANEL_USERS", "")),
    panel_public_url=os.environ.get("PANEL_PUBLIC_URL", "").strip().rstrip("/"),
    secret_key=_secret or secrets.token_hex(32),
    secret_key_generated=not _secret,
    session_days=int(os.environ.get("PANEL_SESSION_DAYS", "30")),
    secure_cookie=_bool("PANEL_SECURE_COOKIE", False),
    notify_author=_bool("NOTIFY_AUTHOR", True),
    tz_offset=_float("DISPLAY_TZ_OFFSET", 3.0),
    log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    seed_demo=_bool("SEED_DEMO", False),
)

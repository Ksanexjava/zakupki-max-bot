"""Веб-панель заявок: список, фильтры, смена статусов, комментарии."""

import base64
import hmac
import logging
import secrets
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from aiohttp import web

from bot import texts
from config import BASE_DIR, settings
from bot.media import remove_photo
from core.notifications import notify_author, notify_author_comment, notify_author_deleted
from core.statuses import STATUSES
from db import repo

log = logging.getLogger("panel")

COOKIE_NAME = "pb_session"

#: ключи для web.Application (aiohttp просит именно AppKey, а не строки)
BOT_KEY: web.AppKey[Any] = web.AppKey("bot")
LOGIN_FAILURES_KEY: web.AppKey[dict] = web.AppKey("login_failures")
STATIC_DIR = BASE_DIR / "static"
LOGIN_WINDOW = 600  # секунд
LOGIN_MAX_FAILURES = 10

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: какие картинки принимаем и с каким расширением сохраняем
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


# ------------------------------------------------------------------ сессии

def _sign(data: str) -> str:
    return hmac.new(settings.secret_key.encode(), data.encode(), sha256).hexdigest()


def make_token(login: str) -> str:
    expires = int(time.time()) + settings.session_days * 86400
    payload = f"{login}:{expires}"
    return base64.urlsafe_b64encode(f"{payload}:{_sign(payload)}".encode()).decode()


def read_token(token: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        login, expires, signature = raw.rsplit(":", 2)
    except Exception:  # noqa: BLE001 — любой мусор в cookie = нет сессии
        return None
    if not hmac.compare_digest(signature, _sign(f"{login}:{expires}")):
        return None
    if not expires.isdigit() or int(expires) < time.time():
        return None
    return login


def current_user(request: web.Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    login = read_token(token)
    return login if login and login in settings.panel_users else None


@web.middleware
async def no_cache_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Панель обновляется вместе с ботом — браузер не должен держать старый app.js."""
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@web.middleware
async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    open_paths = {"/api/login", "/api/meta", "/healthz"}
    protected = request.path.startswith(("/api/", "/media/")) and request.path not in open_paths
    if protected and current_user(request) is None:
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


# ---------------------------------------------------------------- хендлеры

async def handle_index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_health(request: web.Request) -> web.StreamResponse:
    return web.json_response({"ok": True})


async def handle_meta(request: web.Request) -> web.StreamResponse:
    return web.json_response(
        {
            "statuses": [
                {"key": key, "label": meta["label"], "emoji": meta["emoji"]}
                for key, meta in STATUSES.items()
            ],
            "user": current_user(request),
        }
    )


async def handle_login(request: web.Request) -> web.StreamResponse:
    failures: dict[str, list[float]] = request.app[LOGIN_FAILURES_KEY]
    ip = request.headers.get("X-Forwarded-For", request.remote or "?").split(",")[0].strip()
    now = time.time()
    recent = [stamp for stamp in failures.get(ip, []) if now - stamp < LOGIN_WINDOW]
    failures[ip] = recent
    if len(recent) >= LOGIN_MAX_FAILURES:
        return web.json_response({"error": "too_many_attempts"}, status=429)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)

    login = str(payload.get("login", "")).strip()
    password = str(payload.get("password", ""))
    expected = settings.panel_users.get(login)
    # сравниваем байты: compare_digest не принимает строки с не-ASCII символами
    if not expected or not secrets.compare_digest(password.encode(), expected.encode()):
        failures[ip] = [*recent, now]
        log.warning("Неудачный вход в панель: login=%r ip=%s", login, ip)
        return web.json_response({"error": "invalid_credentials"}, status=401)

    response = web.json_response({"ok": True, "user": login})
    response.set_cookie(
        COOKIE_NAME,
        make_token(login),
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="Lax",
        secure=settings.secure_cookie,
        path="/",
    )
    return response


async def handle_logout(request: web.Request) -> web.StreamResponse:
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE_NAME, path="/")
    return response


def _decorate(data: dict[str, Any]) -> dict[str, Any]:
    """Добавляет к заявке поля, нужные фронтенду."""
    meta = STATUSES.get(data["status"], {"label": data["status"], "emoji": "•"})
    row = dict(data)
    row["created_at"] = texts.fmt_dt(data.get("created_at"))
    row["updated_at"] = texts.fmt_dt(data.get("updated_at"))
    row["status_label"] = meta["label"]
    row["status_emoji"] = meta["emoji"]
    row["created_at_human"] = row["created_at"]
    row["updated_at_human"] = row["updated_at"]
    if data.get("photo_file"):
        row["photo_href"] = f"/media/{data['photo_file']}"
    example = (data.get("example_url") or "").strip()
    row["example_is_link"] = example.startswith(("http://", "https://"))
    return row


async def handle_list(request: web.Request) -> web.StreamResponse:
    status = request.query.get("status")
    status = status if status in STATUSES else None
    query = (request.query.get("q") or "").strip() or None
    rows = await repo.list_requests(status=status, query=query)
    counts = await repo.counts_by_status()
    return web.json_response(
        {
            "requests": [_decorate(repo.to_dict(row)) for row in rows],
            "counts": {key: counts.get(key, 0) for key in STATUSES},
            "total": sum(counts.values()),
        }
    )


async def handle_detail(request: web.Request) -> web.StreamResponse:
    request_id = int(request.match_info["request_id"])
    found = await repo.get_request(request_id)
    if found is None:
        return web.json_response({"error": "not_found"}, status=404)
    history = []
    for item in await repo.history(request_id):
        entry = repo.history_to_dict(item)
        entry["at"] = texts.fmt_dt(entry["at"])
        entry["at_human"] = entry["at"]
        entry["from_label"] = STATUSES.get(entry.get("from_status") or "", {}).get("label")
        entry["to_label"] = STATUSES.get(entry.get("to_status") or "", {}).get("label")
        history.append(entry)
    return web.json_response(
        {
            "request": _decorate(repo.to_dict(found)),
            "history": history,
            "attachments": [
                {**item, "uploaded_at": texts.fmt_dt(item["uploaded_at"])}
                for item in await repo.list_attachments(request_id)
            ],
        }
    )


async def handle_set_status(request: web.Request) -> web.StreamResponse:
    actor = current_user(request) or "panel"
    request_id = int(request.match_info["request_id"])
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)

    status = str(payload.get("status", ""))
    comment = (str(payload.get("comment", "")) or "").strip() or None
    if status not in STATUSES:
        return web.json_response({"error": "unknown_status"}, status=400)

    result = await repo.set_status(request_id, status, actor, comment)
    if result is None:
        return web.json_response({"error": "not_found"}, status=404)

    updated, previous = result
    data = repo.to_dict(updated)
    notified, error = await notify_author(request.app.get(BOT_KEY), data, previous, comment)
    return web.json_response(
        {
            "ok": True,
            "request": _decorate(data),
            "author_notified": notified,
            "notify_error": error,
        }
    )


async def handle_comment(request: web.Request) -> web.StreamResponse:
    actor = current_user(request) or "panel"
    request_id = int(request.match_info["request_id"])
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)
    comment = str(payload.get("comment", "")).strip()
    if not comment:
        return web.json_response({"error": "empty_comment"}, status=400)
    updated = await repo.add_comment(request_id, actor, comment)
    if updated is None:
        return web.json_response({"error": "not_found"}, status=404)

    data = repo.to_dict(updated)
    notified, error = await notify_author_comment(request.app.get(BOT_KEY), data, comment)
    return web.json_response(
        {
            "ok": True,
            "request": _decorate(data),
            "author_notified": notified,
            "notify_error": error,
        }
    )


async def handle_delete(request: web.Request) -> web.StreamResponse:
    """Удаляет заявку вместе с историей и фотографией."""
    actor = current_user(request) or "panel"
    request_id = int(request.match_info["request_id"])
    data = await repo.delete_request(request_id)
    if data is None:
        return web.json_response({"error": "not_found"}, status=404)

    for name in data.get("files", []):
        remove_photo(name)
    log.info("Заявка №%s удалена пользователем %s", request_id, actor)

    notified, error = await notify_author_deleted(request.app.get(BOT_KEY), data)
    return web.json_response({"ok": True, "author_notified": notified, "notify_error": error})


async def handle_upload(request: web.Request) -> web.StreamResponse:
    """Приём скриншота к заявке: multipart-поле `file`."""
    actor = current_user(request) or "panel"
    request_id = int(request.match_info["request_id"])
    if await repo.get_request(request_id) is None:
        return web.json_response({"error": "not_found"}, status=404)

    try:
        reader = await request.multipart()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)

    field = await reader.next()
    while field is not None and field.name != "file":
        field = await reader.next()
    if field is None:
        return web.json_response({"error": "no_file"}, status=400)

    content_type = (field.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    extension = ALLOWED_IMAGE_TYPES.get(content_type)
    if extension is None:
        return web.json_response(
            {"error": "unsupported_type", "detail": content_type or "неизвестный тип"},
            status=415,
        )

    settings.media_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}-{secrets.token_hex(4)}{extension}"
    path = settings.media_dir / filename

    size = 0
    try:
        with path.open("wb") as fh:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError("too_large")
                fh.write(chunk)
    except ValueError:
        path.unlink(missing_ok=True)
        return web.json_response(
            {"error": "too_large", "limit_mb": MAX_UPLOAD_BYTES // (1024 * 1024)}, status=413
        )
    except OSError as exc:
        path.unlink(missing_ok=True)
        log.warning("Не удалось сохранить вложение: %s", exc)
        return web.json_response({"error": "write_failed"}, status=500)

    if size == 0:
        path.unlink(missing_ok=True)
        return web.json_response({"error": "empty_file"}, status=400)

    saved = await repo.add_attachment(request_id, filename, field.filename, actor)
    if saved is None:
        path.unlink(missing_ok=True)
        return web.json_response({"error": "not_found"}, status=404)

    log.info("К заявке №%s приложен скриншот %s (%s КБ)", request_id, filename, size // 1024)
    saved["uploaded_at"] = texts.fmt_dt(saved["uploaded_at"])
    return web.json_response({"ok": True, "attachment": saved})


async def handle_delete_attachment(request: web.Request) -> web.StreamResponse:
    attachment_id = int(request.match_info["attachment_id"])
    data = await repo.delete_attachment(attachment_id)
    if data is None:
        return web.json_response({"error": "not_found"}, status=404)
    remove_photo(data["filename"])
    return web.json_response({"ok": True})


async def handle_media(request: web.Request) -> web.StreamResponse:
    name = Path(request.match_info["filename"]).name  # защита от ../
    path = settings.media_dir / name
    if not path.is_file():
        return web.json_response({"error": "not_found"}, status=404)
    return web.FileResponse(path)


def create_app(bot: Any = None) -> web.Application:
    app = web.Application(middlewares=[no_cache_middleware, auth_middleware])
    app[BOT_KEY] = bot
    app[LOGIN_FAILURES_KEY] = {}
    app.add_routes(
        [
            web.get("/", handle_index),
            web.get("/healthz", handle_health),
            web.get("/api/meta", handle_meta),
            web.post("/api/login", handle_login),
            web.post("/api/logout", handle_logout),
            web.get("/api/requests", handle_list),
            web.get(r"/api/requests/{request_id:\d+}", handle_detail),
            web.post(r"/api/requests/{request_id:\d+}/status", handle_set_status),
            web.post(r"/api/requests/{request_id:\d+}/comment", handle_comment),
            web.delete(r"/api/requests/{request_id:\d+}", handle_delete),
            web.post(r"/api/requests/{request_id:\d+}/attachments", handle_upload),
            web.delete(r"/api/attachments/{attachment_id:\d+}", handle_delete_attachment),
            web.get("/media/{filename}", handle_media),
            web.static("/static", STATIC_DIR),
        ]
    )
    return app


async def start_panel(bot: Any = None) -> web.AppRunner:
    """Поднимает панель рядом с ботом и возвращает runner для остановки."""
    runner = web.AppRunner(create_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, settings.panel_host, settings.panel_port)
    await site.start()
    log.info("Панель закупок: http://%s:%s", settings.panel_host, settings.panel_port)
    if settings.panel_public_url:
        log.info("Внешний адрес панели: %s", settings.panel_public_url)
    return runner

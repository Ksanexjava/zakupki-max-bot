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
from core.notifications import (
    notify_author,
    notify_author_comment,
    notify_author_deleted,
    notify_authors_bulk,
)
from core.statuses import STATUSES
from panel import labels as labels_page
from core.notifications import notify_author_arrived  # noqa: E402
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


def current_role(request: web.Request) -> str | None:
    """admin — закупки, stock — склад."""
    login = current_user(request)
    if login is None:
        return None
    return settings.panel_users.get(login, {}).get("role", "admin")


#: что разрешено складскому логину; всё остальное под /api/ — только закупкам
STOCK_ALLOWED_PREFIXES = (
    "/labels",
    "/api/meta",
    "/api/logout",
    "/api/stock/",
    "/api/employees",
    "/media/",
)


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
    # /labels отдаёт данные заявок, поэтому тоже под авторизацией
    protected = (
        request.path.startswith(("/api/", "/media/", "/labels")) and request.path not in open_paths
    )
    if protected and current_user(request) is None:
        return web.json_response({"error": "unauthorized"}, status=401)

    # кладовщик не должен менять статусы, удалять заявки и трогать вложения
    if protected and current_role(request) == "stock":
        if not request.path.startswith(STOCK_ALLOWED_PREFIXES):
            return web.json_response({"error": "forbidden", "detail": "только для закупок"}, status=403)
    return await handler(request)


# ---------------------------------------------------------------- хендлеры

async def handle_index(request: web.Request) -> web.StreamResponse:
    # кладовщику сразу открываем его экран
    if current_role(request) == "stock":
        raise web.HTTPFound("/sklad")
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_stock_page(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "stock.html")


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
            "role": current_role(request),
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
    account = settings.panel_users.get(login) or {}
    expected = account.get("password", "")
    # сравниваем байты: compare_digest не принимает строки с не-ASCII символами
    if not expected or not secrets.compare_digest(password.encode(), expected.encode()):
        failures[ip] = [*recent, now]
        log.warning("Неудачный вход в панель: login=%r ip=%s", login, ip)
        return web.json_response({"error": "invalid_credentials"}, status=401)

    response = web.json_response(
        {"ok": True, "user": login, "role": account.get("role", "admin")}
    )
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
    if status == "ordered":
        # заявка уехала на склад: отмечаем все позиции купленными
        await repo.mark_items_bought(request_id)
        updated = await repo.get_request(request_id) or updated
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


async def handle_bulk_status(request: web.Request) -> web.StreamResponse:
    """Смена статуса сразу у нескольких заявок."""
    actor = current_user(request) or "panel"
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)

    status = str(payload.get("status", ""))
    comment = (str(payload.get("comment", "")) or "").strip() or None
    ids = [int(value) for value in payload.get("ids", []) if str(value).isdigit()]
    if status not in STATUSES:
        return web.json_response({"error": "unknown_status"}, status=400)
    if not ids:
        return web.json_response({"error": "no_ids"}, status=400)

    changes = await repo.bulk_set_status(ids, status, actor, comment)
    if status == "ordered":
        for data, _ in changes:
            await repo.mark_items_bought(data["id"])
    log.info("Массовая смена статуса на %s: заявок %s, автор действия %s", status, len(changes), actor)

    notified, errors = await notify_authors_bulk(request.app.get(BOT_KEY), changes, comment)
    return web.json_response(
        {
            "ok": True,
            "changed": len(changes),
            "requested": len(ids),
            "authors_notified": notified,
            # одинаковые причины схлопываем: иначе в тосте дубли
            "notify_error": "; ".join(list(dict.fromkeys(errors))[:3]) or None,
        }
    )


async def handle_bulk_delete(request: web.Request) -> web.StreamResponse:
    """Удаление нескольких заявок разом."""
    actor = current_user(request) or "panel"
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)
    ids = [int(value) for value in payload.get("ids", []) if str(value).isdigit()]
    if not ids:
        return web.json_response({"error": "no_ids"}, status=400)

    deleted = await repo.bulk_delete(ids)
    for data in deleted:
        for name in data.get("files", []):
            remove_photo(name)
    log.info("Удалено заявок: %s (пользователь %s)", len(deleted), actor)

    notified = 0
    bot = request.app.get(BOT_KEY)
    if bot is not None:
        for data in deleted:
            ok, _ = await notify_author_deleted(bot, data)
            notified += int(ok)
    return web.json_response({"ok": True, "deleted": len(deleted), "authors_notified": notified})


async def handle_item_bought(request: web.Request) -> web.StreamResponse:
    """Отметка «куплено» у позиции. Статус заявки не меняется."""
    item_id = int(request.match_info["item_id"])
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    bought = bool(payload.get("bought", True))
    item = await repo.set_item_bought(item_id, bought)
    if item is None:
        return web.json_response({"error": "not_found"}, status=404)
    updated = await repo.get_request(item["request_id"])
    return web.json_response(
        {"ok": True, "item": item, "request": _decorate(repo.to_dict(updated)) if updated else None}
    )


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


# ------------------------------------------------------------------ склад

async def handle_stock_queue(request: web.Request) -> web.StreamResponse:
    """Очереди склада: что ждём и что лежит невыданным."""
    kind = request.query.get("kind", "pending")
    kind = kind if kind in {"pending", "on_hand"} else "pending"
    rows = await repo.stock_queue(kind)
    for row in rows:
        row["created_at"] = texts.fmt_dt(row.get("created_at"))
    return web.json_response({"kind": kind, "items": rows})


async def handle_stock_history(request: web.Request) -> web.StreamResponse:
    limit = min(int(request.query.get("limit", 60)), 300)
    rows = await repo.movements_history(limit)
    for row in rows:
        row["created_at"] = texts.fmt_dt(row.get("created_at"))
    return web.json_response({"movements": rows})


async def handle_stock_find(request: web.Request) -> web.StreamResponse:
    """Поиск позиции по складскому коду — для сканера и ручного ввода."""
    found = await repo.find_item_by_code(request.query.get("code", ""))
    if found is None:
        return web.json_response({"error": "not_found"}, status=404)
    found["request"] = _decorate(found["request"]) if found.get("request") else None
    return web.json_response(found)


async def handle_stock_movement(request: web.Request) -> web.StreamResponse:
    """Приём на склад или выдача со склада."""
    actor_login = current_user(request) or "panel"
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)

    kind = str(payload.get("kind", ""))
    if kind not in {"in", "out"}:
        return web.json_response({"error": "bad_kind"}, status=400)
    try:
        item_id = int(payload.get("item_id"))
        quantity = float(payload.get("quantity") or 0)
    except (TypeError, ValueError):
        return web.json_response({"error": "bad_request"}, status=400)
    if quantity < 0:
        return web.json_response({"error": "bad_quantity"}, status=400)

    actor_name = str(payload.get("actor_name", "")).strip() or actor_login
    result = await repo.record_movement(
        item_id=item_id,
        kind=kind,
        quantity=quantity,
        actor_name=actor_name,
        actor_employee_id=payload.get("actor_employee_id") or None,
        recipient_name=str(payload.get("recipient_name", "")).strip(),
        recipient_employee_id=payload.get("recipient_employee_id") or None,
        note=str(payload.get("note", "")).strip(),
        close=bool(payload.get("close")),
    )
    if result is None:
        return web.json_response({"error": "not_found"}, status=404)

    log.info(
        "Склад: %s %s по позиции %s (%s)",
        "приход" if kind == "in" else "выдача", quantity, item_id, actor_name,
    )

    bot = request.app.get(BOT_KEY)
    notified = None
    if result["request_arrived"] and bot is not None and result["request"]:
        ok, _ = await notify_author_arrived(bot, result["request"])
        notified = ok
        if ok:
            await repo.mark_arrived_notified(result["request"]["id"])
    if result["request_completed"] and bot is not None and result["request"]:
        await notify_author(bot, result["request"], "ordered")

    result["request"] = _decorate(result["request"]) if result.get("request") else None
    result["author_notified"] = notified
    return web.json_response({"ok": True, **result})


async def handle_employees(request: web.Request) -> web.StreamResponse:
    return web.json_response({"employees": await repo.list_employees()})


async def handle_employee_add(request: web.Request) -> web.StreamResponse:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request"}, status=400)
    full_name = str(payload.get("full_name", "")).strip()
    if not full_name:
        return web.json_response({"error": "empty_name"}, status=400)
    employee = await repo.add_employee(
        full_name,
        str(payload.get("department", "")).strip(),
        bool(payload.get("is_stock")),
    )
    return web.json_response({"ok": True, "employee": employee})


async def handle_labels(request: web.Request) -> web.StreamResponse:
    """Лист наклеек: /labels?request=12 или /labels?items=5,6,7."""
    item_ids: list[int] = []
    raw_items = request.query.get("items", "")
    for chunk in raw_items.replace(";", ",").split(","):
        if chunk.strip().isdigit():
            item_ids.append(int(chunk.strip()))

    rows: list[dict] = []
    raw_request = request.query.get("request", "")
    if raw_request.isdigit():
        found = await repo.get_request(int(raw_request))
        if found is not None:
            rows = [
                {**repo.item_to_dict(item), "request_id": found.id} for item in found.items
            ]
    if item_ids:
        rows = [row for row in rows if row["id"] in item_ids] if rows else []
        if not rows:
            for item_id in item_ids:
                found = await repo.find_item_by_id(item_id)
                if found is not None:
                    rows.append(found)
    if not rows:
        return web.json_response({"error": "nothing_to_print"}, status=404)

    return web.Response(text=labels_page.render(rows), content_type="text/html")


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
            web.get("/sklad", handle_stock_page),
            web.get("/healthz", handle_health),
            web.get("/api/meta", handle_meta),
            web.post("/api/login", handle_login),
            web.post("/api/logout", handle_logout),
            web.get("/api/requests", handle_list),
            web.get(r"/api/requests/{request_id:\d+}", handle_detail),
            web.post(r"/api/requests/{request_id:\d+}/status", handle_set_status),
            web.post(r"/api/requests/{request_id:\d+}/comment", handle_comment),
            web.delete(r"/api/requests/{request_id:\d+}", handle_delete),
            web.post("/api/requests/bulk-status", handle_bulk_status),
            web.post("/api/requests/bulk-delete", handle_bulk_delete),
            web.post(r"/api/items/{item_id:\d+}/bought", handle_item_bought),
            web.get("/labels", handle_labels),
            web.get("/api/stock/queue", handle_stock_queue),
            web.get("/api/stock/history", handle_stock_history),
            web.get("/api/stock/find", handle_stock_find),
            web.post("/api/stock/movement", handle_stock_movement),
            web.get("/api/employees", handle_employees),
            web.post("/api/employees", handle_employee_add),
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

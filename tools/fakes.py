"""Заглушки MAX для прогона диалога без сети (используются в tools/dry_run.py и тестах)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated

USER = {
    "user_id": 777,
    "first_name": "Иван",
    "last_name": "Петров",
    "username": "ipetrov",
    "is_bot": False,
    "last_activity_time": 0,
}
ADMIN = {
    "user_id": 999,
    "first_name": "Шеф",
    "last_name": None,
    "username": None,
    "is_bot": False,
    "last_activity_time": 0,
}
CHAT_ID = 1000


class FakeBot:
    """Вместо отправки в MAX складывает сообщения в список."""

    def __init__(self, verbose: bool = False) -> None:
        self.messages: list[dict[str, Any]] = []
        self.commands: list[Any] = []   # библиотека собирает сюда /команды при регистрации роутеров
        self.me = SimpleNamespace(user_id=1, username="zakupki_bot", first_name="Бот закупок", is_bot=True)
        self.callbacks: list[dict[str, Any]] = []
        self.verbose = verbose

    def resolve_format(self, value: Any = None) -> Any:
        """Библиотека спрашивает у бота формат текста по умолчанию."""
        return value

    async def send_message(
        self,
        chat_id: int | None = None,
        user_id: int | None = None,
        text: str | None = None,
        attachments: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        entry = {"user_id": user_id, "chat_id": chat_id, "text": text or "", "buttons": _labels(attachments)}
        self.messages.append(entry)
        if self.verbose:
            _print(entry)
        return {"message": {"body": {"mid": f"mid{len(self.messages)}"}}}

    async def send_callback(
        self,
        callback_id: str,
        message: Any = None,
        notification: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        entry = {"notification": notification, "text": getattr(message, "text", None)}
        self.callbacks.append(entry)
        if self.verbose and notification:
            print(f"   ↪︎ всплывающее уведомление: {notification}")
        if self.verbose and entry["text"]:
            print("   ↪︎ сообщение обновлено:")
            for line in str(entry["text"]).splitlines():
                print(f"      {line}")
        return {"success": True}

    async def download_file(self, url: str, destination: Path | str, filename: str | None = None, **kwargs: Any) -> Path:
        if self.verbose:
            print(f"   ↪︎ (скачал бы фото {url})")
        path = Path(destination) / (filename or "photo.jpg")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-photo")
        return path


def _labels(attachments: Any) -> list[str]:
    """Названия кнопок из клавиатуры — чтобы было видно, что предлагает бот."""
    labels: list[str] = []
    for attachment in attachments or []:
        payload = getattr(attachment, "payload", None)
        for row in getattr(payload, "buttons", None) or []:
            labels += [button.text for button in row]
    return labels


def _print(entry: dict[str, Any]) -> None:
    who = "ШЕФУ" if entry["user_id"] == ADMIN["user_id"] else "пользователю"
    print(f"\n🤖 БОТ → {who} ({entry['user_id']}):")
    for line in str(entry["text"]).splitlines():
        print(f"   {line}")
    if entry["buttons"]:
        print(f"   [кнопки] {' | '.join(entry['buttons'])}")


def message_event(bot: FakeBot, text: str | None, attachments: list[dict[str, Any]] | None = None) -> MessageCreated:
    event = MessageCreated.model_validate(
        {
            "update_type": "message_created",
            "timestamp": 0,
            "message": {
                "sender": USER,
                "timestamp": 0,
                "recipient": {"chat_id": CHAT_ID, "chat_type": "dialog", "user_id": USER["user_id"]},
                "body": {"mid": "mid.in", "seq": 1, "text": text, "attachments": attachments or []},
            },
        }
    )
    event.bot = bot
    event.message.bot = bot
    return event


def callback_event(bot: FakeBot, payload: str, user: dict[str, Any] | None = None) -> MessageCallback:
    who = user or USER
    event = MessageCallback.model_validate(
        {
            "update_type": "message_callback",
            "timestamp": 0,
            "callback": {"timestamp": 0, "callback_id": "cb", "payload": payload, "user": who},
            "message": {
                "sender": {"user_id": 1, "first_name": "Бот", "last_name": None, "username": "bot",
                           "is_bot": True, "last_activity_time": 0},
                "timestamp": 0,
                "recipient": {"chat_id": CHAT_ID, "chat_type": "dialog", "user_id": who["user_id"]},
                "body": {"mid": "mid.bot", "seq": 1, "text": "предыдущее сообщение бота", "attachments": []},
            },
        }
    )
    event.bot = bot
    event.message.bot = bot
    return event


PHOTO_ATTACHMENT = {
    "type": "image",
    "payload": {"photo_id": 42, "token": "photo-token", "url": "https://cdn.max.ru/example.jpg"},
}


def bot_started_event(bot: FakeBot, user: dict[str, Any] | None = None):
    from maxapi.types.updates.bot_started import BotStarted

    event = BotStarted.model_validate(
        {
            "update_type": "bot_started",
            "timestamp": 0,
            "chat_id": CHAT_ID,
            "user": user or USER,
            "user_locale": "ru",
        }
    )
    event.bot = bot
    return event

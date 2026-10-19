"""Доставка уведомлений автору: запасной путь и понятные причины отказа."""

import asyncio
import dataclasses

from core import notifications
from core.notifications import notify_author, notify_author_deleted
from tools.fakes import FakeBot

REQUEST = {
    "id": 42,
    "item": "Чайник",
    "status": "ordered",
    "author_user_id": 777,
    "author_chat_id": 555,
    "admin_comment": None,
}


class FailingBot(FakeBot):
    """Бот, у которого отправка по user_id не работает, а по chat_id — работает."""

    def __init__(self, fail_on: str = "user_id") -> None:
        super().__init__()
        self.fail_on = fail_on

    async def send_message(self, chat_id=None, user_id=None, text=None, attachments=None, **kwargs):
        if self.fail_on == "user_id" and user_id is not None:
            raise RuntimeError("user_id не поддерживается")
        if self.fail_on == "all":
            raise RuntimeError("мессенджер недоступен")
        return await super().send_message(
            chat_id=chat_id, user_id=user_id, text=text, attachments=attachments, **kwargs
        )


def test_delivered_by_user_id():
    async def scenario():
        bot = FakeBot()
        ok, error = await notify_author(bot, REQUEST, previous_status="new")
        assert ok and error is None
        assert bot.messages[-1]["user_id"] == 777

    asyncio.run(scenario())


def test_falls_back_to_chat_id():
    """Если отправка по user_id не прошла, пробуем chat_id диалога."""

    async def scenario():
        bot = FailingBot(fail_on="user_id")
        ok, error = await notify_author(bot, REQUEST, previous_status="new")
        assert ok and error is None
        assert bot.messages[-1]["chat_id"] == 555

    asyncio.run(scenario())


def test_reports_reason_when_all_fail():
    async def scenario():
        bot = FailingBot(fail_on="all")
        ok, error = await notify_author_deleted(bot, REQUEST)
        assert not ok
        assert "user_id=777" in error and "chat_id=555" in error
        assert "мессенджер недоступен" in error

    asyncio.run(scenario())


def test_no_bot_and_no_author():
    async def scenario():
        ok, error = await notify_author(None, REQUEST, previous_status="new")
        assert not ok and error == "бот не запущен"

        ok, error = await notify_author(FakeBot(), {**REQUEST, "author_user_id": None}, "new")
        assert not ok and error == "у заявки не сохранён автор"

    asyncio.run(scenario())


def test_disabled_by_setting(monkeypatch):
    async def scenario():
        ok, error = await notify_author(FakeBot(), REQUEST, previous_status="new")
        assert not ok and "NOTIFY_AUTHOR" in error

    # Settings — frozen dataclass, поэтому подменяем объект целиком
    monkeypatch.setattr(
        notifications, "settings", dataclasses.replace(notifications.settings, notify_author=False)
    )
    asyncio.run(scenario())


def test_same_status_without_comment_is_silent():
    async def scenario():
        bot = FakeBot()
        ok, error = await notify_author(bot, REQUEST, previous_status="ordered")
        assert not ok and error is None
        assert not bot.messages

    asyncio.run(scenario())

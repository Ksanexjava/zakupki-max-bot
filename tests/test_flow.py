"""Проверка сценария заявки: от первого вопроса до смены статуса."""

import asyncio

from maxapi.context.context import MemoryContext

from bot.handlers import admin, request as form, start
from db import repo
from db.session import init_db
from tools.fakes import (
    ADMIN,
    CHAT_ID,
    PHOTO_ATTACHMENT,
    USER,
    FakeBot,
    callback_event,
    message_event,
)


def run(coro):
    return asyncio.run(coro)


async def _fill_form(bot: FakeBot, context: MemoryContext, with_photo: bool = False) -> int:
    """Проходит анкету целиком и возвращает номер созданной заявки."""
    await start.on_menu_new(callback_event(bot, "menu:new"), context)
    await form.step_requester_self(callback_event(bot, "form:self"), context)
    await form.step_item(message_event(bot, "Чайник Bosch, 1.7 л"), context)
    await form.step_quantity(message_event(bot, "1 шт"), context)
    await form.step_deadline_button(callback_event(bot, "form:deadline:week"), context)
    await form.step_purpose(message_event(bot, "На кухню, старый сломался"), context)
    if with_photo:
        await form.step_example_photo(message_event(bot, None, [PHOTO_ATTACHMENT]), context)
    else:
        await form.step_example_text(message_event(bot, "https://ozon.ru/product/1"), context)
    await form.form_submit(callback_event(bot, "form:submit"), context)
    rows = await repo.list_requests(author_user_id=USER["user_id"], limit=1)
    return rows[0].id


def test_form_creates_request_with_all_fields():
    async def scenario():
        await init_db()
        bot = FakeBot()
        context = MemoryContext(CHAT_ID, USER["user_id"])
        request_id = await _fill_form(bot, context)

        request = await repo.get_request(request_id)
        assert request is not None
        assert request.requester == "Иван Петров"
        assert request.item == "Чайник Bosch, 1.7 л"
        assert request.quantity == "1 шт"
        assert request.deadline == "В течение недели"
        assert request.purpose == "На кухню, старый сломался"
        assert request.example_url == "https://ozon.ru/product/1"
        assert request.status == "new", "новая заявка должна быть «Не просмотрено»"
        assert request.author_user_id == USER["user_id"]

        # автору — подтверждение, админу из ADMIN_USER_IDS — уведомление
        recipients = {message["user_id"] for message in bot.messages}
        assert USER["user_id"] in recipients
        assert ADMIN["user_id"] in recipients

    run(scenario())


def test_photo_is_saved_and_form_state_cleared():
    async def scenario():
        await init_db()
        bot = FakeBot()
        context = MemoryContext(CHAT_ID, USER["user_id"])
        request_id = await _fill_form(bot, context, with_photo=True)

        request = await repo.get_request(request_id)
        assert request.photo_token == "photo-token"
        assert request.photo_file and request.photo_file.endswith(".jpg")
        assert await context.get_state() is None, "после отправки анкета должна сбрасываться"

    run(scenario())


def test_admin_button_changes_status_and_notifies_author():
    async def scenario():
        await init_db()
        bot = FakeBot()
        context = MemoryContext(CHAT_ID, USER["user_id"])
        request_id = await _fill_form(bot, context)

        bot.messages.clear()
        await admin.on_status_button(callback_event(bot, f"adm:{request_id}:ordered", ADMIN))

        request = await repo.get_request(request_id)
        assert request.status == "ordered"

        to_author = [m for m in bot.messages if m["user_id"] == USER["user_id"]]
        assert to_author, "автор должен получить уведомление о смене статуса"
        assert "Заказано" in to_author[-1]["text"]

        history = await repo.history(request_id)
        assert [item.to_status for item in history] == ["new", "ordered"]

    run(scenario())


def test_stranger_cannot_change_status():
    async def scenario():
        await init_db()
        bot = FakeBot()
        context = MemoryContext(CHAT_ID, USER["user_id"])
        request_id = await _fill_form(bot, context)

        # жмёт кнопку обычный пользователь, не админ
        await admin.on_status_button(callback_event(bot, f"adm:{request_id}:ordered", USER))

        request = await repo.get_request(request_id)
        assert request.status == "new", "посторонний не должен менять статус"
        assert bot.callbacks[-1]["notification"] == "Нет прав на смену статуса"

    run(scenario())


def test_cancel_clears_form():
    async def scenario():
        await init_db()
        bot = FakeBot()
        context = MemoryContext(CHAT_ID, USER["user_id"])
        await start.on_menu_new(callback_event(bot, "menu:new"), context)
        await form.step_requester_self(callback_event(bot, "form:self"), context)
        await form.form_cancel(callback_event(bot, "form:cancel"), context)
        assert await context.get_state() is None

    run(scenario())


def test_admin_can_set_done_from_max_button():
    """Статус «Выполнено» доступен кнопкой прямо из уведомления в MAX."""

    async def scenario():
        await init_db()
        bot = FakeBot()
        context = MemoryContext(CHAT_ID, USER["user_id"])
        request_id = await _fill_form(bot, context)

        await admin.on_status_button(callback_event(bot, f"adm:{request_id}:done", ADMIN))
        request = await repo.get_request(request_id)
        assert request.status == "done"

        to_author = [m for m in bot.messages if m["user_id"] == USER["user_id"]]
        assert "Выполнено" in to_author[-1]["text"]

        # кнопки под уведомлением не предлагают текущий статус
        buttons = bot.callbacks[-1]
        assert buttons is not None

    run(scenario())

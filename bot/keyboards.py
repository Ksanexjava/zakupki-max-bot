"""Клавиатуры бота и payload-константы кнопок."""

from maxapi.enums.intent import Intent
from maxapi.types.attachments.buttons.callback_button import CallbackButton
from maxapi.types.attachments.buttons.link_button import LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bot.texts import DEADLINE_CHOICES
from core.statuses import QUICK_STATUSES, STATUSES

# --- payload кнопок ---
MENU_NEW = "menu:new"
MENU_MY = "menu:my"

FORM_SELF = "form:self"
FORM_OTHER = "form:other"
FORM_SKIP = "form:skip"
FORM_SUBMIT = "form:submit"
FORM_RESTART = "form:restart"
FORM_CANCEL = "form:cancel"
FORM_DEADLINE = "form:deadline"      # form:deadline:<ключ>

ADMIN_STATUS = "adm"                  # adm:<id заявки>:<статус>


def _markup(builder: InlineKeyboardBuilder) -> list:
    """Клавиатура в формате attachments=[...] для answer()/edit()."""
    return [builder.as_markup()]


def main_menu_kb() -> list:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="📝 Создать заявку", payload=MENU_NEW, intent=Intent.POSITIVE))
    kb.row(CallbackButton(text="📋 Мои заявки", payload=MENU_MY))
    return _markup(kb)


def cancel_kb() -> list:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="❌ Отмена", payload=FORM_CANCEL, intent=Intent.NEGATIVE))
    return _markup(kb)


def requester_kb(name: str) -> list:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text=f"Это я: {name}"[:128], payload=FORM_SELF, intent=Intent.POSITIVE))
    kb.row(CallbackButton(text="Это не я", payload=FORM_OTHER))
    kb.row(CallbackButton(text="❌ Отмена", payload=FORM_CANCEL, intent=Intent.NEGATIVE))
    return _markup(kb)


def deadline_kb() -> list:
    kb = InlineKeyboardBuilder()
    for key, title in DEADLINE_CHOICES.items():
        kb.row(CallbackButton(text=title, payload=f"{FORM_DEADLINE}:{key}"))
    kb.row(CallbackButton(text="❌ Отмена", payload=FORM_CANCEL, intent=Intent.NEGATIVE))
    return _markup(kb)


def example_kb() -> list:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="⏭ Пропустить", payload=FORM_SKIP))
    kb.row(CallbackButton(text="❌ Отмена", payload=FORM_CANCEL, intent=Intent.NEGATIVE))
    return _markup(kb)


def confirm_kb() -> list:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="✅ Отправить", payload=FORM_SUBMIT, intent=Intent.POSITIVE))
    kb.row(CallbackButton(text="✏️ Заполнить заново", payload=FORM_RESTART))
    kb.row(CallbackButton(text="❌ Отмена", payload=FORM_CANCEL, intent=Intent.NEGATIVE))
    return _markup(kb)


def admin_request_kb(request_id: int, current_status: str, panel_url: str = "") -> list:
    """Кнопки под уведомлением админу: быстрая смена статуса + ссылка на панель."""
    kb = InlineKeyboardBuilder()
    buttons = [
        CallbackButton(
            text=f"{STATUSES[key]['emoji']} {STATUSES[key]['label']}",
            payload=f"{ADMIN_STATUS}:{request_id}:{key}",
            intent=Intent.POSITIVE if key == "ordered" else Intent.DEFAULT,
        )
        for key in QUICK_STATUSES
        if key != current_status
    ]
    for index in range(0, len(buttons), 2):
        kb.row(*buttons[index:index + 2])
    if panel_url:
        kb.row(LinkButton(text="🔗 Открыть панель", url=panel_url))
    return _markup(kb)

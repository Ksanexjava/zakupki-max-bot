"""Статусы заявок — единый справочник для бота и панели."""

STATUSES: dict[str, dict[str, str]] = {
    "new": {"label": "Не просмотрено", "emoji": "🆕"},
    "in_progress": {"label": "В работе", "emoji": "⚙️"},
    "clarify": {"label": "На уточнении", "emoji": "❓"},
    "ordered": {"label": "Заказано", "emoji": "✅"},
    "done": {"label": "Выполнено", "emoji": "🏁"},
}

DEFAULT_STATUS = "new"

#: статусы, которые можно поставить кнопкой прямо из уведомления в MAX
QUICK_STATUSES = ("in_progress", "clarify", "ordered", "done")


def is_valid(status: str) -> bool:
    return status in STATUSES


def label(status: str) -> str:
    """«⚙️ В работе» — для текстов бота."""
    meta = STATUSES.get(status)
    return f"{meta['emoji']} {meta['label']}" if meta else status

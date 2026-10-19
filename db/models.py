"""Модели SQLAlchemy: заявки, история статусов, администраторы."""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.statuses import DEFAULT_STATUS


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class Base(DeclarativeBase):
    pass


class Request(Base):
    """Заявка на закупку."""

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    status: Mapped[str] = mapped_column(String(32), default=DEFAULT_STATUS, index=True)

    # то, что заполняет работник
    requester: Mapped[str] = mapped_column(String(300))
    item: Mapped[str] = mapped_column(String(600))
    quantity: Mapped[str] = mapped_column(String(200), default="")
    deadline: Mapped[str] = mapped_column(String(200), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    example_url: Mapped[str | None] = mapped_column(Text, default=None)
    photo_token: Mapped[str | None] = mapped_column(Text, default=None)
    photo_file: Mapped[str | None] = mapped_column(String(200), default=None)

    # кто отправил
    author_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    author_name: Mapped[str | None] = mapped_column(String(300), default=None)
    author_username: Mapped[str | None] = mapped_column(String(200), default=None)
    author_chat_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # что добавили закупки
    admin_comment: Mapped[str | None] = mapped_column(Text, default=None)

    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="Attachment.id",
        lazy="selectin",
    )

    history: Mapped[list["StatusHistory"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="StatusHistory.id",
        lazy="selectin",
    )

    __table_args__ = (Index("idx_requests_created", "created_at"),)


class StatusHistory(Base):
    """Запись в истории: кто, когда и как изменил заявку."""

    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(200))
    from_status: Mapped[str | None] = mapped_column(String(32), default=None)
    to_status: Mapped[str | None] = mapped_column(String(32), default=None)
    comment: Mapped[str | None] = mapped_column(Text, default=None)

    request: Mapped[Request] = relationship(back_populates="history")


class Attachment(Base):
    """Скриншот, приложенный к заявке в панели (чек, корзина, карточка товара)."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(200))
    original_name: Mapped[str | None] = mapped_column(String(300), default=None)
    uploaded_by: Mapped[str] = mapped_column(String(200), default="panel")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped[Request] = relationship(back_populates="attachments")


class Admin(Base):
    """Пользователь MAX, которому бот шлёт уведомления о новых заявках."""

    __tablename__ = "admins"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(300), default=None)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

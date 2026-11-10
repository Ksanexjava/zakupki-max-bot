"""Модели SQLAlchemy: заявки, история статусов, администраторы."""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
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
    # item и quantity оставлены как заголовок заявки — это первая позиция.
    # Сами позиции лежат в таблице items, их может быть несколько.
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

    #: автору уже написали, что заказ приехал на склад
    arrived_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list["Item"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="Item.position",
        lazy="selectin",
    )

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


class Item(Base):
    """Позиция заявки: один товар со своим количеством, ссылкой и фото."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=1)

    name: Mapped[str] = mapped_column(String(600))
    quantity: Mapped[str] = mapped_column(String(200), default="")
    link: Mapped[str | None] = mapped_column(Text, default=None)
    photo_token: Mapped[str | None] = mapped_column(Text, default=None)
    photo_file: Mapped[str | None] = mapped_column(String(200), default=None)

    #: количество числом — нужно складу, чтобы считать «принято 7 из 10»
    qty_number: Mapped[float | None] = mapped_column(Float, default=None)
    qty_unit: Mapped[str] = mapped_column(String(30), default="")

    #: товар из справочника; подбирается по названию при первой приёмке
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), default=None, index=True
    )
    #: складской номер вида ZK-12-03 — он же на наклейке с QR
    stock_code: Mapped[str | None] = mapped_column(String(40), default=None, index=True)

    #: отметка «куплено» — ставится в панели, статус заявки при этом не меняется
    bought: Mapped[bool] = mapped_column(Boolean, default=False)
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    #: склад закрыл позицию по приходу / по выдаче
    received_done: Mapped[bool] = mapped_column(Boolean, default=False)
    issued_done: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped["Product | None"] = relationship(lazy="joined")
    movements: Mapped[list["Movement"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="Movement.id",
        lazy="selectin",
    )

    request: Mapped[Request] = relationship(back_populates="items")


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


class Employee(Base):
    """Сотрудник: кто принимает на склад и кому выдают товар."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(300))
    department: Mapped[str] = mapped_column(String(200), default="")
    #: если человек пользуется ботом — его id в MAX (пригодится мини-приложению)
    max_user_id: Mapped[int | None] = mapped_column(BigInteger, default=None, index=True)
    #: работает на складе — показывать первым в списке «кто принимает»
    is_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    """Номенклатура склада.

    Собирается сама: при первой приёмке позиции ищется товар с таким же
    названием, и либо позиция привязывается к нему, либо заводится новый.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(600))
    #: нормализованное название — по нему ищем совпадения
    norm_name: Mapped[str] = mapped_column(String(600), unique=True, index=True)
    unit: Mapped[str] = mapped_column(String(30), default="")
    #: подкатегория (или категория, если подкатегории нет)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), default=None, index=True
    )
    #: категорию выставили руками — автоклассификатор её больше не трогает
    category_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    #: поштучный учёт: None — как у категории, True/False — переопределено вручную
    serialized: Mapped[bool | None] = mapped_column(Boolean, default=None)
    #: ниже этого остатка склад подсвечивает «пора заказывать»
    min_stock: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Movement(Base):
    """Движение товара: приход на склад или выдача со склада."""

    __tablename__ = "movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: позиция заявки; пусто у движений не по заявке (инвентаризация, перемещение)
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), default=None, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), default=None, index=True
    )
    #: in — приняли, out — выдали, move — переложили, adjust — инвентаризация/списание
    kind: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float, default=0)

    #: откуда и куда. Остаток в месте = всё, что пришло туда, минус всё, что ушло
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), default=None, index=True
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), default=None, index=True
    )
    #: экземпляр крупного товара, если движение поштучное
    instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("instances.id", ondelete="SET NULL"), default=None, index=True
    )

    #: кто сделал (сотрудник склада) и под каким логином
    actor_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), default=None
    )
    actor_name: Mapped[str] = mapped_column(String(300), default="")

    #: кому выдали — заполняется только у расхода
    recipient_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), default=None
    )
    recipient_name: Mapped[str] = mapped_column(String(300), default="")

    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    item: Mapped[Item | None] = relationship(back_populates="movements")


class Category(Base):
    """Категория и подкатегория товара: «Медицина → Расходники»."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), default=None, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    #: товары этой категории по умолчанию учитываются поштучно, со своим QR
    serialized: Mapped[bool] = mapped_column(Boolean, default=False)
    #: слова, по которым товар относится к категории — через запятую
    keywords: Mapped[str] = mapped_column(Text, default="")


class Location(Base):
    """Место хранения: полка, коробка на полке или служебная зона."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: shelf — полка, box — коробка, zone — служебная зона (приёмка)
    kind: Mapped[str] = mapped_column(String(10), default="shelf")
    #: код на наклейке: SH-01, BX-001
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    #: коробка стоит на полке
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), default=None, index=True
    )
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LocationCategory(Base):
    """Назначение места: какие категории здесь хранятся."""

    __tablename__ = "location_categories"

    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )


class Instance(Base):
    """Экземпляр крупного товара — со своим QR, как инвентарный номер."""

    __tablename__ = "instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: код на наклейке: IN-00001
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    #: из какой позиции заявки пришёл; пусто — завели при инвентаризации
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), default=None
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), default=None, index=True
    )
    #: stock — на складе, issued — выдан
    status: Mapped[str] = mapped_column(String(10), default="stock")
    issued_to: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Admin(Base):
    """Пользователь MAX, которому бот шлёт уведомления о новых заявках."""

    __tablename__ = "admins"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(300), default=None)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

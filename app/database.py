"""
MySQL БД через SQLAlchemy 2 (async) + aiomysql.

Таблицы:
  users        — UserID, email, promocode, phone_num, name,
                 user_status, password, dealer
  subscriptions — SubscriptionID, name, description, price,
                  duration, status
  purchases    — PurchaseID, order_num, user_or_dealer, promocode_id,
                 commission, url, created_at, expired_at,
                 status, active_for, is_test
  promocodes   — PromoID, name, status, commission_percent
  dealers      — DealerID, user_id, commission_percent, amount, order_id
  commissions  — CommissionID, commission_percent
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer,
    Numeric, String, Text, func, text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship,
)

logger = logging.getLogger(__name__)

# ── Настройки подключения ──────────────────────────────────────────────────────

MYSQL_USER     = os.getenv("MYSQL_USER",     "fastapi")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "secret")
MYSQL_HOST     = os.getenv("MYSQL_HOST",     "db")
MYSQL_PORT     = os.getenv("MYSQL_PORT",     "3306")
MYSQL_DB       = os.getenv("MYSQL_DB",       "expresspay")

DATABASE_URL = (
    f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
)

engine              = create_async_engine(DATABASE_URL, echo=False, pool_recycle=3600)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


# ── Base ───────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── 1. Promocodes ──────────────────────────────────────────────────────────────

class Promocode(Base):
    __tablename__ = "promocodes"

    PromoID: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="Уникальный ID промокода",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Название / код промокода",
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="Active",
        comment="Active | Blocked",
    )
    commission_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True,
        comment="Процент комиссии дилера по этому промокоду",
    )

    purchases: Mapped[list["Purchase"]] = relationship(
        "Purchase", back_populates="promocode_rel",
        cascade="all, delete-orphan", lazy="selectin",
    )

    owner: Mapped[str | int] = mapped_column(
        BigInteger, ForeignKey("dealers.DealerID", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
        comment="Ссылка на аккаунт пользователя-дилера"
    )


# ── 2. Commissions ─────────────────────────────────────────────────────────────

class Commission(Base):
    __tablename__ = "commissions"

    CommissionID: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="Уникальный ID записи комиссии",
    )
    commission_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True,
        comment="Процент комиссии",
    )


# ── 3. Users ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    UserID: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="Уникальный ID пользователя",
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False,
        comment="Email пользователя",
    )
    promocode: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Промокод, использованный при регистрации",
    )
    phone_num: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Номер телефона пользователя",
    )
    name: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Имя пользователя",
    )
    user_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="Active",
        comment="Active | Blocked",
    )
    password: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Хэш пароля (bcrypt / argon2)",
    )
    dealer: Mapped[str] = mapped_column(
        String(50), nullable=False, default="User",
        comment="'User' или DealerID если пользователь является дилером",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
        comment="Дата регистрации",
    )

    purchases: Mapped[list["Purchase"]] = relationship(
        "Purchase", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin",
    )
    dealer_profile: Mapped["Dealer | None"] = relationship(
        "Dealer", back_populates="user", uselist=False, lazy="selectin",
    )


# ── 4. Subscriptions ───────────────────────────────────────────────────────────

class Subscription(Base):
    __tablename__ = "subscriptions"

    SubscriptionID: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="Уникальный ID подписки",
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Название подписки (обязательно)",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Описание подписки",
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False,
        comment="Цена подписки (обязательно)",
    )
    duration: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Длительность подписки в днях (обязательно)",
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="Active",
        comment="Active | Blocked",
    )

    purchases: Mapped[list["Purchase"]] = relationship(
        "Purchase", back_populates="subscription",
        cascade="all, delete-orphan", lazy="selectin",
    )


# ── 5. Purchases ───────────────────────────────────────────────────────────────

class Purchase(Base):
    __tablename__ = "purchases"

    PurchaseID: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="Уникальный ID покупки",
    )
    order_num: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True,
        comment="Номер заказа из Express-Pay (InvoiceNo)",
    )
    user_or_dealer: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="UserID или DealerID (зависит от наличия промокода)",
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.UserID", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Ссылка на пользователя",
    )
    subscription_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subscriptions.SubscriptionID", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Ссылка на подписку",
    )
    promocode_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promocodes.PromoID", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Ссылка на использованный промокод",
    )
    commission: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Рассчитанная сумма комиссии дилера",
    )
    url: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Ссылка на форму оплаты из Express-Pay (FormUrl)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
        comment="Дата создания заказа",
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="Дата истечения подписки",
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending",
        comment="pending | successful | cancelled | expired | ...",
    )
    active_for: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3,
        comment="Дней активности ссылки на оплату (по умолчанию 3)",
    )
    is_test: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True = тестовый платёж (startup test), не учитывается в статистике",
    )

    user: Mapped["User | None"] = relationship("User", back_populates="purchases")
    subscription: Mapped["Subscription | None"] = relationship(
        "Subscription", back_populates="purchases",
    )
    promocode_rel: Mapped["Promocode | None"] = relationship(
        "Promocode", back_populates="purchases",
    )


# ── 6. Dealers ─────────────────────────────────────────────────────────────────

class Dealer(Base):
    __tablename__ = "dealers"

    DealerID: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
        comment="Уникальный ID дилера",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.UserID", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
        comment="Ссылка на аккаунт пользователя-дилера",
    )
    commission_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True,
        comment="Индивидуальный процент комиссии дилера",
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Накопленная сумма комиссии: цена_подписки * (commission_percent / 100)",
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("purchases.PurchaseID", ondelete="SET NULL"),
        nullable=True,
        comment="Ссылка на последний заказ дилера",
    )

    user: Mapped["User"] = relationship("User", back_populates="dealer_profile")


# ── Утилиты ────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Создаёт все таблицы и применяет миграции для существующих таблиц."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_users(conn)
        await _migrate_payments(conn)


async def _migrate_users(conn) -> None:
    """Добавляет новые колонки в таблицу users (если отсутствуют)."""
    existing = {row[0] for row in await conn.execute(
        text("SHOW COLUMNS FROM users")
    )}
    migrations = [
        ("promocode",    "VARCHAR(100) NULL COMMENT 'Промокод при регистрации'"),
        ("phone_num",    "VARCHAR(50) NULL COMMENT 'Номер телефона'"),
        ("name",         "VARCHAR(255) NULL COMMENT 'Имя пользователя'"),
        ("user_status",  "VARCHAR(10) NOT NULL DEFAULT 'Active' COMMENT 'Active | Blocked'"),
        ("password",     "VARCHAR(255) NULL COMMENT 'Хэш пароля'"),
        ("dealer",       "VARCHAR(50) NOT NULL DEFAULT 'User' COMMENT 'User или DealerID'"),
    ]
    for col, definition in migrations:
        if col not in existing:
            await conn.execute(text(f"ALTER TABLE users ADD COLUMN `{col}` {definition}"))
            logger.info(f"✅ Миграция users: добавлена колонка {col}")


async def _migrate_payments(conn) -> None:
    """Добавляет колонку is_test в таблицу payments (если отсутствует)."""
    # Проверяем существование таблицы
    tables = {row[0] for row in await conn.execute(
        text("SHOW TABLES LIKE 'payments'")
    )}
    if "payments" not in tables:
        return
    existing = {row[0] for row in await conn.execute(
        text("SHOW COLUMNS FROM payments")
    )}
    if "is_test" not in existing:
        await conn.execute(text(
            "ALTER TABLE payments ADD COLUMN `is_test` TINYINT(1) NOT NULL DEFAULT 0 "
            "COMMENT 'True = тестовый платёж'"
        ))
        logger.info("✅ Миграция payments: добавлена колонка is_test")


async def get_db() -> AsyncSession:
    """FastAPI-зависимость для получения сессии БД."""
    async with async_session_maker() as session:
        yield session


def calc_expired_at(duration_days: int | None) -> datetime | None:
    """Вычисляет дату истечения подписки по длительности в днях (Минск, UTC+3)."""
    if not duration_days:
        return None
    # Локальное время Минска как UTC+3 без таймзоны
    return datetime.utcnow() + timedelta(hours=3, days=duration_days)


def calc_link_expires_at(active_for_days: int = 3) -> datetime:
    """Вычисляет дату истечения ссылки на оплату (по умолчанию 3 дня, Минск, UTC+3)."""
    return datetime.utcnow() + timedelta(hours=3, days=active_for_days)


def calc_dealer_amount(price: Decimal, commission_percent: Decimal) -> Decimal:
    """Рассчитывает сумму комиссии дилера: price * (commission_percent / 100)."""
    return round(price * commission_percent / Decimal("100"), 2)

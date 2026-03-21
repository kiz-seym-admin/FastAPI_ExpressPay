"""
MySQL БД через SQLAlchemy 2 (async) + aiomysql.

Таблицы:
  users    — UserID, email, first_name, last_name, phone, created_at
  payments — PaymentID, OrderNum, UserID (FK), SubscriptionID,
             FormURL, Status, created_at, expired_at

Все платежи пользователя доступны через relationship user.payments.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import (
    BigInteger, String, Integer, DateTime,
    ForeignKey, func, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import os

# ── Строка подключения берётся из .env ────────────────────────────────────────
MYSQL_USER     = os.getenv("MYSQL_USER",     "fastapi")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "secret")
MYSQL_HOST     = os.getenv("MYSQL_HOST",     "db")
MYSQL_PORT     = os.getenv("MYSQL_PORT",     "3306")
MYSQL_DB       = os.getenv("MYSQL_DB",       "expresspay")

DATABASE_URL = (
    f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_recycle=3600)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ── USERS ─────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    UserID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Все платежи пользователя (один ко многим)
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ── PAYMENTS ──────────────────────────────────────────────────────────────────
class Payment(Base):
    """
    OrderNum   — номер заказа из Express-Pay (InvoiceNo / tracking_id)
    FormURL    — ссылка на страницу оплаты (FormUrl из ответа EP)
    Status     — строковый статус: pending / successful / cancelled / ...
    expired_at — дата истечения подписки (created_at + duration_weeks курса)
    """
    __tablename__ = "payments"

    PaymentID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    OrderNum: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True,
                                          comment="tracking_id / InvoiceNo из Express-Pay")
    UserID: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.UserID", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    SubscriptionID: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
        comment="ID курса/подписки из courses.json"
    )
    FormURL: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="FormUrl из ответа Express-Pay — ссылка на оплату"
    )
    Status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending",
        comment="pending / successful / cancelled / refunded / declined / expired"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="Дата истечения подписки = created_at + duration_weeks курса"
    )

    # Обратная связь к пользователю
    user: Mapped["User"] = relationship("User", back_populates="payments")


# ── Утилиты ───────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Создаёт таблицы если не существуют. Вызывается в lifespan FastAPI."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """FastAPI Dependency — выдаёт async-сессию на время запроса."""
    async with async_session_maker() as session:
        yield session


def calc_expired_at(duration_weeks: int | None) -> datetime | None:
    """Вычисляет дату истечения подписки от текущего момента."""
    if not duration_weeks:
        return None
    return datetime.now() + timedelta(weeks=duration_weeks)

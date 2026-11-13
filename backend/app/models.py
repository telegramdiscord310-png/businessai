"""Modèles de données."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Date toujours stockée et relue en UTC avec fuseau (même sous SQLite pour les tests)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WebSession(Base):
    __tablename__ = "web_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


class TelegramAccount(Base):
    """Compte Telegram personnel (une seule ligne, id = 1)."""

    __tablename__ = "telegram_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_id: Mapped[int | None] = mapped_column(BigInteger)
    api_hash_enc: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(32))
    session_enc: Mapped[str | None] = mapped_column(Text)
    # disconnected | code_sent | password_needed | connecting | connected | error
    status: Mapped[str] = mapped_column(String(24), default="disconnected")
    last_error: Mapped[str | None] = mapped_column(Text)
    me_id: Mapped[int | None] = mapped_column(BigInteger)
    me_name: Mapped[str | None] = mapped_column(String(255))
    me_username: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Chat(Base):
    """Conversation privée ; l'identifiant est l'ID Telegram de l'interlocuteur."""

    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    access_hash: Mapped[int | None] = mapped_column(BigInteger)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    has_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_reason: Mapped[str | None] = mapped_column(String(32))
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    last_message_text: Mapped[str | None] = mapped_column(String(255))
    last_message_sender: Mapped[str | None] = mapped_column(String(16))
    first_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    history_imported_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @property
    def display_name(self) -> str:
        name = " ".join(p for p in (self.first_name, self.last_name) if p).strip()
        return name or (f"@{self.username}" if self.username else f"Utilisateur {self.id}")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "tg_message_id", name="uq_messages_chat_tg"),
        Index("ix_messages_chat_id_id", "chat_id", "id"),
        Index("ix_messages_sender_created", "sender", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    sender: Mapped[str] = mapped_column(String(16))  # client | ai | owner | system
    kind: Mapped[str] = mapped_column(String(24), default="text")  # text | media | payment_link | delivery
    text: Mapped[str] = mapped_column(Text, default="")
    media_type: Mapped[str | None] = mapped_column(String(32))
    media_desc: Mapped[str | None] = mapped_column(String(255))
    media_path: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="sent")  # sent | draft | discarded | failed
    # Pour un message reçu : True dès qu'une réponse (IA ou manuelle) l'a pris en compte.
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Pack(Base):
    __tablename__ = "packs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    price_stars: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_link: Mapped[str | None] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    files: Mapped[list[PackFile]] = relationship(
        back_populates="pack", cascade="all, delete-orphan", order_by="PackFile.id", lazy="selectin"
    )


class PackFile(Base):
    __tablename__ = "pack_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mime: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    pack: Mapped[Pack] = relationship(back_populates="files")


class Invoice(Base):
    """Lien de facture en Stars créé pour un acheteur et un pack précis."""

    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    buyer_tg_id: Mapped[int] = mapped_column(BigInteger)
    price_stars: Mapped[int] = mapped_column(Integer)
    link: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="created")  # created | paid
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    pack_id: Mapped[int | None] = mapped_column(ForeignKey("packs.id"), index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    buyer_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    stars: Mapped[int] = mapped_column(Integer)
    # Identifiant de paiement Telegram : unique, garantit qu'un paiement n'est enregistré qu'une fois.
    telegram_payment_charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(255))
    paid_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    # pending | delivering | delivered | failed
    delivery_status: Mapped[str] = mapped_column(String(16), default="pending")
    delivery_step: Mapped[int] = mapped_column(Integer, default=0)
    delivery_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    refunded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    pack: Mapped[Pack | None] = relationship(lazy="joined")


class LogEntry(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(16))  # site | telegram
    logger: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)

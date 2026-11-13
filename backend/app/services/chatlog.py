"""Enregistrement des conversations et des messages, et envoi sérialisé par conversation."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..events import EventBus
from ..models import Chat, Message, utcnow

log = logging.getLogger("app.chat")


@dataclass
class PeerInfo:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    access_hash: int | None = None
    is_bot: bool = False
    is_self: bool = False
    is_service_account: bool = False  # ex. 777000 (notifications Telegram), support


class Transport(Protocol):
    """Ce que le userbot sait faire. Remplacé par un faux transport dans les tests."""

    async def send_text(self, chat_id: int, text: str) -> int: ...
    async def send_file(self, chat_id: int, path: str, filename: str | None = None, caption: str | None = None) -> int: ...
    async def typing(self, chat_id: int, seconds: float) -> None: ...
    async def mark_read(self, chat_id: int) -> None: ...


def preview(text: str, media_desc: str | None = None, limit: int = 120) -> str:
    base = " ".join((text or "").split())
    if media_desc and not base:
        base = media_desc
    elif media_desc:
        base = f"{media_desc} · {base}"
    return base[:limit]


async def upsert_chat(session: AsyncSession, peer: PeerInfo) -> Chat:
    chat = await session.get(Chat, peer.id)
    if chat is None:
        chat = Chat(id=peer.id, unread_count=0, ai_enabled=True, ai_paused=False, has_photo=False)
        session.add(chat)
    if peer.first_name is not None or peer.last_name is not None or peer.username is not None:
        chat.first_name = (peer.first_name or "")[:128] or None
        chat.last_name = (peer.last_name or "")[:128] or None
        chat.username = (peer.username or "")[:64] or None
    if peer.access_hash is not None:
        chat.access_hash = peer.access_hash
    return chat


async def add_message(
    session: AsyncSession,
    chat: Chat,
    *,
    direction: str,
    sender: str,
    text: str = "",
    kind: str = "text",
    tg_message_id: int | None = None,
    media_type: str | None = None,
    media_desc: str | None = None,
    status: str = "sent",
    meta: dict | None = None,
    created_at: datetime | None = None,
    answered: bool = False,
    touch_chat: bool = True,
) -> Message | None:
    """Ajoute un message. Renvoie None s'il est déjà connu (même identifiant Telegram)."""
    if tg_message_id is not None:
        known = await session.scalar(
            select(Message.id).where(Message.chat_id == chat.id, Message.tg_message_id == tg_message_id)
        )
        if known is not None:
            return None
    created_at = created_at or utcnow()
    msg = Message(
        chat_id=chat.id,
        tg_message_id=tg_message_id,
        direction=direction,
        sender=sender,
        kind=kind,
        text=text or "",
        media_type=media_type,
        media_desc=media_desc,
        status=status,
        meta=meta,
        created_at=created_at,
        answered=answered or direction == "out",
    )
    session.add(msg)
    if touch_chat and status == "sent":
        if chat.last_message_at is None or created_at >= chat.last_message_at:
            chat.last_message_at = created_at
            chat.last_message_text = preview(text, media_desc)
            chat.last_message_sender = sender
        if direction == "in":
            chat.unread_count = (chat.unread_count or 0) + 1
            if chat.first_message_at is None or created_at < chat.first_message_at:
                chat.first_message_at = created_at
    await session.flush()
    return msg


async def mark_answered(session: AsyncSession, chat_id: int, upto_id: int | None = None) -> None:
    stmt = update(Message).where(Message.chat_id == chat_id, Message.direction == "in", Message.answered.is_(False))
    if upto_id is not None:
        stmt = stmt.where(Message.id <= upto_id)
    await session.execute(stmt.values(answered=True))


async def discard_drafts(session: AsyncSession, chat_id: int) -> None:
    await session.execute(
        update(Message).where(Message.chat_id == chat_id, Message.status == "draft").values(status="discarded")
    )


class Outbox:
    """Point de passage unique pour tout message sortant du userbot.

    Un verrou par conversation sérialise les envois et permet de distinguer, sans ambiguïté,
    les messages envoyés par l'application de ceux que le propriétaire écrit depuis Telegram.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], transport: Transport, bus: EventBus):
        self.sessionmaker = sessionmaker
        self.transport = transport
        self.bus = bus
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._own: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=200))

    def lock(self, chat_id: int) -> asyncio.Lock:
        return self._locks[chat_id]

    def is_own(self, chat_id: int, tg_message_id: int) -> bool:
        return tg_message_id in self._own[chat_id]

    async def send(
        self,
        chat_id: int,
        *,
        sender: str,
        text: str = "",
        kind: str = "text",
        file_path: str | None = None,
        filename: str | None = None,
        meta: dict | None = None,
        draft_id: int | None = None,
        pause_ai: bool = False,
        answer_upto: int | None = None,
        answer_all: bool = False,
        locked: bool = False,
    ) -> Message:
        """Envoie puis enregistre un message. `locked=True` si l'appelant tient déjà le verrou."""
        if locked:
            return await self._send(chat_id, sender, text, kind, file_path, filename, meta, draft_id, pause_ai, answer_upto, answer_all)
        async with self._locks[chat_id]:
            return await self._send(chat_id, sender, text, kind, file_path, filename, meta, draft_id, pause_ai, answer_upto, answer_all)

    async def _send(self, chat_id, sender, text, kind, file_path, filename, meta, draft_id, pause_ai, answer_upto, answer_all) -> Message:
        if file_path:
            tg_id = await self.transport.send_file(chat_id, file_path, filename=filename, caption=text or None)
        else:
            tg_id = await self.transport.send_text(chat_id, text)
        self._own[chat_id].append(tg_id)
        async with self.sessionmaker() as session:
            chat = await session.get(Chat, chat_id)
            if chat is None:
                chat = await upsert_chat(session, PeerInfo(id=chat_id))
            now = utcnow()
            media_type = "document" if file_path else None
            media_desc = f"Fichier : {filename}" if file_path and filename else ("Fichier" if file_path else None)
            msg: Message | None = None
            if draft_id is not None:
                msg = await session.get(Message, draft_id)
            if msg is not None:
                msg.text, msg.status, msg.tg_message_id, msg.created_at = text, "sent", tg_id, now
                msg.sender, msg.kind = sender, kind
                chat.last_message_at, chat.last_message_text, chat.last_message_sender = now, preview(text), sender
            else:
                msg = await add_message(
                    session, chat, direction="out", sender=sender, text=text, kind=kind, tg_message_id=tg_id,
                    media_type=media_type, media_desc=media_desc, meta=meta, created_at=now,
                )
                if msg is None:
                    # Identifiant Telegram déjà connu (cas rare) : on reprend le message existant
                    # plutôt que d'interrompre l'envoi en cours.
                    msg = await session.scalar(
                        select(Message).where(Message.chat_id == chat_id, Message.tg_message_id == tg_id)
                    )
            if answer_all:
                await mark_answered(session, chat_id)
            elif answer_upto is not None:
                await mark_answered(session, chat_id, answer_upto)
            if pause_ai:
                chat.ai_paused, chat.paused_reason = True, "manual"
                await discard_drafts(session, chat_id)
            await session.commit()
        await self.bus.publish("message", chat_id=chat_id, message_id=msg.id)
        return msg


async def resume_ai(session: AsyncSession, chat_id: int | None = None) -> None:
    """Réactive l'IA (sur une conversation, ou partout si chat_id est None) sans provoquer de relance :
    les messages reçus pendant la pause sont considérés comme traités. L'IA ne répondra qu'au
    prochain message reçu."""
    stmt = update(Message).where(Message.direction == "in", Message.answered.is_(False))
    if chat_id is not None:
        stmt = stmt.where(Message.chat_id == chat_id)
        chat = await session.get(Chat, chat_id)
        if chat is not None:
            chat.ai_paused, chat.paused_reason = False, None
    await session.execute(stmt.values(answered=True))


async def import_history(session: AsyncSession, chat: Chat, items: list[dict]) -> int:
    """Ajoute des messages anciens (du plus ancien au plus récent) sans rien déclencher :
    ni réponse de l'IA, ni compteur de non-lus. Renvoie le nombre de messages ajoutés."""
    added = 0
    for item in items:
        msg = await add_message(
            session, chat,
            direction="out" if item["out"] else "in",
            sender="owner" if item["out"] else "client",
            text=item.get("text") or "",
            kind="media" if item.get("media_type") else "text",
            tg_message_id=item["tg_message_id"],
            media_type=item.get("media_type"), media_desc=item.get("media_desc"),
            created_at=item["date"], answered=True, touch_chat=False,
            meta={"imported": True},
        )
        if msg is None:
            continue
        added += 1
        if not item["out"] and (chat.first_message_at is None or item["date"] < chat.first_message_at):
            chat.first_message_at = item["date"]
        if chat.last_message_at is None or item["date"] > chat.last_message_at:
            chat.last_message_at = item["date"]
            chat.last_message_text = preview(msg.text, msg.media_desc)
            chat.last_message_sender = msg.sender
    chat.history_imported_at = utcnow()
    return added

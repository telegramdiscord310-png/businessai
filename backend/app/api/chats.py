from __future__ import annotations

import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_session
from ..models import Chat, Message, Sale
from ..security import require_auth
from ..services.chatlog import resume_ai
from ..services.stats import eur
from ..settings_store import load_settings
from ..worker_client import call_worker
from .serializers import chat_out, message_out, sale_out

router = APIRouter(prefix="/api", tags=["conversations"], dependencies=[Depends(require_auth)])


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class ChatPatch(BaseModel):
    ai_enabled: bool | None = None
    ai_paused: bool | None = None


class ApproveIn(BaseModel):
    text: str | None = Field(default=None, max_length=4096)


class ImportIn(BaseModel):
    limit: int = Field(default=300, ge=1, le=3000)


async def get_chat(session: AsyncSession, chat_id: int) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(404, "Conversation introuvable.")
    return chat


@router.get("/chats")
async def list_chats(search: str = Query(default="", max_length=64), limit: int = Query(default=300, ge=1, le=1000), session: AsyncSession = Depends(get_session)):
    stmt = select(Chat)
    term = search.strip().lstrip("@")
    if term:
        like = f"%{term.lower()}%"
        full = func.lower(func.coalesce(Chat.first_name, "") + " " + func.coalesce(Chat.last_name, ""))
        stmt = stmt.where(or_(full.like(like), func.lower(func.coalesce(Chat.username, "")).like(like)))
    chats = (await session.scalars(stmt.order_by(Chat.last_message_at.desc().nulls_last(), Chat.id).limit(limit))).all()
    drafts = set((await session.scalars(select(Message.chat_id).where(Message.status == "draft"))).all())
    buyers = set((await session.scalars(select(Sale.chat_id).where(Sale.refunded_at.is_(None)))).all())
    return [chat_out(c, has_draft=c.id in drafts, is_buyer=c.id in buyers) for c in chats]


@router.get("/chats/{chat_id}")
async def chat_detail(chat_id: int, session: AsyncSession = Depends(get_session)):
    """Conversation + fiche client (total dépensé, packs achetés, premier message)."""
    chat = await get_chat(session, chat_id)
    settings = await load_settings(session)
    rate = float(settings.stars_eur_rate)
    sales = (await session.scalars(select(Sale).where(Sale.chat_id == chat_id).order_by(Sale.paid_at.desc()))).all()
    spent = sum(s.stars for s in sales if s.refunded_at is None)
    messages = await session.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chat_id, Message.status == "sent")) or 0
    has_draft = bool(await session.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chat_id, Message.status == "draft")))
    return {
        **chat_out(chat, has_draft=has_draft, is_buyer=spent > 0),
        "customer": {
            "total_stars": spent,
            "total_eur": eur(spent, rate),
            "purchases": [sale_out(s, rate, chat) for s in sales],
            "messages_count": messages,
            "first_message_at": chat.first_message_at,
        },
    }


@router.get("/chats/{chat_id}/messages")
async def list_messages(
    chat_id: int, limit: int = Query(default=80, ge=1, le=300), before_id: int | None = None, session: AsyncSession = Depends(get_session)
):
    await get_chat(session, chat_id)
    stmt = select(Message).where(Message.chat_id == chat_id, Message.status.in_(("sent", "draft")))
    if before_id is not None:
        ref = await session.get(Message, before_id)
        if ref is not None:
            stmt = stmt.where(or_(Message.created_at < ref.created_at, and_(Message.created_at == ref.created_at, Message.id < ref.id)))
    rows = (await session.scalars(stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1))).all()
    has_more = len(rows) > limit
    return {"messages": [message_out(m) for m in reversed(rows[:limit])], "has_more": has_more}


@router.post("/chats/{chat_id}/messages")
async def send_message(chat_id: int, body: SendIn, session: AsyncSession = Depends(get_session)):
    """Réponse manuelle depuis le site : envoyée par le userbot, et l'IA se met en pause sur ce chat."""
    await get_chat(session, chat_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Le message est vide.")
    return await call_worker("POST", "/telegram/send", {"chat_id": chat_id, "text": text})


@router.post("/chats/{chat_id}/read")
async def mark_read(chat_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    chat = await get_chat(session, chat_id)
    if chat.unread_count:
        chat.unread_count = 0
        await session.commit()
        await request.app.state.bus.publish("chat", chat_id=chat_id)
    return {"ok": True}


@router.patch("/chats/{chat_id}")
async def patch_chat(chat_id: int, body: ChatPatch, request: Request, session: AsyncSession = Depends(get_session)):
    chat = await get_chat(session, chat_id)
    if body.ai_enabled is not None:
        chat.ai_enabled = body.ai_enabled
    if body.ai_paused is True:
        chat.ai_paused, chat.paused_reason = True, "site"
    if body.ai_paused is False or body.ai_enabled is True:
        # Réactivation : l'IA reprendra au prochain message reçu, sans relancer la personne.
        await resume_ai(session, chat_id)
    await session.commit()
    await request.app.state.bus.publish("chat", chat_id=chat_id)
    return chat_out(chat)


@router.post("/chats/{chat_id}/import-history")
async def import_history(chat_id: int, body: ImportIn, session: AsyncSession = Depends(get_session)):
    await get_chat(session, chat_id)
    return await call_worker("POST", "/telegram/import_history", {"chat_id": chat_id, "limit": body.limit}, timeout=180)


@router.get("/chats/{chat_id}/avatar")
async def avatar(chat_id: int):
    path = os.path.join(get_config().data_dir, "avatars", f"{chat_id}.jpg")
    if not os.path.isfile(path):
        raise HTTPException(404, "Pas de photo de profil.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/messages/{message_id}/media")
async def message_media(message_id: int, session: AsyncSession = Depends(get_session)):
    message = await session.get(Message, message_id)
    if message is None or not message.media_path:
        raise HTTPException(404, "Pièce jointe introuvable.")
    root = os.path.realpath(os.path.join(get_config().data_dir, "media"))
    path = os.path.realpath(os.path.join(get_config().data_dir, message.media_path))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        raise HTTPException(404, "Pièce jointe introuvable.")
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # Seuls les images, sons et vidéos s'affichent dans la page ; le reste est proposé en téléchargement.
    inline = mime.startswith(("image/", "audio/", "video/")) and mime != "image/svg+xml"
    return FileResponse(
        path, media_type=mime if inline else "application/octet-stream",
        content_disposition_type="inline" if inline else "attachment", filename=os.path.basename(path),
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/drafts/{message_id}/approve")
async def approve_draft(message_id: int, body: ApproveIn):
    return await call_worker("POST", f"/drafts/{message_id}/approve", {"text": body.text})


@router.post("/drafts/{message_id}/discard")
async def discard_draft(message_id: int):
    return await call_worker("POST", f"/drafts/{message_id}/discard")

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Chat, Message, Pack, TelegramAccount
from ..security import require_auth
from ..services.chatlog import resume_ai
from ..settings_store import load_settings, save_settings

router = APIRouter(prefix="/api", tags=["status"], dependencies=[Depends(require_auth)])


class ToggleIn(BaseModel):
    enabled: bool


@router.get("/status")
async def status(session: AsyncSession = Depends(get_session)):
    settings = await load_settings(session)
    account = await session.get(TelegramAccount, 1)
    tg_status = account.status if account else "disconnected"
    packs = await session.scalar(select(func.count()).select_from(Pack).where(Pack.deleted_at.is_(None), Pack.active.is_(True))) or 0
    unread = await session.scalar(select(func.coalesce(func.sum(Chat.unread_count), 0))) or 0
    drafts = await session.scalar(select(func.count()).select_from(Message).where(Message.status == "draft")) or 0
    steps = {
        "telegram": tg_status == "connected",
        "ai": settings.ai_configured,
        "pack": packs > 0,
        "enabled": bool(settings.ai_enabled),
    }
    return {
        "telegram": {
            "status": tg_status,
            "name": account.me_name if account else None,
            "username": account.me_username if account else None,
            "error": account.last_error if account else None,
        },
        "ai": {"enabled": bool(settings.ai_enabled), "configured": settings.ai_configured, "draft_mode": bool(settings.draft_mode)},
        "bot": {"configured": settings.bot_configured, "username": settings.bot_username},
        "onboarding": {**steps, "done": all(steps.values())},
        "unread": int(unread),
        "drafts": int(drafts),
    }


@router.post("/ai/toggle")
async def toggle_ai(body: ToggleIn, request: Request, session: AsyncSession = Depends(get_session)):
    await save_settings(session, {"ai_enabled": body.enabled})
    if body.enabled:
        await resume_ai(session)  # pas de réponse aux anciens messages : seulement aux prochains
    await session.commit()
    await request.app.state.bus.publish("status")
    return {"enabled": body.enabled}


@router.get("/events")
async def events(request: Request):
    """Flux temps réel (SSE) : nouveaux messages, ventes, changements d'état."""
    hub = request.app.state.hub
    queue = hub.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )

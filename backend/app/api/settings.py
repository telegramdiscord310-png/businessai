from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from ..config import get_config
from ..db import get_session
from ..models import LogEntry
from ..security import require_auth
from ..settings_store import Settings, load_settings, save_settings
from ..worker_client import call_worker
from .serializers import log_out

router = APIRouter(prefix="/api", tags=["paramètres"], dependencies=[Depends(require_auth)])


class SettingsIn(BaseModel):
    draft_mode: bool
    batch_delay_seconds: float = Field(ge=0, le=120)
    typing_min_seconds: float = Field(ge=0, le=60)
    typing_max_seconds: float = Field(ge=0, le=120)
    typing_chars_per_second: float = Field(ge=1, le=200)
    mark_as_read: bool
    rate_global_per_hour: int = Field(ge=1, le=5000)
    rate_chat_per_hour: int = Field(ge=1, le=500)
    stars_eur_rate: float = Field(gt=0, le=1)
    delivery_intro: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def check_bounds(self):
        if self.typing_max_seconds < self.typing_min_seconds:
            raise ValueError("Le délai maximum doit être supérieur ou égal au délai minimum.")
        return self


class BotTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)

    @field_validator("token")
    @classmethod
    def check_format(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{5,12}:[A-Za-z0-9_-]{30,}", v):
            raise ValueError("Ce token n'a pas le bon format. Copiez-le tel que BotFather vous l'a donné (ex. 123456789:AA…).")
        return v


def settings_out(settings: Settings) -> dict:
    keys = SettingsIn.model_fields.keys()
    return {
        **{k: settings.get(k) for k in keys},
        "bot": {
            "configured": settings.bot_configured,
            "username": settings.bot_username,
            "token_hint": crypto.mask(settings.bot_token),
        },
        "timezone": get_config().timezone,
    }


@router.get("/settings")
async def get_settings(session: AsyncSession = Depends(get_session)):
    return settings_out(await load_settings(session))


@router.put("/settings")
async def put_settings(body: SettingsIn, request: Request, session: AsyncSession = Depends(get_session)):
    await save_settings(session, body.model_dump())
    await session.commit()
    await request.app.state.bus.publish("status")
    return settings_out(await load_settings(session))


@router.put("/settings/bot")
async def set_bot_token(body: BotTokenIn, request: Request, session: AsyncSession = Depends(get_session)):
    """Enregistre le token (chiffré) puis demande au worker de démarrer le bot avec."""
    previous = (await load_settings(session)).get("bot_token_enc")
    await save_settings(session, {"bot_token_enc": crypto.encrypt(body.token), "bot_username": None})
    await session.commit()
    try:
        status = await call_worker("POST", "/bot/reload", timeout=30)
    except HTTPException:
        await save_settings(session, {"bot_token_enc": previous})
        await session.commit()
        raise
    if status.get("error"):
        await save_settings(session, {"bot_token_enc": previous, "bot_username": None})
        await session.commit()
        if previous:
            await call_worker("POST", "/bot/reload", timeout=30)
        raise HTTPException(400, status["error"])
    await request.app.state.bus.publish("status")
    return settings_out(await load_settings(session))


@router.delete("/settings/bot")
async def remove_bot_token(request: Request, session: AsyncSession = Depends(get_session)):
    await save_settings(session, {"bot_token_enc": None, "bot_username": None})
    await session.commit()
    try:
        await call_worker("POST", "/bot/reload", timeout=30)
    except HTTPException:
        pass
    await request.app.state.bus.publish("status")
    return settings_out(await load_settings(session))


@router.get("/logs")
async def list_logs(
    level: str = "", source: str = "", q: str = "", before_id: int | None = None, limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(LogEntry)
    if level == "error":
        stmt = stmt.where(LogEntry.level.in_(("ERROR", "CRITICAL")))
    elif level == "warning":
        stmt = stmt.where(LogEntry.level.in_(("WARNING", "ERROR", "CRITICAL")))
    if source in ("site", "telegram"):
        stmt = stmt.where(LogEntry.source == source)
    if q.strip():
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(LogEntry.message.ilike(like), LogEntry.details.ilike(like)))
    if before_id is not None:
        stmt = stmt.where(LogEntry.id < before_id)
    limit = max(1, min(limit, 300))
    rows = (await session.scalars(stmt.order_by(LogEntry.id.desc()).limit(limit + 1))).all()
    return {"logs": [log_out(r) for r in rows[:limit]], "has_more": len(rows) > limit}


@router.delete("/logs")
async def clear_logs(session: AsyncSession = Depends(get_session)):
    await session.execute(delete(LogEntry))
    await session.commit()
    return {"ok": True}

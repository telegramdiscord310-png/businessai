from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from ..db import get_session
from ..models import Pack
from ..security import require_auth
from ..services.ai_client import AIConfig, AIError, OpenAICompatClient
from ..services.conversation import run_turn
from ..services.prompt import build_system_prompt
from ..settings_store import Settings, load_settings, save_settings

router = APIRouter(prefix="/api/ai", tags=["ia"], dependencies=[Depends(require_auth)])


class AIConfigIn(BaseModel):
    ai_base_url: str = Field(min_length=8, max_length=255)
    ai_model: str = Field(min_length=1, max_length=128)
    # Vide = conserver la clé déjà enregistrée.
    ai_api_key: str = Field(default="", max_length=512)
    ai_system_prompt: str = Field(min_length=1, max_length=8000)
    ai_never_deny_bot: bool = True
    ai_history_limit: int = Field(default=30, ge=2, le=100)
    ai_temperature: float = Field(default=0.7, ge=0, le=2)

    @field_validator("ai_base_url")
    @classmethod
    def check_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("https://", "http://")):
            raise ValueError("L'URL de base doit commencer par https://")
        return v

    @field_validator("ai_model", "ai_api_key")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class TestMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class TestIn(BaseModel):
    messages: list[TestMessage] = Field(min_length=1, max_length=40)
    config: AIConfigIn | None = None  # valeurs du formulaire non encore enregistrées


def config_out(settings: Settings) -> dict:
    return {
        "ai_base_url": settings.ai_base_url,
        "ai_model": settings.ai_model,
        "ai_api_key_set": bool(settings.get("ai_api_key_enc")),
        "ai_api_key_hint": crypto.mask(settings.ai_api_key),
        "ai_system_prompt": settings.ai_system_prompt,
        "ai_never_deny_bot": settings.ai_never_deny_bot,
        "ai_history_limit": settings.ai_history_limit,
        "ai_temperature": settings.ai_temperature,
    }


@router.get("/config")
async def get_config_(session: AsyncSession = Depends(get_session)):
    return config_out(await load_settings(session))


@router.put("/config")
async def put_config(body: AIConfigIn, request: Request, session: AsyncSession = Depends(get_session)):
    values = body.model_dump(exclude={"ai_api_key"})
    if body.ai_api_key:
        values["ai_api_key_enc"] = crypto.encrypt(body.ai_api_key)
    await save_settings(session, values)
    await session.commit()
    await request.app.state.bus.publish("status")
    return config_out(await load_settings(session))


@router.post("/test")
async def test_ai(body: TestIn, request: Request, session: AsyncSession = Depends(get_session)):
    """Simule une conversation : même prompt et mêmes outils qu'en vrai, mais rien n'est envoyé sur Telegram."""
    settings = await load_settings(session)
    values = dict(settings._values)
    api_key = settings.ai_api_key
    if body.config is not None:
        values.update(body.config.model_dump(exclude={"ai_api_key"}))
        api_key = body.config.ai_api_key or api_key
    if not api_key:
        raise HTTPException(400, "Saisissez d'abord une clé API pour tester.")
    effective = Settings(values)
    packs = list((await session.scalars(select(Pack).where(Pack.active.is_(True), Pack.deleted_at.is_(None)).order_by(Pack.id))).all())
    by_id = {p.id: p for p in packs}

    async def dry_run_tool(pack_id: int) -> tuple[bool, str]:
        pack = by_id.get(pack_id)
        if pack is None:
            return False, "Ce pack n'existe pas. Utilise uniquement un identifiant présent dans le catalogue."
        return True, f"Lien de paiement pour « {pack.name} » ({pack.price_stars} Stars) prêt : il sera envoyé automatiquement juste après ton message."

    factory = getattr(request.app.state, "ai_factory", None)
    client = factory(effective) if factory else OpenAICompatClient(
        AIConfig(base_url=effective.ai_base_url, model=effective.ai_model, api_key=api_key, temperature=float(effective.ai_temperature))
    )
    try:
        turn = await run_turn(client, build_system_prompt(effective, packs), [m.model_dump() for m in body.messages], dry_run_tool)
    except AIError as exc:
        raise HTTPException(400, str(exc))
    return {
        "reply": turn.text,
        "payment_links": [{"pack_id": pid, "name": by_id[pid].name, "price_stars": by_id[pid].price_stars} for pid in turn.pack_ids if pid in by_id],
    }

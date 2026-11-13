"""API interne du worker, appelée uniquement par le backend (réseau Docker privé + secret partagé)."""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from ..config import get_config
from ..services.payments import PaymentError
from ..services.reply_engine import EngineError
from .userbot import TgError

log = logging.getLogger("app.rpc")


class SendCodeIn(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=8, max_length=64)
    phone: str = Field(min_length=5, max_length=32)


class CodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=16)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SendIn(BaseModel):
    chat_id: int
    text: str = Field(min_length=1, max_length=4096)


class ImportIn(BaseModel):
    chat_id: int
    limit: int = Field(default=300, ge=1, le=3000)


class ApproveIn(BaseModel):
    text: str | None = Field(default=None, max_length=4096)


def check_token(x_internal_token: str = Header(default="")) -> None:
    expected = get_config().internal_token
    if not expected or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(403, "Accès interne refusé.")


def create_rpc_app(telegram, engine, paybot, payments, delivery) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(check_token)])

    async def guard(coro):
        try:
            return await coro
        except (TgError, EngineError, PaymentError) as exc:
            raise HTTPException(400, str(exc))
        except HTTPException:
            raise
        except Exception:
            log.exception("Erreur interne du worker")
            raise HTTPException(500, "Erreur interne du service Telegram. Consultez la page Logs.")

    @app.get("/health")
    async def health():
        return {"ok": True, "telegram_ready": telegram.ready, "bot": paybot.status()}

    @app.post("/telegram/send_code")
    async def send_code(body: SendCodeIn):
        return await guard(telegram.send_code(body.api_id, body.api_hash.strip(), body.phone.strip()))

    @app.post("/telegram/sign_in")
    async def sign_in(body: CodeIn):
        return await guard(telegram.sign_in(body.code.strip()))

    @app.post("/telegram/password")
    async def password(body: PasswordIn):
        return await guard(telegram.check_password(body.password))

    @app.post("/telegram/logout")
    async def logout():
        await guard(telegram.logout())
        return {"ok": True}

    @app.post("/telegram/send")
    async def send(body: SendIn):
        msg = await guard(engine.send_owner_message(body.chat_id, body.text))
        return {"message_id": msg.id}

    @app.post("/telegram/import_history")
    async def import_history(body: ImportIn):
        return {"added": await guard(telegram.import_history(body.chat_id, body.limit))}

    @app.post("/drafts/{message_id}/approve")
    async def approve(message_id: int, body: ApproveIn):
        msg = await guard(engine.approve_draft(message_id, body.text))
        return {"message_id": msg.id}

    @app.post("/drafts/{message_id}/discard")
    async def discard(message_id: int):
        await guard(engine.discard_draft(message_id))
        return {"ok": True}

    @app.post("/bot/reload")
    async def bot_reload():
        return await guard(paybot.reload())

    @app.post("/sales/{sale_id}/refund")
    async def refund(sale_id: int):
        await guard(payments.refund(sale_id))
        return {"ok": True}

    @app.post("/sales/{sale_id}/deliver")
    async def deliver(sale_id: int):
        if not telegram.ready:
            raise HTTPException(400, "Le compte Telegram n'est pas connecté : livraison impossible pour l'instant.")
        delivered = await guard(delivery.deliver(sale_id))
        if not delivered:
            raise HTTPException(400, "La livraison n'a pas abouti (déjà livrée, remboursée, ou erreur d'envoi). Consultez la page Logs.")
        return {"ok": True}

    return app

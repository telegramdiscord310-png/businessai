from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from ..db import get_session
from ..models import TelegramAccount
from ..security import require_auth
from ..worker_client import call_worker

router = APIRouter(prefix="/api/telegram", tags=["telegram"], dependencies=[Depends(require_auth)])


class SendCodeIn(BaseModel):
    api_id: int = Field(gt=0, lt=10**12)
    api_hash: str = Field(default="", max_length=64)
    phone: str = Field(min_length=5, max_length=32)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        v = re.sub(r"[\s().-]", "", v)
        if not re.fullmatch(r"\+?\d{6,15}", v):
            raise ValueError("Numéro invalide : utilisez le format international, par exemple +33612345678.")
        return v if v.startswith("+") else "+" + v

    @field_validator("api_hash")
    @classmethod
    def check_hash(cls, v: str) -> str:
        v = v.strip()
        if v and not re.fullmatch(r"[0-9a-fA-F]{32}", v):
            raise ValueError("api_hash invalide : il contient 32 caractères (chiffres et lettres de a à f).")
        return v


class CodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=16)

    @field_validator("code")
    @classmethod
    def digits(cls, v: str) -> str:
        v = re.sub(r"\D", "", v)
        if len(v) < 3:
            raise ValueError("Le code ne contient que des chiffres.")
        return v


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return phone[:4] + "•" * max(0, len(phone) - 6) + phone[-2:]


@router.get("")
async def get_account(session: AsyncSession = Depends(get_session)):
    account = await session.get(TelegramAccount, 1)
    if account is None:
        return {"status": "disconnected", "api_id": None, "has_api_hash": False, "phone": None, "name": None, "username": None, "error": None}
    return {
        "status": account.status,
        "api_id": account.api_id,
        "has_api_hash": bool(account.api_hash_enc),
        "phone": mask_phone(account.phone),
        "name": account.me_name,
        "username": account.me_username,
        "error": account.last_error,
    }


@router.post("/send-code")
async def send_code(body: SendCodeIn, session: AsyncSession = Depends(get_session)):
    api_hash = body.api_hash
    if not api_hash:  # réutilise l'api_hash déjà enregistré
        account = await session.get(TelegramAccount, 1)
        api_hash = crypto.decrypt(account.api_hash_enc) if account and account.api_hash_enc else None
        if not api_hash:
            raise HTTPException(422, "Saisissez votre api_hash.")
    return await call_worker("POST", "/telegram/send_code", {"api_id": body.api_id, "api_hash": api_hash, "phone": body.phone})


@router.post("/sign-in")
async def sign_in(body: CodeIn):
    return await call_worker("POST", "/telegram/sign_in", {"code": body.code})


@router.post("/password")
async def password(body: PasswordIn):
    return await call_worker("POST", "/telegram/password", {"password": body.password})


@router.post("/logout")
async def logout():
    return await call_worker("POST", "/telegram/logout")

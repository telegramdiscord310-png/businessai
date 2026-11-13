from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import security
from ..config import get_config
from ..db import get_session
from ..models import AdminUser, WebSession

log = logging.getLogger("app.auth")
router = APIRouter(prefix="/api", tags=["auth"])


class SetupIn(BaseModel):
    setup_token: str = Field(default="", max_length=256)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=1, max_length=256)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


async def admin_exists(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(func.count()).select_from(AdminUser)))


@router.get("/setup/status")
async def setup_status(session: AsyncSession = Depends(get_session)):
    return {"needs_setup": not await admin_exists(session)}


@router.post("/setup")
async def setup(body: SetupIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    """Crée l'unique compte administrateur. Cette route se désactive dès qu'un compte existe."""
    if await admin_exists(session):
        raise HTTPException(403, "L'installation est déjà terminée. Connectez-vous avec votre compte.")
    ip = security.client_ip(request)
    await security.check_login_allowed(session, ip)
    expected = get_config().setup_token
    if not expected:
        raise HTTPException(403, "SETUP_TOKEN n'est pas défini dans le fichier .env : installation impossible depuis le site.")
    if not hmac.compare_digest(body.setup_token.encode(), expected.encode()):
        await security.record_login_attempt(session, ip, False)
        raise HTTPException(403, "Code d'installation incorrect. Il se trouve dans votre fichier .env (SETUP_TOKEN).")
    security.validate_password_strength(body.password)
    user = AdminUser(username=body.username, password_hash=security.hash_password(body.password))
    session.add(user)
    await session.commit()
    log.info("Compte administrateur créé")
    web_session = await security.create_session(session, user, request, response)
    return {"username": user.username, "csrf_token": web_session.csrf_token}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    ip = security.client_ip(request)
    await security.check_login_allowed(session, ip)
    user = await session.scalar(select(AdminUser).where(AdminUser.username == body.username))
    if not security.verify_password(user.password_hash if user else None, body.password) or user is None:
        await security.record_login_attempt(session, ip, False)
        log.warning("Tentative de connexion refusée depuis %s", ip)
        raise HTTPException(401, "Identifiant ou mot de passe incorrect.")
    await security.record_login_attempt(session, ip, True)
    web_session = await security.create_session(session, user, request, response)
    return {"username": user.username, "csrf_token": web_session.csrf_token}


@router.get("/auth/me")
async def me(web_session: WebSession = Depends(security.current_session), session: AsyncSession = Depends(get_session)):
    user = await session.get(AdminUser, web_session.user_id)
    return {"username": user.username, "csrf_token": web_session.csrf_token}


@router.post("/auth/logout")
async def logout(response: Response, web_session: WebSession = Depends(security.require_auth), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(WebSession).where(WebSession.id == web_session.id))
    await session.commit()
    security.clear_cookie(response)
    return {"ok": True}


@router.post("/auth/password")
async def change_password(
    body: PasswordIn, web_session: WebSession = Depends(security.require_auth), session: AsyncSession = Depends(get_session)
):
    user = await session.get(AdminUser, web_session.user_id)
    if not security.verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Le mot de passe actuel est incorrect.")
    security.validate_password_strength(body.new_password)
    user.password_hash = security.hash_password(body.new_password)
    # Toutes les autres sessions sont fermées.
    await session.execute(delete(WebSession).where(WebSession.user_id == user.id, WebSession.id != web_session.id))
    await session.commit()
    log.info("Mot de passe administrateur modifié")
    return {"ok": True}

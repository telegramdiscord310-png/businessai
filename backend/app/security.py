"""Authentification : argon2, sessions par cookie httpOnly, CSRF, limitation des tentatives."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_config
from .db import get_session
from .models import AdminUser, LoginAttempt, WebSession, utcnow

COOKIE_NAME = "ba_session"
MAX_FAILS_PER_IP = 5
MAX_FAILS_GLOBAL = 30
WINDOW = timedelta(minutes=15)

_hasher = PasswordHasher()
# Haché factice : la vérification prend le même temps que l'identifiant existe ou non.
_DUMMY_HASH = _hasher.hash("mot-de-passe-factice")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(422, "Le mot de passe doit contenir au moins 10 caractères.")
    if len(password) > 256:
        raise HTTPException(422, "Le mot de passe est trop long (256 caractères maximum).")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "inconnue"


async def check_login_allowed(session: AsyncSession, ip: str) -> None:
    since = utcnow() - WINDOW
    per_ip = await session.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.ip == ip, LoginAttempt.success.is_(False), LoginAttempt.created_at > since
        )
    )
    overall = await session.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.success.is_(False), LoginAttempt.created_at > since
        )
    )
    if (per_ip or 0) >= MAX_FAILS_PER_IP or (overall or 0) >= MAX_FAILS_GLOBAL:
        raise HTTPException(
            429,
            "Trop de tentatives de connexion. Patientez 15 minutes avant de réessayer.",
            headers={"Retry-After": str(int(WINDOW.total_seconds()))},
        )


async def record_login_attempt(session: AsyncSession, ip: str, success: bool) -> None:
    session.add(LoginAttempt(ip=ip, success=success))
    if success:  # une connexion réussie remet le compteur de cette adresse à zéro
        await session.execute(delete(LoginAttempt).where(LoginAttempt.ip == ip, LoginAttempt.success.is_(False)))
    await session.execute(delete(LoginAttempt).where(LoginAttempt.created_at < utcnow() - timedelta(days=2)))
    await session.commit()


async def create_session(session: AsyncSession, user: AdminUser, request: Request, response: Response) -> WebSession:
    cfg = get_config()
    token = secrets.token_urlsafe(32)
    web_session = WebSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utcnow() + timedelta(days=cfg.session_days),
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:255],
    )
    session.add(web_session)
    await session.execute(delete(WebSession).where(WebSession.expires_at < utcnow()))
    await session.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=cfg.session_days * 86400,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite="strict",
        path="/",
    )
    return web_session


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=get_config().cookie_secure, samesite="strict")


async def current_session(request: Request, session: AsyncSession = Depends(get_session)) -> WebSession:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Connexion requise.")
    web_session = await session.scalar(select(WebSession).where(WebSession.token_hash == _hash_token(token)))
    if web_session is None or web_session.expires_at < utcnow():
        raise HTTPException(401, "Votre session a expiré. Reconnectez-vous.")
    return web_session


async def require_auth(request: Request, web_session: WebSession = Depends(current_session)) -> WebSession:
    """Protège une route : session valide, et jeton CSRF pour toute requête qui modifie des données."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not hmac.compare_digest(sent, web_session.csrf_token):
            raise HTTPException(403, "Jeton de sécurité invalide. Rechargez la page et réessayez.")
    return web_session

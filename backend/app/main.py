"""Application FastAPI (API du site)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import ai, auth, chats, packs, sales, settings, status, telegram
from .config import get_config
from .crypto import CryptoError
from .db import dispose_engine, get_engine, get_sessionmaker
from .events import EventHub, PgBus
from .logs import setup_logging

log = logging.getLogger("app.site")

FIELD_LABELS = {
    "username": "Identifiant", "password": "Mot de passe", "new_password": "Nouveau mot de passe", "name": "Nom",
    "description": "Description", "price_stars": "Prix", "content_text": "Texte à livrer", "content_link": "Lien à livrer",
    "api_id": "api_id", "api_hash": "api_hash", "phone": "Numéro de téléphone", "code": "Code", "token": "Token",
    "ai_base_url": "URL de base", "ai_model": "Modèle", "ai_api_key": "Clé API", "ai_system_prompt": "Consignes",
    "ai_history_limit": "Historique", "ai_temperature": "Créativité", "batch_delay_seconds": "Délai de regroupement",
    "typing_min_seconds": "Délai minimum", "typing_max_seconds": "Délai maximum", "typing_chars_per_second": "Vitesse d'écriture",
    "rate_global_per_hour": "Limite globale", "rate_chat_per_hour": "Limite par conversation",
    "stars_eur_rate": "Taux Stars → euros", "delivery_intro": "Message de livraison", "text": "Message",
}


def french_validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:4]:
        field = next((str(p) for p in reversed(err.get("loc", [])) if isinstance(p, str) and p not in ("body", "query")), "")
        label = FIELD_LABELS.get(field, field)
        kind, ctx, msg = err.get("type", ""), err.get("ctx") or {}, err.get("msg", "")
        if kind == "value_error":
            text = msg.removeprefix("Value error, ")
        elif kind == "missing":
            text = "champ obligatoire."
        elif kind == "string_too_short":
            text = "champ obligatoire." if ctx.get("min_length") == 1 else f"{ctx.get('min_length')} caractères minimum."
        elif kind == "string_too_long":
            text = f"{ctx.get('max_length')} caractères maximum."
        elif kind in ("greater_than_equal", "greater_than"):
            text = f"la valeur doit être supérieure{' ou égale' if kind.endswith('equal') else ''} à {ctx.get('ge', ctx.get('gt'))}."
        elif kind in ("less_than_equal", "less_than"):
            text = f"la valeur doit être inférieure{' ou égale' if kind.endswith('equal') else ''} à {ctx.get('le', ctx.get('lt'))}."
        elif kind.startswith(("int_", "float_")):
            text = "un nombre est attendu."
        elif kind == "string_pattern_mismatch":
            text = "caractères non autorisés."
        else:
            text = "valeur invalide."
        parts.append(f"{label} : {text}" if label else text[:1].upper() + text[1:])
    return " ".join(parts) or "Certaines valeurs sont invalides."


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    db_logs = setup_logging("site")
    sessionmaker = get_sessionmaker()
    log_task = asyncio.create_task(db_logs.run(sessionmaker))
    app.state.bus = PgBus(get_engine())
    app.state.hub = EventHub()
    await app.state.hub.start(config.database_url)
    if not config.fernet_key:
        log.error("FERNET_KEY est vide : renseignez-la dans le fichier .env")
    yield
    await app.state.hub.stop()
    log_task.cancel()
    await dispose_engine()


def create_app(with_lifespan: bool = True) -> FastAPI:
    config = get_config()
    app = FastAPI(
        title="BusinessAI", docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan if with_lifespan else None,
    )
    # CORS strict : seul le site lui-même peut appeler l'API.
    app.add_middleware(
        CORSMiddleware, allow_origins=[config.app_origin], allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def security_layer(request: Request, call_next):
        # Toute requête qui modifie des données doit venir du site lui-même.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != config.app_origin:
                return JSONResponse({"detail": "Requête refusée : origine non autorisée."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def on_validation(_request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": french_validation_message(exc)}, status_code=422)

    @app.exception_handler(CryptoError)
    async def on_crypto(_request: Request, exc: CryptoError):
        log.error("%s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=500)

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception):
        log.error("Erreur inattendue sur %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse({"detail": "Une erreur inattendue est survenue. Le détail est dans la page Logs."}, status_code=500)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    for module in (auth, status, telegram, ai, packs, chats, sales, settings):
        app.include_router(module.router)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def not_found(path: str):
        raise HTTPException(404, "Cette adresse n'existe pas.")

    return app


app = create_app()

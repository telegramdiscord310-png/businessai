"""Appels du backend vers le worker Telegram (réseau interne)."""
from __future__ import annotations

import httpx
from fastapi import HTTPException

from .config import get_config

UNREACHABLE = "Le service Telegram ne répond pas. Vérifiez qu'il est démarré, puis réessayez dans un instant."


async def call_worker(method: str, path: str, json: dict | None = None, timeout: float = 90.0) -> dict:
    cfg = get_config()
    try:
        async with httpx.AsyncClient(base_url=cfg.worker_url, timeout=timeout) as client:
            resp = await client.request(method, path, json=json, headers={"X-Internal-Token": cfg.internal_token})
    except httpx.TimeoutException:
        raise HTTPException(504, "Le service Telegram met trop de temps à répondre. Réessayez dans un instant.")
    except httpx.HTTPError:
        raise HTTPException(503, UNREACHABLE)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = None
        if not isinstance(detail, str):
            detail = "Le service Telegram a rencontré une erreur. Consultez la page Logs."
        raise HTTPException(resp.status_code if resp.status_code < 500 else 502, detail)
    return resp.json()

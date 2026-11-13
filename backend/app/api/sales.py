from __future__ import annotations

import csv
import io
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_session
from ..models import Chat, Sale
from ..security import require_auth
from ..services.stats import compute_dashboard, eur
from ..settings_store import load_settings
from ..worker_client import call_worker
from .serializers import sale_out

router = APIRouter(prefix="/api", tags=["ventes"], dependencies=[Depends(require_auth)])

DELIVERY_LABELS = {"pending": "En attente", "delivering": "En cours", "delivered": "Livrée", "failed": "Échec"}


async def load_sales(session: AsyncSession, limit: int | None, offset: int = 0) -> tuple[list[Sale], dict[int, Chat]]:
    stmt = select(Sale).order_by(Sale.paid_at.desc(), Sale.id.desc()).offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    sales = list((await session.scalars(stmt)).all())
    ids = {s.chat_id for s in sales if s.chat_id is not None}
    chats = {c.id: c for c in (await session.scalars(select(Chat).where(Chat.id.in_(ids or {0})))).all()}
    return sales, chats


@router.get("/dashboard")
async def dashboard(days: int = Query(default=30, ge=7, le=365), session: AsyncSession = Depends(get_session)):
    settings = await load_settings(session)
    rate = float(settings.stars_eur_rate)
    data = await compute_dashboard(session, get_config().timezone, rate, days)
    sales, chats = await load_sales(session, limit=8)
    data["recent_sales"] = [sale_out(s, rate, chats.get(s.chat_id)) for s in sales]
    return data


@router.get("/sales")
async def list_sales(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), session: AsyncSession = Depends(get_session)):
    settings = await load_settings(session)
    rate = float(settings.stars_eur_rate)
    sales, chats = await load_sales(session, limit, offset)
    total = await session.scalar(select(func.count()).select_from(Sale)) or 0
    return {"sales": [sale_out(s, rate, chats.get(s.chat_id)) for s in sales], "total": total}


def csv_cell(value) -> str:
    """Neutralise les formules (=, +, -, @) qu'un tableur pourrait exécuter à l'ouverture du fichier."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/sales/export.csv")
async def export_csv(session: AsyncSession = Depends(get_session)):
    settings = await load_settings(session)
    rate = float(settings.stars_eur_rate)
    tz = ZoneInfo(get_config().timezone)
    sales, chats = await load_sales(session, limit=None)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Date", "Client", "Identifiant Telegram", "Pack", "Stars", "Montant estimé (EUR)", "Livraison", "Remboursée", "Identifiant de paiement"])
    for s in sales:
        chat = chats.get(s.chat_id)
        writer.writerow([
            s.paid_at.astimezone(tz).strftime("%d/%m/%Y %H:%M"),
            csv_cell(chat.display_name if chat else f"Utilisateur {s.buyer_tg_id}"),
            s.buyer_tg_id,
            csv_cell(s.pack.name if s.pack else "Pack inconnu"),
            s.stars,
            f"{eur(s.stars, rate):.2f}".replace(".", ","),
            DELIVERY_LABELS.get(s.delivery_status, s.delivery_status),
            "Oui" if s.refunded_at else "Non",
            csv_cell(s.telegram_payment_charge_id),
        ])
    content = "﻿" + buffer.getvalue()  # BOM : accents corrects à l'ouverture dans Excel
    return Response(
        content=content.encode("utf-8"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ventes.csv"'},
    )


@router.post("/sales/{sale_id}/refund")
async def refund(sale_id: int):
    return await call_worker("POST", f"/sales/{sale_id}/refund")


@router.post("/sales/{sale_id}/deliver")
async def redeliver(sale_id: int):
    return await call_worker("POST", f"/sales/{sale_id}/deliver", timeout=300)

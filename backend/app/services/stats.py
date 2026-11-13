"""Statistiques de ventes pour le tableau de bord (montants en euros = estimation)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Chat, Pack, Sale


def eur(stars: int, rate: float) -> float:
    return round(stars * rate, 2)


async def compute_dashboard(session: AsyncSession, tz_name: str, rate: float, days: int = 30, now: datetime | None = None) -> dict:
    tz = ZoneInfo(tz_name)
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date()
    rows = (
        await session.execute(
            select(Sale.id, Sale.stars, Sale.paid_at, Sale.pack_id, Sale.chat_id, Sale.buyer_tg_id).where(Sale.refunded_at.is_(None))
        )
    ).all()
    refunded = await session.scalar(select(func.count()).select_from(Sale).where(Sale.refunded_at.is_not(None))) or 0

    per_day: dict = defaultdict(lambda: [0, 0])
    per_pack: dict = defaultdict(lambda: [0, 0])
    per_buyer: dict = defaultdict(lambda: [0, 0])
    total = 0
    for row in rows:
        day = row.paid_at.astimezone(tz).date()
        per_day[day][0] += row.stars
        per_day[day][1] += 1
        per_pack[row.pack_id][0] += row.stars
        per_pack[row.pack_id][1] += 1
        per_buyer[row.chat_id or row.buyer_tg_id][0] += row.stars
        per_buyer[row.chat_id or row.buyer_tg_id][1] += 1
        total += row.stars

    def window(start_offset: int, length: int) -> int:
        """Somme des Stars sur `length` jours se terminant `start_offset` jours avant aujourd'hui."""
        return sum(per_day[today - timedelta(days=start_offset + i)][0] for i in range(length) if (today - timedelta(days=start_offset + i)) in per_day)

    def amount(stars: int) -> dict:
        return {"stars": stars, "eur": eur(stars, rate)}

    series = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        stars, count = per_day.get(day, (0, 0))
        series.append({"date": day.isoformat(), "stars": stars, "eur": eur(stars, rate), "count": count})

    pack_names = {p.id: p.name for p in (await session.scalars(select(Pack))).all()}
    by_pack = sorted(
        (
            {"pack_id": pid, "name": pack_names.get(pid, "Pack inconnu"), "count": c, "stars": s, "eur": eur(s, rate)}
            for pid, (s, c) in per_pack.items()
        ),
        key=lambda x: -x["stars"],
    )
    top_ids = sorted(per_buyer.items(), key=lambda kv: -kv[1][0])[:5]
    chats = {c.id: c for c in (await session.scalars(select(Chat).where(Chat.id.in_([k for k, _ in top_ids] or [0])))).all()}
    top_customers = [
        {
            "chat_id": cid, "name": chats[cid].display_name if cid in chats else f"Utilisateur {cid}",
            "has_photo": bool(cid in chats and chats[cid].has_photo), "count": c, "stars": s, "eur": eur(s, rate),
        }
        for cid, (s, c) in top_ids
    ]
    conversations = await session.scalar(select(func.count()).select_from(Chat).where(Chat.first_message_at.is_not(None))) or 0
    buyers = len(per_buyer)
    return {
        "rate": rate,
        "timezone": tz_name,
        "revenue": {
            "today": amount(window(0, 1)),
            "d7": amount(window(0, 7)),
            "d30": amount(window(0, 30)),
            "total": amount(total),
            "prev_d7": amount(window(7, 7)),
            "prev_d30": amount(window(30, 30)),
            "yesterday": amount(window(1, 1)),
        },
        "series": series,
        "by_pack": by_pack,
        "top_customers": top_customers,
        "sales_count": len(rows),
        "refunded_count": refunded,
        "conversations": conversations,
        "buyers": buyers,
        "conversion": round(buyers / conversations * 100, 1) if conversations else 0.0,
    }

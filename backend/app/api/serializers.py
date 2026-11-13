from __future__ import annotations

from ..models import Chat, LogEntry, Message, Pack, Sale
from ..services.stats import eur


def chat_out(chat: Chat, *, has_draft: bool = False, is_buyer: bool = False) -> dict:
    return {
        "id": str(chat.id),  # en chaîne : les identifiants Telegram dépassent la précision des nombres JavaScript
        "name": chat.display_name,
        "username": chat.username,
        "has_photo": chat.has_photo,
        "photo_version": int(chat.photo_checked_at.timestamp()) if chat.photo_checked_at else 0,
        "ai_enabled": chat.ai_enabled,
        "ai_paused": chat.ai_paused,
        "unread_count": chat.unread_count,
        "last_message_at": chat.last_message_at,
        "last_message_text": chat.last_message_text,
        "last_message_sender": chat.last_message_sender,
        "first_message_at": chat.first_message_at,
        "history_imported_at": chat.history_imported_at,
        "has_draft": has_draft,
        "is_buyer": is_buyer,
    }


def message_out(m: Message) -> dict:
    meta = m.meta or {}
    return {
        "id": m.id,
        "chat_id": str(m.chat_id),
        "direction": m.direction,
        "sender": m.sender,
        "kind": m.kind,
        "text": m.text,
        "media_type": m.media_type,
        "media_desc": m.media_desc,
        "has_media_file": bool(m.media_path),
        "status": m.status,
        "created_at": m.created_at,
        "pack_names": meta.get("pack_names") or ([meta["pack_name"]] if meta.get("pack_name") else []),
        "imported": bool(meta.get("imported")),
    }


def pack_out(p: Pack, sales_count: int = 0, sales_stars: int = 0) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price_stars": p.price_stars,
        "content_text": p.content_text or "",
        "content_link": p.content_link or "",
        "active": p.active,
        "created_at": p.created_at,
        "files": [{"id": f.id, "filename": f.filename, "size": f.size, "mime": f.mime} for f in p.files],
        "sales_count": sales_count,
        "sales_stars": sales_stars,
    }


def sale_out(s: Sale, rate: float, chat: Chat | None = None) -> dict:
    return {
        "id": s.id,
        "chat_id": str(s.chat_id) if s.chat_id is not None else None,
        "client_name": chat.display_name if chat else f"Utilisateur {s.buyer_tg_id}",
        "client_has_photo": bool(chat and chat.has_photo),
        "buyer_tg_id": str(s.buyer_tg_id),
        "pack_id": s.pack_id,
        "pack_name": s.pack.name if s.pack else "Pack inconnu",
        "stars": s.stars,
        "eur": eur(s.stars, rate),
        "paid_at": s.paid_at,
        "delivery_status": s.delivery_status,
        "delivery_error": s.delivery_error,
        "delivered_at": s.delivered_at,
        "refunded_at": s.refunded_at,
    }


def log_out(entry: LogEntry) -> dict:
    return {
        "id": entry.id, "created_at": entry.created_at, "level": entry.level, "source": entry.source,
        "message": entry.message, "details": entry.details,
    }

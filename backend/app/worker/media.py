"""Description simple des messages non textuels (pour l'historique et pour l'IA)."""
from __future__ import annotations


def _duration(msg) -> str:
    try:
        seconds = int(msg.file.duration or 0)
    except Exception:
        return ""
    return f" ({seconds} s)" if seconds else ""


def describe_media(msg) -> tuple[str | None, str | None]:
    """Renvoie (type, description) ou (None, None) pour un message purement textuel.
    Ne lève jamais d'exception : un média inconnu devient « Pièce jointe »."""
    try:
        if getattr(msg, "photo", None):
            return "photo", "Photo"
        if getattr(msg, "voice", None):
            return "voice", f"Message vocal{_duration(msg)}"
        if getattr(msg, "video_note", None):
            return "video_note", f"Message vidéo{_duration(msg)}"
        if getattr(msg, "sticker", None):
            emoji = ""
            try:
                emoji = msg.file.emoji or ""
            except Exception:
                pass
            return "sticker", f"Sticker {emoji}".strip()
        if getattr(msg, "gif", None):
            return "gif", "GIF"
        if getattr(msg, "video", None):
            return "video", f"Vidéo{_duration(msg)}"
        if getattr(msg, "audio", None):
            title = ""
            try:
                title = msg.file.title or msg.file.name or ""
            except Exception:
                pass
            return "audio", f"Fichier audio{' : ' + title if title else ''}"[:200]
        if getattr(msg, "document", None):
            name = ""
            try:
                name = msg.file.name or ""
            except Exception:
                pass
            return "document", f"Fichier{' : ' + name if name else ''}"[:200]
        if getattr(msg, "contact", None):
            return "contact", "Contact partagé"
        if getattr(msg, "venue", None) or getattr(msg, "geo", None):
            return "location", "Position géographique"
        if getattr(msg, "poll", None):
            return "poll", "Sondage"
        if getattr(msg, "dice", None):
            return "dice", "Dé animé"
        if getattr(msg, "game", None):
            return "game", "Jeu"
        if getattr(msg, "invoice", None):
            return "invoice", "Facture"
        media = getattr(msg, "media", None)
        if media is not None and not getattr(msg, "web_preview", None):
            return "other", "Pièce jointe"
    except Exception:
        return "other", "Pièce jointe"
    return None, None

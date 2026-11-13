"""Réglages de l'application stockés en base (table clé/valeur), avec valeurs par défaut."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto
from .models import Setting

DEFAULT_PERSONA = (
    "Tu es l'assistant de vente d'un créateur de contenus numériques. Tu réponds à ses messages "
    "privés sur Telegram avec un ton chaleureux, naturel et direct, comme dans une vraie "
    "conversation par messagerie.\n\n"
    "Ton rôle : comprendre ce que cherche la personne, répondre à ses questions, et lui proposer "
    "le pack le plus adapté quand c'est pertinent, sans insister."
)

DEFAULTS: dict[str, Any] = {
    # Interrupteurs
    "ai_enabled": False,
    "draft_mode": False,
    # Fournisseur IA (format OpenAI)
    "ai_base_url": "https://api.x.ai/v1",
    "ai_model": "",
    "ai_api_key_enc": None,
    "ai_system_prompt": DEFAULT_PERSONA,
    "ai_never_deny_bot": True,
    "ai_history_limit": 30,
    "ai_temperature": 0.7,
    # Rythme des réponses
    "batch_delay_seconds": 6,
    "typing_min_seconds": 2,
    "typing_max_seconds": 12,
    "typing_chars_per_second": 18,
    "mark_as_read": True,
    # Limites de débit
    "rate_global_per_hour": 120,
    "rate_chat_per_hour": 20,
    # Ventes
    "stars_eur_rate": 0.012,
    "delivery_intro": "Merci pour ton achat ! Voici ton pack :",
    # Bot de paiement
    "bot_token_enc": None,
    "bot_username": None,
}

SECRET_KEYS = {"ai_api_key_enc", "bot_token_enc"}


class Settings:
    """Instantané des réglages ; les clés absentes de la base prennent leur valeur par défaut."""

    def __init__(self, values: dict[str, Any]):
        self._values = {**DEFAULTS, **values}

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def get(self, name: str, default: Any = None) -> Any:
        return self._values.get(name, default)

    @property
    def ai_api_key(self) -> str | None:
        return crypto.decrypt(self._values.get("ai_api_key_enc"))

    @property
    def bot_token(self) -> str | None:
        return crypto.decrypt(self._values.get("bot_token_enc"))

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_base_url and self.ai_model and self._values.get("ai_api_key_enc"))

    @property
    def bot_configured(self) -> bool:
        return bool(self._values.get("bot_token_enc"))

    def public(self) -> dict[str, Any]:
        """Réglages sans secret, pour l'interface."""
        return {k: v for k, v in self._values.items() if k not in SECRET_KEYS}


async def load_settings(session: AsyncSession) -> Settings:
    rows = (await session.execute(select(Setting))).scalars().all()
    return Settings({r.key: r.value for r in rows if r.key in DEFAULTS})


async def save_settings(session: AsyncSession, values: dict[str, Any]) -> None:
    """Enregistre les clés fournies (le commit reste à la charge de l'appelant)."""
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(f"Réglage inconnu : {key}")
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value

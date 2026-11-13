"""Outils de test : base temporaire, faux userbot, fausse IA, faux bot de paiement."""
from __future__ import annotations

import itertools
import os
import random
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("SETUP_TOKEN", "code-installation-test")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("APP_ORIGIN", "http://testserver")

from app import crypto  # noqa: E402
from app.events import MemoryBus  # noqa: E402
from app.models import Base, Chat, Pack  # noqa: E402
from app.services.ai_client import AIResponse, ToolCall  # noqa: E402
from app.services.chatlog import Outbox, PeerInfo  # noqa: E402
from app.services.delivery import DeliveryService  # noqa: E402
from app.services.payments import PaymentService  # noqa: E402
from app.services.reply_engine import Incoming, ReplyEngine  # noqa: E402
from app.settings_store import save_settings  # noqa: E402


class FakeTransport:
    """Remplace le userbot : note tout ce qui « partirait » sur Telegram."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.typing_calls: list[tuple[int, float]] = []
        self.read: list[int] = []
        self._ids = itertools.count(1000)
        self.fail_on_file: str | None = None
        self.before_send = None  # crochet optionnel (simulateur de course)

    async def send_text(self, chat_id: int, text: str) -> int:
        if self.before_send:
            await self.before_send(chat_id)
        tg_id = next(self._ids)
        self.sent.append({"chat_id": chat_id, "text": text, "tg_id": tg_id})
        return tg_id

    async def send_file(self, chat_id: int, path: str, filename: str | None = None, caption: str | None = None) -> int:
        if self.fail_on_file and filename == self.fail_on_file:
            raise RuntimeError("envoi du fichier impossible")
        tg_id = next(self._ids)
        self.sent.append({"chat_id": chat_id, "file": filename, "caption": caption, "tg_id": tg_id})
        return tg_id

    async def typing(self, chat_id: int, seconds: float) -> None:
        self.typing_calls.append((chat_id, seconds))

    async def mark_read(self, chat_id: int) -> None:
        self.read.append(chat_id)

    def texts(self, chat_id: int | None = None) -> list[str]:
        return [s["text"] for s in self.sent if "text" in s and (chat_id is None or s["chat_id"] == chat_id)]


class FakeAI:
    """IA scriptée : renvoie les réponses prévues, puis une réponse par défaut."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.script: list[AIResponse] = []
        self.default = "Bonjour ! Comment puis-je t'aider ?"
        self.before_complete = None

    def say(self, text: str) -> None:
        self.script.append(AIResponse(text=text, assistant_message={"role": "assistant", "content": text}))

    def call_tool(self, pack_id, text: str = "") -> None:
        raw = [{"id": "call_1", "type": "function", "function": {"name": "envoyer_lien_paiement", "arguments": f'{{"pack_id": {pack_id}}}'}}]
        self.script.append(
            AIResponse(
                text=text,
                tool_calls=[ToolCall(id="call_1", name="envoyer_lien_paiement", arguments={"pack_id": pack_id})],
                assistant_message={"role": "assistant", "content": text or None, "tool_calls": raw},
            )
        )

    async def complete(self, messages, tools=None) -> AIResponse:
        self.calls.append([dict(m) for m in messages])
        if self.before_complete:
            await self.before_complete()
        if self.script:
            return self.script.pop(0)
        return AIResponse(text=self.default, assistant_message={"role": "assistant", "content": self.default})

    def last_user_content(self) -> str:
        return [m for m in self.calls[-1] if m["role"] == "user"][-1]["content"]


class FakeBot:
    """Remplace le bot de paiement (API Bot de Telegram)."""

    def __init__(self) -> None:
        self.invoice_calls: list[dict] = []
        self.refund_calls: list[dict] = []
        self.refund_error: Exception | None = None
        self._n = itertools.count(1)

    async def create_invoice_link(self, **kwargs) -> str:
        self.invoice_calls.append(kwargs)
        return f"https://t.me/$facture{next(self._n)}"

    async def refund_star_payment(self, user_id: int, telegram_payment_charge_id: str) -> bool:
        if self.refund_error:
            raise self.refund_error
        self.refund_calls.append({"user_id": user_id, "telegram_payment_charge_id": telegram_payment_charge_id})
        return True


@dataclass
class World:
    sm: async_sessionmaker
    bus: MemoryBus
    transport: FakeTransport
    ai: FakeAI
    bot: FakeBot
    outbox: Outbox
    payments: PaymentService
    delivery: DeliveryService
    engine: ReplyEngine
    data_dir: str
    _tg_ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    async def settings(self, **values) -> None:
        async with self.sm() as s:
            await save_settings(s, values)
            await s.commit()

    def incoming(self, chat_id: int = 111, text: str = "Salut", **kw) -> Incoming:
        peer = kw.pop("peer", None) or PeerInfo(id=chat_id, first_name="Léa", username="lea", access_hash=42)
        return Incoming(peer=peer, tg_message_id=kw.pop("tg_message_id", next(self._tg_ids)), text=text, **kw)

    async def receive(self, chat_id: int = 111, text: str = "Salut", **kw):
        """Simule un message reçu, puis attend que le moteur ait fini."""
        stored = await self.engine.on_incoming(self.incoming(chat_id, text, **kw))
        await self.engine.wait_idle()
        return stored

    async def chat(self, chat_id: int = 111) -> Chat | None:
        async with self.sm() as s:
            return await s.get(Chat, chat_id)

    async def add_pack(self, name="Pack Photos", price=250, **kw) -> Pack:
        async with self.sm() as s:
            pack = Pack(name=name, description=kw.pop("description", "20 photos HD"), price_stars=price,
                        content_text=kw.pop("content_text", "Voici ton contenu"), content_link=kw.pop("content_link", None),
                        active=kw.pop("active", True))
            s.add(pack)
            await s.commit()
            return pack


@pytest_asyncio.fixture
async def world(tmp_path):
    # Par défaut : fichier SQLite jetable. Avec TEST_DATABASE_URL, les tests tournent sur Postgres.
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    bus, transport, ai, bot = MemoryBus(), FakeTransport(), FakeAI(), FakeBot()
    outbox = Outbox(sm, transport, bus)
    payments = PaymentService(sm, lambda: bot, bus)
    delivery = DeliveryService(sm, outbox, bus, str(tmp_path))
    engine_ = ReplyEngine(sm, outbox, payments, bus, lambda settings: ai, rng=random.Random(1))
    w = World(sm, bus, transport, ai, bot, outbox, payments, delivery, engine_, str(tmp_path))
    # Réglages de test : IA active et configurée, aucun délai réel.
    await w.settings(
        ai_enabled=True, ai_model="modele-test", ai_api_key_enc=crypto.encrypt("cle-test"),
        batch_delay_seconds=0, typing_min_seconds=0, typing_max_seconds=0,
    )
    yield w
    await engine_.shutdown()
    await engine.dispose()

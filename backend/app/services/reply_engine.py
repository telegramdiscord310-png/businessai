"""Règles de réponse automatique.

Invariants garantis ici (et vérifiés par les tests) :
- le userbot ne fait que répondre : aucun envoi sans message reçu resté sans réponse ;
- seuls les messages privés d'utilisateurs humains sont pris en compte ;
- plusieurs messages d'affilée donnent une seule réponse ;
- dès que le propriétaire écrit, l'IA se met en pause sur la conversation ;
- limites de débit globale et par conversation ;
- en mode brouillon, rien n'est envoyé sans validation.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..events import EventBus
from ..models import Chat, Invoice, Message, Pack, utcnow
from ..settings_store import Settings, load_settings
from .ai_client import AIClient, AIError
from .chatlog import Outbox, PeerInfo, add_message, discard_drafts, mark_answered, upsert_chat
from .conversation import run_turn
from .payments import PaymentError, PaymentService
from .prompt import build_system_prompt, history_to_messages

log = logging.getLogger("app.engine")
MAX_LINKS_PER_REPLY = 2


class EngineError(Exception):
    """Erreur présentable telle quelle (en français)."""


@dataclass
class Incoming:
    """Message vu par le userbot, réduit à ce dont les règles ont besoin."""

    peer: PeerInfo
    tg_message_id: int
    text: str = ""
    date: datetime | None = None
    is_private: bool = True
    is_outgoing: bool = False
    is_service: bool = False
    media_type: str | None = None
    media_desc: str | None = None


def should_handle(msg: Incoming) -> bool:
    """Vrai uniquement pour un message privé entrant écrit par un utilisateur humain."""
    if not msg.is_private or msg.is_outgoing or msg.is_service:
        return False
    peer = msg.peer
    if peer.is_bot or peer.is_self or peer.is_service_account:
        return False
    return True


def typing_delay(length: int, settings: Settings, rng: random.Random) -> float:
    """Durée d'écriture simulée : proportionnelle à la longueur, ±25 % d'aléatoire, bornée."""
    low = max(0.0, float(settings.typing_min_seconds))
    high = max(low, float(settings.typing_max_seconds))
    speed = max(1.0, float(settings.typing_chars_per_second))
    return min(high, max(low, (length / speed) * rng.uniform(0.75, 1.25)))


def blocked_reason(settings: Settings, chat: Chat | None) -> str | None:
    if chat is None:
        return "conversation inconnue"
    if not settings.ai_enabled:
        return "IA désactivée"
    if not chat.ai_enabled:
        return "IA désactivée pour cette conversation"
    if chat.ai_paused:
        return "IA en pause sur cette conversation"
    if not settings.ai_configured:
        return "IA non configurée"
    return None


class ReplyEngine:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        outbox: Outbox,
        payments: PaymentService,
        bus: EventBus,
        ai_factory: Callable[[Settings], AIClient],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.outbox = outbox
        self.payments = payments
        self.bus = bus
        self.ai_factory = ai_factory
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._tasks: dict[int, asyncio.Task] = {}
        self._sending: set[int] = set()
        self._rerun: set[int] = set()

    # ------------------------------------------------------------------ entrées

    async def on_incoming(self, msg: Incoming) -> Message | None:
        """Message reçu d'un client. Enregistré, puis réponse planifiée (jamais immédiate)."""
        if not should_handle(msg):
            return None
        async with self.sessionmaker() as session:
            chat = await upsert_chat(session, msg.peer)
            stored = await add_message(
                session, chat, direction="in", sender="client", text=msg.text,
                kind="media" if msg.media_type else "text", tg_message_id=msg.tg_message_id,
                media_type=msg.media_type, media_desc=msg.media_desc, created_at=msg.date,
            )
            if stored is None:  # doublon (mise à jour rejouée par Telegram)
                return None
            await session.commit()
        await self.bus.publish("message", chat_id=msg.peer.id, message_id=stored.id)
        self._schedule(msg.peer.id)
        return stored

    async def on_owner_message(self, msg: Incoming) -> Message | None:
        """Message sortant vu sur Telegram. S'il n'a pas été envoyé par l'application, c'est le
        propriétaire qui écrit : on l'enregistre et l'IA se met en pause sur cette conversation."""
        if not msg.is_private or msg.is_service or msg.peer.is_self or msg.peer.is_bot or msg.peer.is_service_account:
            return None
        chat_id = msg.peer.id
        async with self.outbox.lock(chat_id):
            if self.outbox.is_own(chat_id, msg.tg_message_id):
                return None
            async with self.sessionmaker() as session:
                chat = await upsert_chat(session, msg.peer)
                stored = await add_message(
                    session, chat, direction="out", sender="owner", text=msg.text,
                    kind="media" if msg.media_type else "text", tg_message_id=msg.tg_message_id,
                    media_type=msg.media_type, media_desc=msg.media_desc, created_at=msg.date,
                )
                if stored is None:
                    return None
                chat.ai_paused, chat.paused_reason = True, "manual"
                await mark_answered(session, chat_id)
                await discard_drafts(session, chat_id)
                await session.commit()
        self._cancel(chat_id)
        log.info("Réponse manuelle détectée : IA mise en pause sur la conversation %s", chat_id)
        await self.bus.publish("message", chat_id=chat_id, message_id=stored.id)
        await self.bus.publish("chat", chat_id=chat_id)
        return stored

    async def send_owner_message(self, chat_id: int, text: str) -> Message:
        """Réponse manuelle écrite depuis le site : envoyée, et l'IA se met en pause."""
        text = text.strip()
        if not text:
            raise EngineError("Le message est vide.")
        async with self.sessionmaker() as session:
            if await session.get(Chat, chat_id) is None:
                raise EngineError("Conversation introuvable.")
        self._cancel(chat_id)
        msg = await self.outbox.send(chat_id, sender="owner", text=text, pause_ai=True, answer_all=True)
        await self.bus.publish("chat", chat_id=chat_id)
        return msg

    async def approve_draft(self, message_id: int, text: str | None = None) -> Message:
        """Mode brouillon : le propriétaire valide (et corrige éventuellement) la réponse de l'IA."""
        async with self.sessionmaker() as session:
            draft = await session.get(Message, message_id)
            if draft is None or draft.status != "draft":
                raise EngineError("Ce brouillon n'existe plus (déjà envoyé, remplacé ou supprimé).")
            chat_id = draft.chat_id
            final_text = (text if text is not None else draft.text).strip()
            pack_ids = list((draft.meta or {}).get("pack_ids", []))
            batch_upto = (draft.meta or {}).get("answer_upto")
        if not final_text and not pack_ids:
            raise EngineError("Le message est vide.")
        try:
            invoices = [await self.payments.create_invoice(pid, chat_id) for pid in pack_ids]
        except PaymentError as exc:
            raise EngineError(f"Lien de paiement impossible à créer : {exc}") from exc
        async with self.outbox.lock(chat_id):
            async with self.sessionmaker() as session:
                draft = await session.get(Message, message_id)
                if draft is None or draft.status != "draft":
                    raise EngineError("Ce brouillon n'existe plus (déjà envoyé, remplacé ou supprimé).")
            if final_text:
                msg = await self.outbox.send(
                    chat_id, sender="ai", text=final_text, draft_id=message_id, answer_upto=batch_upto, locked=True
                )
            else:
                async with self.sessionmaker() as session:
                    draft = await session.get(Message, message_id)
                    draft.status = "discarded"
                    if batch_upto is not None:
                        await mark_answered(session, chat_id, batch_upto)
                    await session.commit()
                msg = draft
            await self._send_links(chat_id, invoices)
        await self.bus.publish("chat", chat_id=chat_id)
        return msg

    async def discard_draft(self, message_id: int) -> None:
        async with self.sessionmaker() as session:
            draft = await session.get(Message, message_id)
            if draft is None or draft.status != "draft":
                raise EngineError("Ce brouillon n'existe plus.")
            draft.status = "discarded"
            chat_id = draft.chat_id
            await session.commit()
        await self.bus.publish("chat", chat_id=chat_id)

    # --------------------------------------------------------------- planification

    def _schedule(self, chat_id: int) -> None:
        task = self._tasks.get(chat_id)
        if task and not task.done():
            if chat_id in self._sending:
                # Une réponse part à l'instant : on traitera ce nouveau message juste après.
                self._rerun.add(chat_id)
                return
            task.cancel()
        self._tasks[chat_id] = asyncio.create_task(self._run(chat_id))

    def _cancel(self, chat_id: int) -> None:
        self._rerun.discard(chat_id)
        task = self._tasks.get(chat_id)
        if task and not task.done() and chat_id not in self._sending:
            task.cancel()

    async def _run(self, chat_id: int) -> None:
        try:
            async with self.sessionmaker() as session:
                settings = await load_settings(session)
            # Regroupement : on laisse à la personne le temps de finir d'écrire.
            await self._sleep(max(0.0, float(settings.batch_delay_seconds)))
            await self._process(chat_id)
        except asyncio.CancelledError:
            raise
        except AIError as exc:
            log.error("Réponse IA impossible (conversation %s) : %s", chat_id, exc)
        except Exception:
            log.exception("Erreur pendant la réponse automatique (conversation %s)", chat_id)
        finally:
            if self._tasks.get(chat_id) is asyncio.current_task():
                del self._tasks[chat_id]
                if chat_id in self._rerun:
                    self._rerun.discard(chat_id)
                    self._schedule(chat_id)

    async def wait_idle(self) -> None:
        """Attend la fin des réponses en cours (utilisé par les tests et à l'arrêt)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
            await asyncio.sleep(0)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    # ------------------------------------------------------------------ traitement

    async def _pending_batch(self, session: AsyncSession, chat_id: int, upto: int | None = None) -> list[int]:
        stmt = select(Message.id).where(
            Message.chat_id == chat_id, Message.direction == "in", Message.status == "sent", Message.answered.is_(False)
        )
        if upto is not None:
            stmt = stmt.where(Message.id <= upto)
        return list((await session.scalars(stmt.order_by(Message.id))).all())

    async def _within_limits(self, session: AsyncSession, settings: Settings, chat_id: int) -> bool:
        since = utcnow() - timedelta(hours=1)
        base = select(func.count()).select_from(Message).where(
            Message.sender == "ai", Message.kind == "text", Message.status == "sent", Message.created_at > since
        )
        total = await session.scalar(base) or 0
        if total >= int(settings.rate_global_per_hour):
            log.warning("Limite de débit globale atteinte (%s réponses sur une heure) : pas de réponse pour l'instant", total)
            return False
        per_chat = await session.scalar(base.where(Message.chat_id == chat_id)) or 0
        if per_chat >= int(settings.rate_chat_per_hour):
            log.warning("Limite de débit atteinte pour la conversation %s (%s réponses sur une heure)", chat_id, per_chat)
            return False
        return True

    async def _process(self, chat_id: int) -> None:
        async with self.sessionmaker() as session:
            settings = await load_settings(session)
            chat = await session.get(Chat, chat_id)
            reason = blocked_reason(settings, chat)
            if reason:
                if reason == "IA non configurée":
                    log.warning("Message reçu mais l'IA n'est pas configurée (page IA) : aucune réponse envoyée")
                return
            batch = await self._pending_batch(session, chat_id)
            if not batch:
                return  # rien à quoi répondre : le userbot n'écrit jamais en premier
            if not await self._within_limits(session, settings, chat_id):
                return
            limit = max(2, int(settings.ai_history_limit))
            rows = (
                await session.scalars(
                    select(Message)
                    .where(Message.chat_id == chat_id, Message.status == "sent")
                    .order_by(Message.id.desc())
                    .limit(limit)
                )
            ).all()
            history = history_to_messages(list(reversed(rows)))
            packs = list(
                (await session.scalars(select(Pack).where(Pack.active.is_(True), Pack.deleted_at.is_(None)).order_by(Pack.id))).all()
            )
        if not history:
            return
        batch_upto = batch[-1]
        packs_by_id = {p.id: p for p in packs}
        draft_mode = bool(settings.draft_mode)
        invoices: list[Invoice] = []

        async def on_payment_tool(pack_id: int) -> tuple[bool, str]:
            pack = packs_by_id.get(pack_id)
            if pack is None:
                return False, "Ce pack n'existe pas. Utilise uniquement un identifiant présent dans le catalogue."
            if len(invoices) >= MAX_LINKS_PER_REPLY:
                return False, "Trop de liens dans un même message."
            if not self.payments.available:
                return False, "Le paiement est momentanément indisponible. Dis-le simplement au client, sans inventer de lien."
            if not draft_mode:
                try:
                    invoices.append(await self.payments.create_invoice(pack_id, chat_id))
                except PaymentError:
                    return False, "Le paiement est momentanément indisponible. Dis-le simplement au client, sans inventer de lien."
            return True, (
                f"Lien de paiement pour « {pack.name} » ({pack.price_stars} Stars) prêt : il sera envoyé "
                "automatiquement juste après ton message. N'écris aucun lien toi-même."
            )

        system_prompt = build_system_prompt(settings, packs)
        turn = await run_turn(self.ai_factory(settings), system_prompt, history, on_payment_tool)
        if not turn.text and not turn.pack_ids:
            log.warning("L'IA a renvoyé une réponse vide (conversation %s) : rien n'a été envoyé", chat_id)
            return

        if draft_mode:
            await self._save_draft(chat_id, turn.text, turn.pack_ids, batch_upto, packs_by_id)
            return

        if settings.mark_as_read:
            try:
                await self.outbox.transport.mark_read(chat_id)
            except Exception:
                log.debug("Accusé de lecture non envoyé", exc_info=True)
        # Délai humain : « en train d'écrire » pendant une durée liée à la longueur de la réponse.
        await self.outbox.transport.typing(chat_id, typing_delay(len(turn.text), settings, self._rng))

        self._sending.add(chat_id)
        try:
            await self._send_reply(chat_id, batch_upto, turn.text, invoices)
        finally:
            self._sending.discard(chat_id)

    async def _save_draft(self, chat_id: int, text: str, pack_ids: list[int], batch_upto: int, packs_by_id: dict[int, Pack]) -> None:
        async with self.sessionmaker() as session:
            chat = await session.get(Chat, chat_id)
            await discard_drafts(session, chat_id)
            draft = await add_message(
                session, chat, direction="out", sender="ai", text=text, status="draft",
                meta={
                    "pack_ids": pack_ids,
                    "pack_names": [packs_by_id[p].name for p in pack_ids if p in packs_by_id],
                    "answer_upto": batch_upto,
                },
            )
            await session.commit()
        log.info("Brouillon de réponse prêt à valider (conversation %s)", chat_id)
        await self.bus.publish("message", chat_id=chat_id, message_id=draft.id)
        await self.bus.publish("chat", chat_id=chat_id)

    async def _send_reply(self, chat_id: int, batch_upto: int, text: str, invoices: list[Invoice]) -> None:
        async with self.outbox.lock(chat_id):
            # Dernière vérification, verrou tenu : l'état a pu changer pendant la rédaction.
            async with self.sessionmaker() as session:
                settings = await load_settings(session)
                chat = await session.get(Chat, chat_id)
                if blocked_reason(settings, chat):
                    return
                if not await self._pending_batch(session, chat_id, batch_upto):
                    return  # déjà répondu entre-temps : jamais de second message
            if text:
                await self.outbox.send(chat_id, sender="ai", text=text, answer_upto=batch_upto, locked=True)
            else:
                async with self.sessionmaker() as session:
                    await mark_answered(session, chat_id, batch_upto)
                    await session.commit()
            await self._send_links(chat_id, invoices)
        log.info("Réponse IA envoyée (conversation %s)", chat_id)
        await self.bus.publish("chat", chat_id=chat_id)

    async def _send_links(self, chat_id: int, invoices: list[Invoice]) -> None:
        """Envoie les liens de paiement. Le texte est composé ici, à partir de la base uniquement."""
        for invoice in invoices:
            async with self.sessionmaker() as session:
                pack = await session.get(Pack, invoice.pack_id)
            await self.outbox.send(
                chat_id,
                sender="ai",
                kind="payment_link",
                text=f"{pack.name} — {invoice.price_stars} ⭐\n{invoice.link}",
                meta={"pack_id": pack.id, "pack_name": pack.name, "invoice_id": invoice.id, "stars": invoice.price_stars},
                locked=True,
            )

"""Paiements en Telegram Stars : liens de facture, contrôle avant paiement, ventes, remboursements.

Toute décision (prix, pack, acheteur) est prise ici à partir de la base de données,
jamais à partir du texte produit par l'IA ou envoyé par un client.
"""
from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..events import EventBus
from ..models import Invoice, Pack, Sale, utcnow

log = logging.getLogger("app.payments")
CURRENCY = "XTR"


class PaymentError(Exception):
    """Erreur présentable telle quelle (en français)."""


@dataclass
class PayloadData:
    token: str
    buyer_id: int
    pack_id: int
    chat_id: int


def build_payload(token: str, buyer_id: int, pack_id: int, chat_id: int) -> str:
    """Payload de facture (≤ 128 octets) : identifie l'acheteur, le pack et la conversation."""
    payload = f"v1|{token}|{buyer_id}|{pack_id}|{chat_id}"
    assert len(payload.encode()) <= 128
    return payload


def parse_payload(payload: str | None) -> PayloadData | None:
    try:
        version, token, buyer, pack, chat = (payload or "").split("|")
        if version != "v1" or not token:
            return None
        return PayloadData(token=token, buyer_id=int(buyer), pack_id=int(pack), chat_id=int(chat))
    except ValueError:
        return None


class PaymentService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        get_bot: Callable[[], Any | None],
        bus: EventBus,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.get_bot = get_bot
        self.bus = bus

    @property
    def available(self) -> bool:
        return self.get_bot() is not None

    async def create_invoice(self, pack_id: int, chat_id: int) -> Invoice:
        """Crée un lien de facture en Stars pour ce pack, réservé à l'interlocuteur de cette conversation."""
        bot = self.get_bot()
        if bot is None:
            raise PaymentError("Le bot de paiement n'est pas configuré (Paramètres → Bot de paiement).")
        async with self.sessionmaker() as session:
            pack = await session.get(Pack, pack_id)
            if pack is None or pack.deleted_at is not None or not pack.active:
                raise PaymentError("Ce pack n'existe pas ou n'est plus en vente.")
            if pack.price_stars < 1:
                raise PaymentError("Le prix du pack est invalide.")
            invoice = Invoice(
                token=secrets.token_urlsafe(16),
                pack_id=pack.id,
                chat_id=chat_id,
                buyer_tg_id=chat_id,  # en message privé, la conversation est l'acheteur
                price_stars=pack.price_stars,
            )
            payload = build_payload(invoice.token, invoice.buyer_tg_id, pack.id, chat_id)
            from aiogram.types import LabeledPrice

            try:
                # Stars : devise XTR, provider_token vide, exactement un prix (Bot API, createInvoiceLink).
                link = await bot.create_invoice_link(
                    title=pack.name[:32],
                    description=(pack.description.strip() or pack.name)[:255],
                    payload=payload,
                    currency=CURRENCY,
                    prices=[LabeledPrice(label=pack.name[:32], amount=pack.price_stars)],
                    provider_token="",
                )
            except Exception as exc:
                log.error("Création du lien de paiement impossible pour le pack %s : %s", pack.id, exc)
                raise PaymentError("Telegram a refusé la création du lien de paiement.") from exc
            invoice.link = link
            session.add(invoice)
            await session.commit()
            return invoice

    async def check_pre_checkout(
        self, payload: str, payer_id: int, currency: str, total_amount: int
    ) -> tuple[bool, str | None]:
        """Dernier contrôle avant que Telegram ne débite l'acheteur."""
        data = parse_payload(payload)
        if data is None:
            return False, "Ce lien de paiement n'est pas valide."
        async with self.sessionmaker() as session:
            invoice = await session.scalar(select(Invoice).where(Invoice.token == data.token))
            if invoice is None or invoice.pack_id != data.pack_id or invoice.buyer_tg_id != data.buyer_id:
                return False, "Ce lien de paiement n'est pas valide."
            if invoice.status == "paid":
                return False, "Ce lien a déjà été utilisé. Demandez un nouveau lien si vous souhaitez racheter ce pack."
            if payer_id != invoice.buyer_tg_id:
                return False, "Ce lien est réservé à la personne à qui il a été envoyé."
            pack = await session.get(Pack, invoice.pack_id)
            if pack is None or pack.deleted_at is not None or not pack.active:
                return False, "Ce pack n'est plus en vente."
            if currency != CURRENCY or total_amount != invoice.price_stars or total_amount != pack.price_stars:
                return False, "Le prix de ce pack a changé. Demandez un nouveau lien de paiement."
        return True, None

    async def record_payment(
        self,
        *,
        payload: str,
        payer_id: int,
        currency: str,
        total_amount: int,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None = None,
    ) -> tuple[Sale, bool]:
        """Enregistre une vente. Renvoie (vente, créée) ; `créée` est False si ce paiement était déjà connu."""
        data = parse_payload(payload)
        async with self.sessionmaker() as session:
            existing = await session.scalar(
                select(Sale).where(Sale.telegram_payment_charge_id == telegram_payment_charge_id)
            )
            if existing is not None:
                return existing, False
            invoice = None
            if data is not None:
                invoice = await session.scalar(select(Invoice).where(Invoice.token == data.token))
            sale = Sale(
                buyer_tg_id=payer_id,
                stars=total_amount,
                telegram_payment_charge_id=telegram_payment_charge_id,
                provider_payment_charge_id=provider_payment_charge_id,
                paid_at=utcnow(),
                delivery_status="pending",
                delivery_step=0,
            )
            if invoice is not None:
                sale.invoice_id, sale.pack_id, sale.chat_id = invoice.id, invoice.pack_id, invoice.chat_id
                invoice.status = "paid"
                if payer_id != invoice.buyer_tg_id:
                    sale.delivery_status = "failed"
                    sale.delivery_error = "Le payeur n'est pas le destinataire du lien : livraison à vérifier à la main."
            else:
                sale.chat_id = payer_id
                sale.delivery_status = "failed"
                sale.delivery_error = "Paiement reçu mais non rattaché à un lien connu : à vérifier, puis rembourser si besoin."
            if currency != CURRENCY:
                sale.delivery_status = "failed"
                sale.delivery_error = f"Devise inattendue ({currency})."
            session.add(sale)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(Sale).where(Sale.telegram_payment_charge_id == telegram_payment_charge_id)
                )
                assert existing is not None
                return existing, False
        if sale.delivery_status == "failed":
            log.error("Vente n°%s enregistrée mais non livrable : %s", sale.id, sale.delivery_error)
        else:
            log.info("Vente n°%s enregistrée : %s Stars", sale.id, sale.stars)
        await self.bus.publish("sale", sale_id=sale.id, chat_id=sale.chat_id, kind="new", stars=sale.stars)
        return sale, True

    async def refund(self, sale_id: int) -> Sale:
        bot = self.get_bot()
        if bot is None:
            raise PaymentError("Le bot de paiement n'est pas configuré : remboursement impossible.")
        async with self.sessionmaker() as session:
            sale = await session.get(Sale, sale_id)
            if sale is None:
                raise PaymentError("Vente introuvable.")
            if sale.refunded_at is not None:
                raise PaymentError("Cette vente a déjà été remboursée.")
            try:
                await bot.refund_star_payment(
                    user_id=sale.buyer_tg_id, telegram_payment_charge_id=sale.telegram_payment_charge_id
                )
            except Exception as exc:
                if "ALREADY_REFUNDED" not in str(exc).upper():
                    log.error("Remboursement de la vente n°%s refusé par Telegram : %s", sale.id, exc)
                    raise PaymentError(f"Telegram a refusé le remboursement : {exc}") from exc
            sale.refunded_at = utcnow()
            await session.commit()
        log.info("Vente n°%s remboursée (%s Stars)", sale.id, sale.stars)
        await self.bus.publish("sale", sale_id=sale.id, chat_id=sale.chat_id, kind="refunded")
        return sale

"""Livraison d'un pack après paiement, dans la conversation privée, via le userbot.

Idempotence : une vente est « réservée » par une mise à jour atomique avant tout envoi ;
deux traitements simultanés du même paiement ne peuvent donc pas livrer deux fois.
L'avancement est mémorisé étape par étape pour reprendre sans rien renvoyer en double.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..events import EventBus
from ..models import Pack, Sale, utcnow
from ..settings_store import load_settings
from .chatlog import Outbox

log = logging.getLogger("app.delivery")


def pack_files_dir(data_dir: str, pack_id: int) -> str:
    return os.path.join(data_dir, "packs", str(pack_id))


class DeliveryService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        outbox: Outbox,
        bus: EventBus,
        data_dir: str,
        is_ready: Callable[[], bool] = lambda: True,
    ):
        self.is_ready = is_ready  # userbot connecté ? sinon la vente reste « en attente »
        self.sessionmaker = sessionmaker
        self.outbox = outbox
        self.bus = bus
        self.data_dir = data_dir

    async def deliver(self, sale_id: int) -> bool:
        """Livre la vente si elle ne l'a pas déjà été. Renvoie True si cet appel a terminé la livraison."""
        if not self.is_ready():
            log.warning("Vente n°%s payée mais compte Telegram déconnecté : livraison dès la reconnexion", sale_id)
            return False
        async with self.sessionmaker() as session:
            claimed = await session.execute(
                update(Sale)
                .where(
                    Sale.id == sale_id,
                    Sale.delivery_status.in_(("pending", "failed")),
                    Sale.refunded_at.is_(None),
                    Sale.pack_id.is_not(None),
                    Sale.chat_id.is_not(None),
                )
                .values(delivery_status="delivering", delivery_error=None)
            )
            await session.commit()
            if claimed.rowcount != 1:
                return False
            sale = await session.get(Sale, sale_id)
            pack = await session.get(Pack, sale.pack_id)
            settings = await load_settings(session)
            chat_id, step = sale.chat_id, sale.delivery_step or 0
            files = [(f.filename, os.path.join(pack_files_dir(self.data_dir, pack.id), f.stored_name)) for f in pack.files]
            body = [p for p in ((settings.delivery_intro or "").strip(), (pack.content_text or "").strip(), (pack.content_link or "").strip()) if p]
            meta = {"sale_id": sale.id, "pack_id": pack.id, "pack_name": pack.name}

        # Première étape : le texte (mot d'accueil, contenu, lien) ; puis un fichier par étape.
        steps: list[dict] = [{"text": "\n\n".join(body)}] if body else []
        steps += [{"file_path": path, "filename": name} for name, path in files]

        try:
            if not (pack.content_text or pack.content_link or files):
                raise RuntimeError("Ce pack n'a aucun contenu à livrer.")
            for index in range(step, len(steps)):
                await self.outbox.send(chat_id, sender="system", kind="delivery", meta=meta, **steps[index])
                async with self.sessionmaker() as session:
                    await session.execute(update(Sale).where(Sale.id == sale_id).values(delivery_step=index + 1))
                    await session.commit()
        except Exception as exc:
            log.error("Livraison de la vente n°%s interrompue : %s", sale_id, exc, exc_info=True)
            async with self.sessionmaker() as session:
                await session.execute(
                    update(Sale).where(Sale.id == sale_id).values(delivery_status="failed", delivery_error=str(exc)[:500])
                )
                await session.commit()
            await self.bus.publish("sale", sale_id=sale_id, chat_id=chat_id)
            return False

        async with self.sessionmaker() as session:
            await session.execute(
                update(Sale).where(Sale.id == sale_id).values(delivery_status="delivered", delivered_at=utcnow())
            )
            await session.commit()
        log.info("Vente n°%s livrée (pack « %s »)", sale_id, pack.name)
        await self.bus.publish("sale", sale_id=sale_id, chat_id=chat_id)
        return True

    async def recover(self) -> None:
        """Au démarrage : une livraison coupée en plein envoi passe en échec (relance manuelle depuis le site)."""
        async with self.sessionmaker() as session:
            result = await session.execute(
                update(Sale)
                .where(Sale.delivery_status == "delivering")
                .values(delivery_status="failed", delivery_error="Livraison interrompue par un redémarrage. Relancez-la depuis le site.")
            )
            await session.commit()
            if result.rowcount:
                log.warning("%s livraison(s) interrompue(s) à relancer depuis le site", result.rowcount)

    async def deliver_pending(self) -> None:
        """Livre les ventes payées pendant que le compte Telegram était déconnecté."""
        async with self.sessionmaker() as session:
            ids = (
                await session.scalars(
                    select(Sale.id).where(Sale.delivery_status == "pending", Sale.refunded_at.is_(None)).order_by(Sale.id)
                )
            ).all()
        for sale_id in ids:
            await self.deliver(sale_id)

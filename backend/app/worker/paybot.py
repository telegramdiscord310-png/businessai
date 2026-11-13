"""Bot de paiement (aiogram) : contrôle avant paiement et traitement des paiements en Stars."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery
from aiogram.utils.token import TokenValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..events import EventBus
from ..services.delivery import DeliveryService
from ..services.payments import PaymentService
from ..settings_store import load_settings, save_settings

log = logging.getLogger("app.paybot")


def build_router(payments: PaymentService, delivery: DeliveryService) -> Router:
    router = Router(name="paiements")

    @router.pre_checkout_query()
    async def on_pre_checkout(query: PreCheckoutQuery) -> None:
        # Telegram attend la réponse sous 10 secondes.
        try:
            ok, error = await asyncio.wait_for(
                payments.check_pre_checkout(
                    payload=query.invoice_payload, payer_id=query.from_user.id,
                    currency=query.currency, total_amount=query.total_amount,
                ),
                timeout=8,
            )
        except Exception:
            log.exception("Contrôle avant paiement en échec")
            ok, error = False, "Paiement momentanément indisponible. Réessayez dans un instant."
        if not ok:
            log.warning("Paiement refusé avant débit : %s", error)
        await query.answer(ok=ok, error_message=None if ok else error)

    @router.message(F.successful_payment)
    async def on_successful_payment(message: Message) -> None:
        payment = message.successful_payment
        sale, _created = await payments.record_payment(
            payload=payment.invoice_payload,
            payer_id=message.from_user.id,
            currency=payment.currency,
            total_amount=payment.total_amount,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id,
        )
        # La livraison est idempotente : si Telegram rejoue ce paiement, rien n'est renvoyé.
        await delivery.deliver(sale.id)
        try:
            await message.answer("Merci, paiement bien reçu ✅ Votre contenu arrive dans notre conversation privée.")
        except Exception:
            pass

    @router.message(Command("paysupport"))
    async def on_paysupport(message: Message) -> None:
        await message.answer("Pour toute question sur un paiement, écrivez directement au vendeur dans votre conversation privée.")

    @router.message()
    async def on_other(message: Message) -> None:
        if message.chat.type == "private":
            await message.answer("Ce bot sert uniquement à régler vos achats. Pour toute question, écrivez au vendeur en message privé.")

    return router


class PayBot:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], bus: EventBus) -> None:
        self.sessionmaker = sessionmaker
        self.bus = bus
        self.bot: Bot | None = None
        self.username: str | None = None
        self.error: str | None = None
        self.payments: PaymentService | None = None
        self.delivery: DeliveryService | None = None
        self._dispatcher: Dispatcher | None = None
        self._task: asyncio.Task | None = None

    def get_bot(self) -> Bot | None:
        return self.bot

    def status(self) -> dict:
        return {"running": self.bot is not None, "username": self.username, "error": self.error}

    async def stop(self) -> None:
        if self._dispatcher is not None and self._task is not None and not self._task.done():
            try:
                await self._dispatcher.stop_polling()
            except Exception:
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self.bot is not None:
            await self.bot.session.close()
        self.bot, self._dispatcher, self._task = None, None, None

    async def reload(self) -> dict:
        """(Re)démarre le bot avec le token enregistré. Appelé au démarrage et quand le token change."""
        await self.stop()
        self.error, self.username = None, None
        async with self.sessionmaker() as session:
            settings = await load_settings(session)
            token = settings.bot_token
        if not token:
            return self.status()
        try:
            bot = Bot(token=token)
            me = await bot.get_me(request_timeout=15)
        except TokenValidationError:
            self.error = "Ce token n'a pas le bon format. Copiez-le tel que BotFather vous l'a donné."
            return self.status()
        except TelegramUnauthorizedError:
            self.error = "Telegram refuse ce token. Vérifiez-le auprès de BotFather."
            await bot.session.close()
            return self.status()
        except Exception as exc:
            self.error = "Impossible de joindre Telegram pour vérifier le bot. Réessayez dans un instant."
            log.warning("Vérification du bot de paiement impossible (%s)", exc.__class__.__name__)
            await bot.session.close()
            return self.status()
        self.bot, self.username = bot, me.username
        async with self.sessionmaker() as session:
            await save_settings(session, {"bot_username": me.username})
            await session.commit()
        dispatcher = Dispatcher()
        dispatcher.include_router(build_router(self.payments, self.delivery))
        self._dispatcher = dispatcher
        self._task = asyncio.create_task(self._poll(bot, dispatcher))
        log.info("Bot de paiement démarré (@%s)", me.username)
        await self.bus.publish("status")
        return self.status()

    async def _poll(self, bot: Bot, dispatcher: Dispatcher) -> None:
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await dispatcher.start_polling(
                bot, handle_signals=False, close_bot_session=False,
                allowed_updates=["message", "pre_checkout_query"],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Le bot de paiement s'est arrêté de façon inattendue")
            self.error = "Le bot de paiement s'est arrêté. Redémarrez-le depuis les paramètres."

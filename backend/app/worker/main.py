"""Point d'entrée du worker Telegram : userbot + bot de paiement + API interne."""
from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn

from ..config import get_config
from ..db import dispose_engine, get_engine, get_sessionmaker
from ..events import PgBus
from ..logs import setup_logging
from ..services.ai_client import AIConfig, OpenAICompatClient
from ..services.chatlog import Outbox
from ..services.delivery import DeliveryService
from ..services.payments import PaymentService
from ..services.reply_engine import ReplyEngine
from ..settings_store import Settings
from .paybot import PayBot
from .rpc import create_rpc_app
from .userbot import TelegramManager

log = logging.getLogger("app.worker")


def ai_factory(settings: Settings) -> OpenAICompatClient:
    return OpenAICompatClient(
        AIConfig(
            base_url=settings.ai_base_url, model=settings.ai_model,
            api_key=settings.ai_api_key or "", temperature=float(settings.ai_temperature),
        )
    )


async def main() -> None:
    config = get_config()
    db_logs = setup_logging("telegram")
    if not config.fernet_key or not config.internal_token:
        raise SystemExit("FERNET_KEY et INTERNAL_TOKEN doivent être renseignés dans le fichier .env.")
    sessionmaker = get_sessionmaker()
    bus = PgBus(get_engine())
    log_task = asyncio.create_task(db_logs.run(sessionmaker))

    telegram = TelegramManager(sessionmaker, bus, config)
    paybot = PayBot(sessionmaker, bus)
    outbox = Outbox(sessionmaker, telegram, bus)
    payments = PaymentService(sessionmaker, paybot.get_bot, bus)
    delivery = DeliveryService(sessionmaker, outbox, bus, config.data_dir, is_ready=lambda: telegram.ready)
    engine = ReplyEngine(sessionmaker, outbox, payments, bus, ai_factory)
    telegram.engine, telegram.delivery = engine, delivery
    paybot.payments, paybot.delivery = payments, delivery

    await delivery.recover()
    try:
        await paybot.reload()
    except Exception:
        log.exception("Démarrage du bot de paiement impossible")
    await telegram.start()

    server = uvicorn.Server(
        uvicorn.Config(
            create_rpc_app(telegram, engine, paybot, payments, delivery),
            host="0.0.0.0", port=config.worker_port, log_config=None, access_log=False,
        )
    )
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    server_task = asyncio.create_task(server.serve())
    log.info("Service Telegram démarré")
    await stop.wait()

    log.info("Arrêt du service Telegram")
    server.should_exit = True
    await engine.shutdown()
    await paybot.stop()
    await telegram.stop()
    await asyncio.gather(server_task, return_exceptions=True)
    await asyncio.sleep(0.2)
    log_task.cancel()
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

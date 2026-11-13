"""Userbot Telethon : connexion du compte personnel, réception des messages, envois.

La session est conservée chiffrée en base (jamais en clair, jamais dans les journaux).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession
from telethon.tl import types

from .. import crypto
from ..config import Config
from ..events import EventBus
from ..models import Chat, Message, TelegramAccount, utcnow
from ..services import chatlog
from ..services.chatlog import PeerInfo
from ..services.reply_engine import Incoming
from .media import describe_media

log = logging.getLogger("app.telegram")
SERVICE_ACCOUNTS = {777000, 42777}
LOGIN_TTL = 15 * 60


class TgError(Exception):
    """Erreur présentable telle quelle (en français)."""

    user_facing = True


def human_wait(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} secondes"
    if seconds < 5400:
        return f"{round(seconds / 60)} minutes"
    return f"{round(seconds / 3600)} heures"


def peer_info(user, fallback_id: int | None = None) -> PeerInfo | None:
    if user is None or not isinstance(user, types.User):
        return None
    return PeerInfo(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        access_hash=user.access_hash,
        is_bot=bool(user.bot),
        is_self=bool(user.is_self),
        is_service_account=user.id in SERVICE_ACCOUNTS or bool(user.support) or bool(user.deleted),
    )


class TelegramManager:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], bus: EventBus, config: Config) -> None:
        self.sessionmaker = sessionmaker
        self.bus = bus
        self.config = config
        self.client: TelegramClient | None = None
        self.ready = False
        self.engine = None  # ReplyEngine, branché par worker.main
        self.delivery = None  # DeliveryService
        self._login: TelegramClient | None = None
        self._login_phone: str | None = None
        self._login_at = 0.0
        self._supervisor: asyncio.Task | None = None
        self._stopping = False
        self._flood_until = 0.0
        self._background: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ état

    async def _account(self, session: AsyncSession) -> TelegramAccount:
        account = await session.get(TelegramAccount, 1)
        if account is None:
            account = TelegramAccount(id=1, status="disconnected")
            session.add(account)
            await session.flush()
        return account

    async def _set_status(self, status: str, error: str | None = None, **fields) -> None:
        async with self.sessionmaker() as session:
            account = await self._account(session)
            account.status, account.last_error = status, error
            for key, value in fields.items():
                setattr(account, key, value)
            await session.commit()
        self.ready = status == "connected"
        await self.bus.publish("telegram", status=status)

    def _make_client(self, session_string: str, api_id: int, api_hash: str) -> TelegramClient:
        return TelegramClient(
            StringSession(session_string),
            api_id,
            api_hash,
            device_model="BusinessAI",
            system_version="Serveur",
            app_version="1.0",
            lang_code="fr",
            system_lang_code="fr",
            flood_sleep_threshold=60,  # Telethon patiente seul pour les attentes courtes
            connection_retries=8,
            retry_delay=2,
            auto_reconnect=True,
            receive_updates=True,
        )

    # --------------------------------------------------------------- connexion du compte

    async def _drop_login(self) -> None:
        if self._login is not None:
            try:
                await self._login.disconnect()
            except Exception:
                pass
        self._login, self._login_phone = None, None

    def _login_client(self) -> TelegramClient:
        if self._login is None or time.monotonic() - self._login_at > LOGIN_TTL:
            raise TgError("La demande de connexion a expiré. Recommencez depuis la première étape.")
        return self._login

    async def send_code(self, api_id: int, api_hash: str, phone: str) -> dict:
        if self.client is not None and self.ready:
            raise TgError("Un compte est déjà connecté. Déconnectez-le avant d'en connecter un autre.")
        await self._stop_client()
        await self._drop_login()
        client = self._make_client("", api_id, api_hash)
        try:
            await asyncio.wait_for(client.connect(), 25)
            sent = await asyncio.wait_for(client.send_code_request(phone), 30)
        except (errors.ApiIdInvalidError, errors.ApiIdPublishedFloodError):
            await client.disconnect()
            raise TgError("api_id ou api_hash incorrect. Vérifiez-les sur my.telegram.org.")
        except errors.PhoneNumberInvalidError:
            await client.disconnect()
            raise TgError("Numéro de téléphone invalide. Utilisez le format international, par exemple +33612345678.")
        except errors.PhoneNumberBannedError:
            await client.disconnect()
            raise TgError("Ce numéro est banni de Telegram.")
        except errors.FloodWaitError as exc:
            await client.disconnect()
            raise TgError(f"Trop de tentatives : Telegram demande d'attendre {human_wait(exc.seconds)} avant de réessayer.")
        except errors.RPCError as exc:
            await client.disconnect()
            raise TgError(f"Telegram a refusé la demande ({exc.__class__.__name__}).")
        except (OSError, asyncio.TimeoutError, ConnectionError) as exc:
            await client.disconnect()
            log.warning("Connexion aux serveurs Telegram impossible : %s", exc.__class__.__name__)
            raise TgError("Impossible de joindre les serveurs de Telegram. Vérifiez la connexion Internet du serveur, puis réessayez.")
        self._login, self._login_phone, self._login_at = client, phone, time.monotonic()
        await self._set_status(
            "code_sent", None, api_id=api_id, api_hash_enc=crypto.encrypt(api_hash), phone=phone, session_enc=None
        )
        by_app = isinstance(sent.type, types.auth.SentCodeTypeApp)
        return {"status": "code_sent", "delivery": "app" if by_app else "sms"}

    async def sign_in(self, code: str) -> dict:
        client = self._login_client()
        try:
            me = await client.sign_in(self._login_phone, code)
        except errors.SessionPasswordNeededError:
            await self._set_status("password_needed")
            return {"status": "password_needed"}
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
            raise TgError("Code incorrect. Vérifiez le code reçu dans Telegram et réessayez.")
        except errors.PhoneCodeExpiredError:
            await self._drop_login()
            await self._set_status("disconnected")
            raise TgError("Ce code a expiré. Recommencez pour en recevoir un nouveau.")
        except errors.FloodWaitError as exc:
            raise TgError(f"Trop de tentatives : attendez {human_wait(exc.seconds)} avant de réessayer.")
        except errors.RPCError as exc:
            raise TgError(f"Telegram a refusé la connexion ({exc.__class__.__name__}).")
        return await self._finish_login(client, me)

    async def check_password(self, password: str) -> dict:
        client = self._login_client()
        try:
            me = await client.sign_in(password=password)
        except errors.PasswordHashInvalidError:
            raise TgError("Mot de passe de validation en deux étapes incorrect.")
        except errors.FloodWaitError as exc:
            raise TgError(f"Trop de tentatives : attendez {human_wait(exc.seconds)} avant de réessayer.")
        except errors.RPCError as exc:
            raise TgError(f"Telegram a refusé la connexion ({exc.__class__.__name__}).")
        return await self._finish_login(client, me)

    async def _finish_login(self, client: TelegramClient, me) -> dict:
        session_string = client.session.save()
        self._login, self._login_phone = None, None
        self.client = client
        await self._set_status(
            "connected", None,
            session_enc=crypto.encrypt(session_string),
            me_id=me.id,
            me_name=" ".join(p for p in (me.first_name, me.last_name) if p),
            me_username=me.username,
        )
        log.info("Compte Telegram connecté")
        self._attach_handlers(client)
        self._start_supervisor()
        return {"status": "connected"}

    async def logout(self) -> None:
        """Déconnexion : la session est révoquée côté Telegram puis effacée de la base."""
        self._stopping = True
        if self._supervisor:
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
            self._supervisor = None
        await self._drop_login()
        client, self.client, self.ready = self.client, None, False
        revoked = False
        try:
            if client is None:
                async with self.sessionmaker() as session:
                    account = await self._account(session)
                    if account.session_enc and account.api_id and account.api_hash_enc:
                        client = self._make_client(
                            crypto.decrypt(account.session_enc), account.api_id, crypto.decrypt(account.api_hash_enc)
                        )
            if client is not None:
                if not client.is_connected():
                    await asyncio.wait_for(client.connect(), 20)
                revoked = bool(await asyncio.wait_for(client.log_out(), 20))
        except Exception as exc:
            log.warning("Révocation de la session auprès de Telegram impossible (%s)", exc.__class__.__name__)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            self._stopping = False
        await self._set_status(
            "disconnected",
            None if revoked else "Session effacée du site. Si elle apparaît encore dans Telegram → Paramètres → Appareils, fermez-la à la main.",
            session_enc=None, me_id=None, me_name=None, me_username=None,
        )
        log.info("Compte Telegram déconnecté")

    # --------------------------------------------------------------------- cycle de vie

    async def start(self) -> None:
        async with self.sessionmaker() as session:
            account = await self._account(session)
            has_session = bool(account.session_enc)
            if not has_session and account.status != "disconnected":
                account.status = "disconnected"  # une connexion en cours n'a pas survécu au redémarrage
            await session.commit()
        if has_session:
            self._start_supervisor()

    def _start_supervisor(self) -> None:
        if self._supervisor is None or self._supervisor.done():
            self._supervisor = asyncio.create_task(self._supervise())

    async def _stop_client(self) -> None:
        if self._supervisor:
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
            self._supervisor = None
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client, self.ready = None, False

    async def stop(self) -> None:
        self._stopping = True
        await self._drop_login()
        await self._stop_client()

    async def _supervise(self) -> None:
        """Maintient la connexion : reconnexion automatique avec attente croissante."""
        backoff = 2
        while not self._stopping:
            try:
                if self.client is None:
                    async with self.sessionmaker() as session:
                        account = await self._account(session)
                        if not account.session_enc:
                            return
                        self.client = self._make_client(
                            crypto.decrypt(account.session_enc), account.api_id, crypto.decrypt(account.api_hash_enc)
                        )
                    self._attach_handlers(self.client)
                client = self.client
                if not client.is_connected():
                    await self._set_status("connecting")
                    await client.connect()
                if not await client.is_user_authorized():
                    await self._session_lost("La session a été fermée depuis Telegram. Reconnectez votre compte.")
                    return
                me = await client.get_me()
                await self._set_status(
                    "connected", None, me_id=me.id,
                    me_name=" ".join(p for p in (me.first_name, me.last_name) if p), me_username=me.username,
                )
                backoff = 2
                if self.delivery is not None:
                    self._spawn(self.delivery.deliver_pending())
                await client.disconnected  # se termine quand la connexion est définitivement perdue
                if self._stopping:
                    return
                log.warning("Connexion à Telegram perdue : nouvelle tentative dans %s s", backoff)
                await self._set_status("connecting", "Connexion perdue, reconnexion en cours…")
            except asyncio.CancelledError:
                raise
            except (
                errors.AuthKeyUnregisteredError, errors.AuthKeyDuplicatedError, errors.SessionRevokedError,
                errors.UserDeactivatedError, errors.UserDeactivatedBanError, errors.AuthKeyInvalidError,
            ) as exc:
                await self._session_lost(f"Telegram a invalidé la session ({exc.__class__.__name__}). Reconnectez votre compte.")
                return
            except errors.FloodWaitError as exc:
                log.warning("Telegram demande d'attendre %s avant de se reconnecter", human_wait(exc.seconds))
                await self._set_status("error", f"Telegram demande d'attendre {human_wait(exc.seconds)}. Reconnexion automatique ensuite.")
                backoff = exc.seconds + 5
            except crypto.CryptoError as exc:
                await self._set_status("error", str(exc))
                log.error("%s", exc)
                return
            except Exception as exc:
                log.error("Connexion à Telegram en échec (%s) : nouvelle tentative dans %s s", exc.__class__.__name__, backoff)
                await self._set_status("error", "Connexion à Telegram impossible pour le moment. Nouvelle tentative automatique en cours.")
            await asyncio.sleep(backoff)
            backoff = min(max(backoff, 2) * 2, 300)

    async def _session_lost(self, message: str) -> None:
        log.error("%s", message)
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        await self._set_status("disconnected", message, session_enc=None)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    # ------------------------------------------------------------------------ réception

    def _attach_handlers(self, client: TelegramClient) -> None:
        if getattr(client, "_ba_handlers", False):
            return
        client._ba_handlers = True  # type: ignore[attr-defined]
        client.add_event_handler(self._on_incoming, events.NewMessage(incoming=True))
        client.add_event_handler(self._on_outgoing, events.NewMessage(outgoing=True))

    async def _resolve_user(self, event):
        try:
            entity = await event.get_chat()
            if entity is None:
                entity = await event.client.get_entity(types.PeerUser(event.chat_id))
            return entity
        except Exception:
            return None

    async def _build(self, event, outgoing: bool) -> Incoming | None:
        msg = event.message
        peer = peer_info(await self._resolve_user(event))
        if peer is None:
            log.warning("Message privé ignoré : expéditeur impossible à identifier")
            return None
        media_type, media_desc = describe_media(msg)
        return Incoming(
            peer=peer, tg_message_id=msg.id, text=msg.message or "", date=utcnow(),
            is_private=True, is_outgoing=outgoing, is_service=isinstance(msg, types.MessageService),
            media_type=media_type, media_desc=media_desc,
        )

    async def _on_incoming(self, event) -> None:
        try:
            if not event.is_private or self.engine is None:
                return  # groupes et canaux : ignorés
            incoming = await self._build(event, outgoing=False)
            if incoming is None:
                return
            stored = await self.engine.on_incoming(incoming)
            if stored is not None:
                self._spawn(self._after_store(event, stored.id, incoming.peer.id, bool(incoming.media_type)))
        except Exception:
            log.exception("Erreur pendant le traitement d'un message reçu")

    async def _on_outgoing(self, event) -> None:
        try:
            if not event.is_private or self.engine is None:
                return
            incoming = await self._build(event, outgoing=True)
            if incoming is None:
                return
            stored = await self.engine.on_owner_message(incoming)
            if stored is not None and incoming.media_type:
                self._spawn(self._after_store(event, stored.id, incoming.peer.id, True, avatar=False))
        except Exception:
            log.exception("Erreur pendant le traitement d'un message envoyé depuis Telegram")

    async def _after_store(self, event, message_id: int, chat_id: int, has_media: bool, avatar: bool = True) -> None:
        """Tâches annexes, sans effet sur la réponse : pièce jointe et photo de profil."""
        try:
            if has_media:
                await self._download_media(event.message, message_id, chat_id)
            if avatar:
                await self.refresh_avatar(chat_id)
        except Exception:
            log.warning("Pièce jointe ou photo de profil non récupérée", exc_info=True)

    async def _download_media(self, msg, message_id: int, chat_id: int) -> None:
        size = 0
        try:
            size = int(msg.file.size or 0)
        except Exception:
            pass
        if msg.file is None or size > self.config.media_max_mb * 1024 * 1024:
            return
        ext = (msg.file.ext or "").lower() or ".bin"
        if getattr(msg, "photo", None):
            ext = ".jpg"
        folder = os.path.join(self.config.data_dir, "media", str(chat_id))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{message_id}{ext}")
        saved = await self.client.download_media(msg, file=path)
        if not saved:
            return
        async with self.sessionmaker() as session:
            row = await session.get(Message, message_id)
            if row is not None:
                row.media_path = os.path.relpath(saved, self.config.data_dir)
                await session.commit()
        await self.bus.publish("message", chat_id=chat_id, message_id=message_id)

    async def refresh_avatar(self, chat_id: int, force: bool = False) -> None:
        async with self.sessionmaker() as session:
            chat = await session.get(Chat, chat_id)
            if chat is None:
                return
            if not force and chat.photo_checked_at and (utcnow() - chat.photo_checked_at).total_seconds() < 86400:
                return
        folder = os.path.join(self.config.data_dir, "avatars")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{chat_id}.jpg")
        saved = await self.client.download_profile_photo(await self._peer(chat_id), file=path, download_big=False)
        async with self.sessionmaker() as session:
            chat = await session.get(Chat, chat_id)
            chat.has_photo, chat.photo_checked_at = bool(saved), utcnow()
            await session.commit()
        if saved:
            await self.bus.publish("chat", chat_id=chat_id)

    # --------------------------------------------------------------------------- envois

    def _require_client(self) -> TelegramClient:
        if self.client is None or not self.ready:
            raise TgError("Le compte Telegram n'est pas connecté.")
        return self.client

    async def _peer(self, chat_id: int):
        async with self.sessionmaker() as session:
            chat = await session.get(Chat, chat_id)
        if chat is not None and chat.access_hash is not None:
            return types.InputPeerUser(chat_id, chat.access_hash)
        try:
            return await self._require_client().get_input_entity(types.PeerUser(chat_id))
        except Exception:
            raise TgError("Impossible d'écrire à cette personne : elle doit d'abord vous envoyer un message.")

    async def _call(self, fn):
        """Exécute un envoi en gérant proprement les limites de Telegram (FloodWait)."""
        remaining = self._flood_until - time.monotonic()
        if remaining > 0:
            raise TgError(f"Telegram impose une pause : envois suspendus encore {human_wait(int(remaining))}.")
        try:
            return await fn()
        except errors.FloodWaitError as exc:
            if exc.seconds <= 120:
                log.warning("Telegram demande d'attendre %s s avant l'envoi : on patiente", exc.seconds)
                await asyncio.sleep(exc.seconds + 1)
                return await fn()
            self._flood_until = time.monotonic() + exc.seconds
            log.error("Telegram impose une pause de %s : les envois reprendront ensuite", human_wait(exc.seconds))
            raise TgError(f"Telegram impose une pause de {human_wait(exc.seconds)} avant tout nouvel envoi.")
        except errors.PeerFloodError:
            self._flood_until = time.monotonic() + 3600
            log.error("Telegram limite les envois de ce compte (trop de messages). Envois suspendus pendant 1 heure.")
            raise TgError("Telegram limite temporairement les envois de ce compte. Réessayez plus tard.")
        except (errors.UserIsBlockedError, errors.InputUserDeactivatedError):
            raise TgError("Cette personne vous a bloqué ou a supprimé son compte : message non envoyé.")

    async def send_text(self, chat_id: int, text: str) -> int:
        client = self._require_client()
        peer = await self._peer(chat_id)
        msg = await self._call(lambda: client.send_message(peer, text, parse_mode=None))
        return msg.id

    async def send_file(self, chat_id: int, path: str, filename: str | None = None, caption: str | None = None) -> int:
        client = self._require_client()
        if not os.path.isfile(path):
            raise TgError(f"Fichier introuvable sur le serveur : {filename or os.path.basename(path)}")
        peer = await self._peer(chat_id)
        attributes = [types.DocumentAttributeFilename(filename)] if filename else None
        msg = await self._call(
            lambda: client.send_file(
                peer, path, caption=caption, parse_mode=None, attributes=attributes, supports_streaming=True
            )
        )
        return msg.id

    async def typing(self, chat_id: int, seconds: float) -> None:
        if seconds <= 0:
            return
        try:
            client = self._require_client()
            peer = await self._peer(chat_id)
            async with client.action(peer, "typing"):
                await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise
        except TgError:
            raise
        except Exception:
            await asyncio.sleep(seconds)  # l'indicateur est cosmétique : on garde quand même le délai

    async def mark_read(self, chat_id: int) -> None:
        client = self._require_client()
        await client.send_read_acknowledge(await self._peer(chat_id))

    # ------------------------------------------------------------------------- historique

    async def import_history(self, chat_id: int, limit: int = 300) -> int:
        client = self._require_client()
        peer = await self._peer(chat_id)
        items: list[dict] = []
        try:
            async for msg in client.iter_messages(peer, limit=limit):
                if isinstance(msg, types.MessageService):
                    continue
                media_type, media_desc = describe_media(msg)
                items.append({
                    "tg_message_id": msg.id, "out": bool(msg.out), "text": msg.message or "", "date": msg.date,
                    "media_type": media_type, "media_desc": media_desc,
                })
        except errors.FloodWaitError as exc:
            raise TgError(f"Telegram demande d'attendre {human_wait(exc.seconds)} avant de relire l'historique.")
        items.reverse()
        async with self.outbox_lock(chat_id):
            async with self.sessionmaker() as session:
                chat = await session.get(Chat, chat_id)
                if chat is None:
                    raise TgError("Conversation introuvable.")
                added = await chatlog.import_history(session, chat, items)
                await session.commit()
        await self.bus.publish("chat", chat_id=chat_id)
        await self.bus.publish("message", chat_id=chat_id, message_id=None)
        return added

    def outbox_lock(self, chat_id: int):
        return self.engine.outbox.lock(chat_id)

"""Bus d'événements temps réel.

Le worker Telegram et le backend publient via NOTIFY Postgres ; le backend écoute (LISTEN)
et redistribue aux navigateurs connectés en SSE. En test, un bus en mémoire le remplace.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("app.events")
CHANNEL = "app_events"


class EventBus(Protocol):
    async def publish(self, type_: str, **data: Any) -> None: ...


class MemoryBus:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.subscribers: set[asyncio.Queue] = set()

    async def publish(self, type_: str, **data: Any) -> None:
        event = {"type": type_, **data}
        self.events.append(event)
        for q in list(self.subscribers):
            q.put_nowait(event)

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == type_]


class PgBus:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def publish(self, type_: str, **data: Any) -> None:
        payload = json.dumps({"type": type_, **data}, default=str)
        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": payload})
        except Exception:  # un événement perdu ne doit jamais casser le traitement
            log.warning("Événement temps réel non publié (%s)", type_, exc_info=True)


class EventHub:
    """Côté backend : écoute Postgres et alimente les abonnés SSE."""

    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def dispatch(self, event: dict[str, Any]) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self.subscribers.discard(q)

    async def start(self, database_url: str) -> None:
        self._task = asyncio.create_task(self._listen(database_url))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _listen(self, database_url: str) -> None:
        import asyncpg

        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")

        def on_notify(_conn, _pid, _channel, payload: str) -> None:
            try:
                self.dispatch(json.loads(payload))
            except Exception:
                log.warning("Événement illisible ignoré")

        while True:
            conn = None
            try:
                conn = await asyncpg.connect(dsn)
                await conn.add_listener(CHANNEL, on_notify)
                # Après une reconnexion, on demande aux navigateurs de tout rafraîchir.
                self.dispatch({"type": "resync"})
                while not conn.is_closed():
                    await asyncio.sleep(15)
                    await conn.execute("SELECT 1")
            except asyncio.CancelledError:
                if conn and not conn.is_closed():
                    await conn.close()
                raise
            except Exception:
                log.warning("Écoute des événements interrompue, nouvelle tentative dans 3 s")
            await asyncio.sleep(3)

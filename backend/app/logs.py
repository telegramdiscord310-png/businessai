"""Journal applicatif : écrit en base (page « Logs ») et masque tout ce qui ressemble à un secret."""
from __future__ import annotations

import asyncio
import logging
import re
import traceback
from datetime import timedelta

from sqlalchemy import delete

from .models import LogEntry, utcnow

_REDACTIONS = [
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "[token masqué]"),  # token de bot Telegram
    (re.compile(r"\b(?:sk|xai|gsk|pk)-[A-Za-z0-9_-]{16,}\b"), "[clé masquée]"),  # clés API
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{16,}"), r"\1[masqué]"),
    (re.compile(r"\b1[A-Za-z0-9_-]{200,}={0,2}"), "[session masquée]"),  # StringSession Telethon
    (re.compile(r"gAAAA[A-Za-z0-9_-]{40,}={0,2}"), "[chiffré]"),  # jeton Fernet
    (re.compile(r"(?i)((?:api_hash|password|phone_code_hash|phone_code|bot_token|api_key)\s*[=:]\s*)['\"]?[^\s'\",)]+"), r"\1[masqué]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = None
        except Exception:
            pass
        return True


class DBLogHandler(logging.Handler):
    """Met les entrées en file ; une tâche de fond les écrit en base par lots."""

    def __init__(self, source: str) -> None:
        super().__init__(level=logging.INFO)
        self.source = source
        self.queue: asyncio.Queue[LogEntry] = asyncio.Queue(maxsize=2000)

    def emit(self, record: logging.LogRecord) -> None:
        # INFO uniquement pour nos propres modules ; les bibliothèques à partir de WARNING.
        if record.levelno < logging.WARNING and not record.name.startswith("app"):
            return
        if record.name.startswith(("sqlalchemy", "app.logs")):
            return
        try:
            details = None
            if record.exc_info and record.exc_info[0] is not None:
                details = redact("".join(traceback.format_exception(*record.exc_info)))[-8000:]
            entry = LogEntry(
                level=record.levelname,
                source=self.source,
                logger=record.name[:128],
                message=redact(record.getMessage())[:4000],
                details=details,
            )
            self.queue.put_nowait(entry)
        except Exception:
            pass

    async def run(self, sessionmaker) -> None:
        last_purge = None
        while True:
            entry = await self.queue.get()
            batch = [entry]
            while not self.queue.empty() and len(batch) < 100:
                batch.append(self.queue.get_nowait())
            try:
                async with sessionmaker() as session:
                    session.add_all(batch)
                    now = utcnow()
                    if last_purge is None or now - last_purge > timedelta(hours=6):
                        from .config import get_config

                        limit = now - timedelta(days=get_config().log_retention_days)
                        await session.execute(delete(LogEntry).where(LogEntry.created_at < limit))
                        last_purge = now
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger("app.logs").debug("Écriture du journal impossible", exc_info=True)


def setup_logging(source: str) -> DBLogHandler:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    console.addFilter(RedactFilter())
    db_handler = DBLogHandler(source)
    root.handlers = [console, db_handler]
    for noisy in ("telethon", "aiogram.event", "httpx", "httpcore", "openai", "uvicorn.access", "aiogram.dispatcher"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return db_handler

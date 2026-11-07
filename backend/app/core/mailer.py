"""Outgoing email. Phase 1 uses ConsoleMailer (or FileMailer when MAIL_OUTBOX_DIR is set);
a real ESP plugs in during Phase 3."""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

log = logging.getLogger("versnq.mail")


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    async def send(self, email: Email) -> None: ...


class ConsoleMailer:
    """Writes emails to the log instead of sending them (development only)."""

    async def send(self, email: Email) -> None:
        log.warning("EMAIL to=%s subject=%s\n%s", email.to, email.subject, email.body)


class FileMailer:
    """Saves each email as a JSON file in a folder (dev demos and end-to-end tests only)."""

    def __init__(self, folder: Path):
        self.folder = folder

    async def send(self, email: Email) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns()}-{uuid.uuid4().hex[:6]}.json"
        (self.folder / name).write_text(json.dumps(asdict(email)))
        log.warning("EMAIL to=%s subject=%s saved to %s", email.to, email.subject, name)


_mailer: Mailer = ConsoleMailer()


def get_mailer() -> Mailer:
    settings = get_settings()
    # Emails carry sign-in links, so they are never written to disk in production.
    if settings.mail_outbox_dir and settings.environment != "prod":
        return FileMailer(Path(settings.mail_outbox_dir))
    return _mailer

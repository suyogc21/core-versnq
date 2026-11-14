"""Core's own emails (invites, password resets). SmtpMailer when SYSTEM_SMTP_HOST is set (the
server: the no-reply mailbox), FileMailer for dev demos and tests (MAIL_OUTBOX_DIR), otherwise
ConsoleMailer (the log)."""

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


class SmtpMailer:
    """Sends through the system mailbox. A failure is logged, never raised: the invite or reset
    already exists, and it can be sent again from the screen."""

    async def send(self, email: Email) -> None:
        from email.message import EmailMessage
        from email.utils import formataddr, make_msgid

        from app.modules.money import mailbox as smtp

        s = get_settings()
        sender = s.system_email_from or s.system_smtp_username or ""
        msg = EmailMessage()
        msg["From"] = formataddr((s.system_email_from_name, sender))
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1] or None)
        msg.set_content(email.body)
        box = smtp.Box(
            host=s.system_smtp_host or "",
            port=s.system_smtp_port,
            security=s.system_smtp_security,
            username=s.system_smtp_username or sender,
            password=s.system_smtp_password or "",
            from_name=s.system_email_from_name,
            from_email=sender,
        )
        try:
            await smtp.send(box, msg)
            log.info("EMAIL sent to=%s subject=%s", email.to, email.subject)
        except Exception:  # noqa: BLE001 - logged; the caller's record already exists
            log.exception("EMAIL could not be sent to=%s subject=%s", email.to, email.subject)


_mailer: Mailer = ConsoleMailer()


def get_mailer() -> Mailer:
    settings = get_settings()
    # Emails carry sign-in links, so they are never written to disk in production.
    if settings.mail_outbox_dir and settings.environment != "prod":
        return FileMailer(Path(settings.mail_outbox_dir))
    if settings.system_smtp_host:
        return SmtpMailer()
    return _mailer

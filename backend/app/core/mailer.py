"""Outgoing email. Phase 1 uses ConsoleMailer; a real ESP plugs in during Phase 3."""

import logging
from dataclasses import dataclass
from typing import Protocol

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


_mailer: Mailer = ConsoleMailer()


def get_mailer() -> Mailer:
    return _mailer

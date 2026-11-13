"""Sending invoice emails from the company's own mailbox (SMTP), Decision log #34.

Gmail / Google Workspace (smtp.gmail.com, an app password), Zoho, Outlook or any mail server.
Python's own smtplib does the work; no email service or extra cost.

Safety: only the usual mail ports, and in production the mail server must be on the public
internet (a company cannot point Core at our own private network). Outside production, when
MAIL_OUTBOX_DIR is set, messages are saved there as .eml files instead of being sent.
"""

import asyncio
import ipaddress
import smtplib
import socket
import ssl
import time
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import Invalid

TIMEOUT_S = 20
PORTS = (25, 465, 587, 2525)


@dataclass(frozen=True)
class Box:
    host: str
    port: int
    security: str  # ssl / starttls
    username: str
    password: str
    from_name: str
    from_email: str
    reply_to: str | None = None


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/pdf"


def _check_host(host: str, port: int, ports: tuple[int, ...] = PORTS) -> None:
    if port not in ports:
        raise Invalid(f"Use one of the usual mail ports: {', '.join(map(str, ports))}")
    if get_settings().environment != "prod":
        return
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise Invalid(f"Could not find the mail server {host}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise Invalid("The mail server must be on the internet, not a private address")


def build(box: Box, to: str, subject: str, text: str, files: list[Attachment]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((box.from_name, box.from_email))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=box.from_email.rsplit("@", 1)[-1])
    if box.reply_to:
        msg["Reply-To"] = box.reply_to
    msg.set_content(text)
    for f in files:
        main, sub = f.mime.split("/", 1)
        msg.add_attachment(f.content, maintype=main, subtype=sub, filename=f.filename)
    return msg


def _send_now(box: Box, msg: EmailMessage | None) -> None:
    _check_host(box.host, box.port)
    ctx = ssl.create_default_context()
    if box.security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(box.host, box.port, timeout=TIMEOUT_S, context=ctx)
    else:
        server = smtplib.SMTP(box.host, box.port, timeout=TIMEOUT_S)
    try:
        if box.security == "starttls":
            server.starttls(context=ctx)
        server.login(box.username, box.password)
        if msg is not None:
            server.send_message(msg)
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass


def _outbox() -> Path | None:
    s = get_settings()
    if s.mail_outbox_dir and s.environment != "prod":
        return Path(s.mail_outbox_dir)
    return None


async def send(box: Box, msg: EmailMessage) -> None:
    folder = _outbox()
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{time.time_ns()}-{uuid.uuid4().hex[:6]}.eml").write_bytes(msg.as_bytes())
        return
    try:
        await asyncio.to_thread(_send_now, box, msg)
    except smtplib.SMTPAuthenticationError:
        raise Invalid(
            "The mailbox refused the user name or password", code="mailbox_auth_failed"
        ) from None
    except (smtplib.SMTPException, OSError) as e:
        raise Invalid(
            f"Could not send through the mailbox: {str(e)[:200]}", code="email_send_failed"
        ) from None


async def check(box: Box) -> None:
    """Signs in to the mailbox without sending anything."""
    if _outbox() is not None:
        _check_host(box.host, box.port)
        return
    try:
        await asyncio.to_thread(_send_now, box, None)
    except smtplib.SMTPAuthenticationError:
        raise Invalid(
            "The mailbox refused the user name or password", code="mailbox_auth_failed"
        ) from None
    except (smtplib.SMTPException, OSError) as e:
        raise Invalid(
            f"Could not reach the mailbox: {str(e)[:200]}", code="mailbox_unreachable"
        ) from None

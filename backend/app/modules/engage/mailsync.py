"""Connect my inbox (step 9b-3, Decision log #40): each user's own mailbox, by IMAP + SMTP with
an app password — Gmail (personal too), Google Workspace, Outlook / Office 365, Zoho or any
mail server. Python's own imaplib / smtplib do the work; no extra service.

Two-way:
- Every couple of minutes the worker reads the mailbox's Inbox and Sent folders. It reads only
  the From / To / Cc / Message-ID lines first, and downloads an email only when it is with a
  known lead (and not on the company's exclusion list). The rest of the mailbox is never stored.
- Emails a user writes in Core go out through their own mailbox and a copy is put in their Sent
  folder (Gmail and Outlook do that themselves).

When first connected, the last 30 days are pulled in quietly (I4): on the trail, but nobody is
notified and no sequence stops. Nothing is ever marked read or changed in the mailbox, apart
from that copy in Sent. A wrong password stops the sync and shows on the mailbox until fixed.

Outside production, MAILBOX_TEST_DIR replaces the mail server with folders of .eml files
(<dir>/<address>/<folder>/<uid>.eml), so all of this can be tried before anyone connects one.
"""

import asyncio
import email
import email.policy
import imaplib
import logging
import re
import ssl
import time
import uuid
from datetime import timedelta
from email.utils import getaddresses, parseaddr
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets as SEC
from app.core.config import get_settings
from app.core.errors import Invalid
from app.core.tenancy import tenant_session
from app.modules.crm import leads as L
from app.modules.crm.models import Lead, LeadIdentity
from app.modules.crm.notify import notify
from app.modules.engage import inbox as IB
from app.modules.engage.models import Mailbox
from app.modules.money import mailbox as smtp
from app.modules.settings.models import TenantSettings

log = logging.getLogger(__name__)

IMAP_PORTS = (993, 143)
TIMEOUT_S = 30
BACKFILL_DAYS = 30
BATCH = 200  # emails looked at per folder per run; the next run carries on
EVERY = timedelta(minutes=2)
SLACK = timedelta(minutes=10)
SENT_NAMES = ("[Gmail]/Sent Mail", "Sent Items", "Sent", "Sent Messages", "INBOX.Sent")
# These providers put emails sent through their SMTP in Sent themselves.
SAVES_SENT = ("gmail.com", "googlemail.com", "office365.com", "outlook.com")
HEADERS = "(UID BODY.PEEK[HEADER.FIELDS (FROM TO CC MESSAGE-ID DATE)])"


# ---------- talking to the mail server ----------
class _Imap:
    """A real IMAP connection (blocking; every call runs in a thread)."""

    def __init__(self, mb: Mailbox, password: str):
        ctx = ssl.create_default_context()
        if mb.imap_port == 993:
            self.m = imaplib.IMAP4_SSL(
                mb.imap_host, mb.imap_port, ssl_context=ctx, timeout=TIMEOUT_S
            )
        else:
            self.m = imaplib.IMAP4(mb.imap_host, mb.imap_port, timeout=TIMEOUT_S)
            self.m.starttls(ssl_context=ctx)
        self.m.login(mb.username, password)

    @staticmethod
    def _q(name: str) -> str:
        return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def sent_folder(self) -> str | None:
        typ, rows = self.m.list()
        names = {}
        for row in rows or []:
            line = row.decode(errors="replace") if isinstance(row, bytes) else str(row)
            hit = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
            if not hit:
                continue
            name = hit["name"].strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            if "\\sent" in hit["flags"].lower():
                return name
            names[name.lower()] = name
        return next((names[n.lower()] for n in SENT_NAMES if n.lower() in names), None)

    def select(self, folder: str) -> int:
        typ, _ = self.m.select(self._q(folder), readonly=True)
        if typ != "OK":
            raise Invalid(f"Could not open the folder {folder}")
        _, data = self.m.response("UIDVALIDITY")
        return int((data or [b"0"])[0] or 0)

    def _search(self, *criteria: str) -> list[int]:
        typ, data = self.m.uid("SEARCH", None, *criteria)
        if typ != "OK":
            return []
        return [int(x) for x in (data[0] or b"").split()]

    def uids_since(self, since) -> list[int]:
        return self._search("SINCE", since.strftime("%d-%b-%Y"))

    def uids_after(self, uid: int) -> list[int]:
        return [u for u in self._search("UID", f"{uid + 1}:*") if u > uid]

    def headers(self, uids: list[int]) -> dict[int, bytes]:
        if not uids:
            return {}
        typ, data = self.m.uid("FETCH", ",".join(map(str, uids)), HEADERS)
        out = {}
        for part in data or []:
            if isinstance(part, tuple) and (hit := re.search(rb"UID (\d+)", part[0])):
                out[int(hit[1])] = part[1]
        return out

    def fetch(self, uid: int) -> bytes | None:
        typ, data = self.m.uid("FETCH", str(uid), "(BODY.PEEK[])")  # PEEK: never marks it read
        for part in data or []:
            if isinstance(part, tuple):
                return part[1]
        return None

    def append(self, folder: str, raw: bytes) -> None:
        self.m.append(self._q(folder), "(\\Seen)", imaplib.Time2Internaldate(time.time()), raw)

    def close(self) -> None:
        try:
            self.m.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


class _Folders:
    """MAILBOX_TEST_DIR: a mailbox made of folders of <uid>.eml files (dev and tests only)."""

    def __init__(self, mb: Mailbox, password: str):
        self.root = Path(get_settings().mailbox_test_dir) / mb.email_address.lower()
        lock = self.root / "password"  # a test mailbox with a password file checks it
        if lock.exists() and lock.read_text().strip() != password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED Invalid credentials")
        (self.root / "INBOX").mkdir(parents=True, exist_ok=True)
        (self.root / "Sent").mkdir(parents=True, exist_ok=True)
        self.folder = self.root

    def sent_folder(self) -> str | None:
        return "Sent"

    def select(self, folder: str) -> int:
        self.folder = self.root / folder
        v = self.folder / "uidvalidity"
        return int(v.read_text()) if v.exists() else 1

    def _all(self) -> list[int]:
        return sorted(int(p.stem) for p in self.folder.glob("*.eml") if p.stem.isdigit())

    def uids_since(self, since) -> list[int]:
        return self._all()

    def uids_after(self, uid: int) -> list[int]:
        return [u for u in self._all() if u > uid]

    def headers(self, uids: list[int]) -> dict[int, bytes]:
        return {u: (self.folder / f"{u}.eml").read_bytes().split(b"\n\n", 1)[0] for u in uids}

    def fetch(self, uid: int) -> bytes | None:
        return (self.folder / f"{uid}.eml").read_bytes()

    def append(self, folder: str, raw: bytes) -> None:
        self.select(folder)
        (self.folder / f"{(self._all() or [0])[-1] + 1}.eml").write_bytes(raw)

    def close(self) -> None:
        pass


def _test_mode() -> bool:
    s = get_settings()
    return bool(s.mailbox_test_dir) and s.environment != "prod"


class Client:
    """Async face of one connection; each call runs in a thread."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        fn = getattr(self.inner, name)

        async def call(*args):
            return await asyncio.to_thread(fn, *args)

        return call


async def connect(mb: Mailbox, password: str) -> Client:
    """Signs in to the mailbox's IMAP server. Raises Invalid with a plain reason."""
    kind = _Folders if _test_mode() else _Imap
    try:
        smtp._check_host(mb.imap_host, mb.imap_port, IMAP_PORTS)
        return Client(await asyncio.to_thread(kind, mb, password))
    except Invalid:
        raise
    except imaplib.IMAP4.error:
        raise Invalid("The mailbox refused the email or app password") from None
    except (OSError, ssl.SSLError) as e:
        raise Invalid(f"Could not reach the mailbox: {str(e)[:200]}") from None


def box(mb: Mailbox) -> smtp.Box:
    """The mailbox's SMTP side, for sending."""
    return smtp.Box(
        host=mb.smtp_host,
        port=mb.smtp_port,
        security=mb.smtp_security,
        username=mb.username,
        password=SEC.decrypt(mb.password_enc or ""),
        from_name="",
        from_email=mb.email_address,
    )


async def check(mb: Mailbox, password: str) -> None:
    """Signs in to both sides (reading and sending) without changing anything."""
    client = await connect(mb, password)
    await client.close()
    await smtp.check(
        smtp.Box(
            mb.smtp_host, mb.smtp_port, mb.smtp_security, mb.username, password, "",
            mb.email_address,
        )
    )  # fmt: skip


async def usable_mailbox(db: AsyncSession, user_id: uuid.UUID) -> Mailbox | None:
    """The user's connected mailbox to send from. One that needs its password again refuses,
    rather than silently sending from another address."""
    mb = await db.scalar(select(Mailbox).where(Mailbox.user_id == user_id))
    if mb is None or mb.status == "off":
        return None
    if mb.status == "error":
        raise Invalid("Your mailbox needs reconnecting (My account → Connected inbox)")
    return mb


async def save_to_sent(mb: Mailbox, raw: bytes) -> None:
    """Puts the email sent from Core in the user's Sent folder (where the provider doesn't)."""
    if any(mb.smtp_host.lower().endswith(h) for h in SAVES_SENT) and not _test_mode():
        return
    if smtp._outbox() is not None and not _test_mode():
        return  # dev without a test mailbox: nothing was really sent
    try:
        client = await connect(mb, SEC.decrypt(mb.password_enc or ""))
    except Invalid:
        return  # sent fine; only the copy in Sent is missing
    try:
        if folder := await client.sent_folder():
            await client.append(folder, raw)
    except (imaplib.IMAP4.error, OSError):
        pass
    finally:
        await client.close()


# ---------- choosing which emails to keep ----------
def excluded(address: str, exclusions: list[str]) -> bool:
    address = address.lower()
    domain = address.rsplit("@", 1)[-1]
    for rule in exclusions:
        rule = rule.lower().strip()
        if rule == address or rule.lstrip("@") == domain:
            return True
    return False


def _people(head: bytes) -> tuple[str, list[str], str | None]:
    parsed = email.message_from_bytes(head, policy=email.policy.default)
    sender = parseaddr(str(parsed.get("From", "")))[1].lower()
    to = [
        a.lower()
        for _, a in getaddresses(
            [str(v) for v in parsed.get_all("To", []) + parsed.get_all("Cc", [])]
        )
        if a
    ]
    return sender, to, (str(parsed.get("Message-ID") or "").strip() or None)


async def _known(db: AsyncSession, addresses: set[str]) -> dict[str, Lead]:
    if not addresses:
        return {}
    rows = (
        await db.execute(
            select(LeadIdentity.value_normalized, Lead)
            .join(Lead, Lead.id == LeadIdentity.lead_id)
            .where(LeadIdentity.type == "email", LeadIdentity.value_normalized.in_(addresses))
            .order_by(Lead.is_open.desc(), Lead.last_activity_at.desc().nulls_last())
        )
    ).all()
    out: dict[str, Lead] = {}
    for address, lead in rows:
        out.setdefault(address, lead)
    return out


# ---------- one sync run ----------
async def _folder(
    db: AsyncSession,
    mb: Mailbox,
    client: Client,
    name: str,
    sent: bool,
    exclusions: list[str],
) -> int:
    validity = await client.select(name)
    state = (mb.sync_state or {}).get(name)
    first_pass = not state or state.get("v") != validity
    if first_pass:
        state = {"v": validity, "last": 0}
        uids = await client.uids_since(mb.connected_at - timedelta(days=BACKFILL_DAYS))
    else:
        uids = await client.uids_after(state["last"])
    uids = sorted(uids)[:BATCH]
    heads = await client.headers(uids)
    own = mb.email_address.lower()

    picks: list[tuple[int, str, list[str]]] = []
    wanted: set[str] = set()
    for uid in uids:
        head = heads.get(uid)
        if head is None:
            continue
        sender, recipients, _ = _people(head)
        outgoing = sent or sender == own
        others = [a for a in (recipients if outgoing else [sender]) if a != own]
        others = [a for a in others if not excluded(a, exclusions)]
        if others:
            picks.append((uid, "out" if outgoing else "in", others))
            wanted.update(others)
    leads = await _known(db, wanted)

    kept = 0
    for uid, direction, others in picks:
        lead = next((leads[a] for a in others if a in leads), None)
        if lead is None:
            continue
        raw = await client.fetch(uid)
        if not raw:
            continue
        try:
            async with db.begin_nested():  # one odd email never stops the rest
                quiet = first_pass or _older_than_connect(raw, mb)
                if direction == "out":
                    stored = await IB.ingest_sent(db, mb, raw, lead, quiet=quiet)
                else:
                    stored = await IB.ingest(db, mb.tenant_id, raw, mailbox=mb, quiet=quiet)
                kept += stored is not None
        except Exception:  # noqa: BLE001 - logged; the email is skipped, the sync carries on
            log.exception("mailbox %s: could not keep email uid %s in %s", mb.id, uid, name)
    if uids:
        state["last"] = uids[-1]
    mb.sync_state = {**(mb.sync_state or {}), name: state}
    return kept


def _older_than_connect(raw: bytes, mb: Mailbox) -> bool:
    parsed = email.message_from_bytes(raw.split(b"\n\n", 1)[0], policy=email.policy.default)
    when = IB._date_of(parsed)  # the sender's clock: whole seconds, and may be a bit off
    return when is not None and when < mb.connected_at - SLACK


async def sync(db: AsyncSession, mb: Mailbox) -> int:
    """Reads new emails from the mailbox. Returns how many were kept. A refused password or an
    unreachable server puts the mailbox in 'error' (shown to the user, who is told once)."""
    mb.sync_requested = False
    try:
        client = await connect(mb, SEC.decrypt(mb.password_enc or ""))
    except (Invalid, ValueError) as e:
        reason = e.detail if isinstance(e, Invalid) else str(e)
        if mb.status != "error":
            await notify(
                db,
                mb.tenant_id,
                [mb.user_id],
                "inbox",
                f"Your mailbox {mb.email_address} stopped syncing: {reason}",
                None,
            )
        mb.status, mb.last_error = "error", str(reason)[:500]
        mb.last_sync_at = L.now()
        return 0
    settings = await db.get(TenantSettings, mb.tenant_id)
    exclusions = list(settings.mail_exclusions or [])
    kept = 0
    try:
        kept += await _folder(db, mb, client, "INBOX", False, exclusions)
        if sent := await client.sent_folder():
            kept += await _folder(db, mb, client, sent, True, exclusions)
    except (Invalid, imaplib.IMAP4.error, OSError) as e:
        mb.last_error = str(getattr(e, "detail", e))[:500]
    else:
        mb.status, mb.last_error = "active", None
    finally:
        await client.close()
    mb.last_sync_at = L.now()
    return kept


async def run_due(tenant_id: uuid.UUID) -> int:
    """The worker's pass over one company: mailboxes not read for a couple of minutes, or
    where the user pressed 'Sync now'."""
    async with tenant_session(tenant_id) as db:
        ids = (
            await db.scalars(
                select(Mailbox.id).where(
                    or_(
                        Mailbox.sync_requested.is_(True),
                        (Mailbox.status == "active")
                        & or_(
                            Mailbox.last_sync_at.is_(None),
                            Mailbox.last_sync_at < L.now() - EVERY,
                        ),
                    ),
                    Mailbox.status != "off",
                )
            )
        ).all()
    kept = 0
    for mb_id in ids:
        async with tenant_session(tenant_id) as db:
            mb = await db.scalar(
                select(Mailbox).where(Mailbox.id == mb_id).with_for_update(skip_locked=True)
            )
            if mb is not None:
                kept += await sync(db, mb)
    return kept


async def run_all(tenant_ids: list[uuid.UUID]) -> int:
    return sum([await run_due(t) for t in tenant_ids])

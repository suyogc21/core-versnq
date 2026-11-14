"""Copy-in addresses (step 9b-2, Decision log #40): CC or BCC a secret address on any email, or
auto-forward mail to it, and the email lands on the right lead — from any mail app, no
mailbox connected.

Address: <company slug>-<token>@INBOUND_EMAIL_DOMAIN. One for the company, one per user (emails
sent by the company address's users are logged as theirs either way; a user's own address also
owns any lead it creates).

What happens to an email that reaches one:
- Sent by someone in the company (From is a user): it is their email to the people on it. The
  first known lead among To / Cc gets it (ingest_sent, via "copy_in").
- Sent by anyone else: it is an email from that person (ingest, like a reply).
- Nobody known: dropped, unless the company turned on "create a lead" (I3), then a lead is made
  for that person with the chosen source.
- The company's exclusion list applies, the same email twice is kept once (Message-ID), and the
  copy-in address itself is never treated as a person.
A forward done by hand ("Fwd:") carries the original sender only inside the text, so it is
logged only if someone on it is a known lead.
"""

import email
import email.policy
import re
import secrets
import uuid
from dataclasses import dataclass
from email.utils import getaddresses, parseaddr

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.modules import is_enabled
from app.core.tenancy import platform_session, tenant_session
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.models import Lead, LeadSource
from app.modules.engage import inbox as IB
from app.modules.engage.mailsync import _known, excluded
from app.modules.engage.models import CopyInAddress, Message
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User
from app.platform.models import Tenant

LOCAL = re.compile(r"^(?P<slug>[a-z0-9-]+)-(?P<token>[a-z0-9]{12})$")


def address_of(slug: str, token: str) -> str:
    return f"{slug}-{token}@{get_settings().inbound_email_domain}"


async def get_or_create(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None
) -> CopyInAddress:
    row = await db.scalar(
        select(CopyInAddress).where(
            CopyInAddress.user_id.is_(None) if user_id is None else CopyInAddress.user_id == user_id
        )
    )
    if row is None:
        row = CopyInAddress(id=uuid.uuid4(), tenant_id=tenant_id, user_id=user_id, token=_token())
        db.add(row)
        await db.flush()
    return row


def _token() -> str:
    return secrets.token_hex(6)  # 12 characters, 48 bits: not guessable, easy to read


async def reset(db: AsyncSession, row: CopyInAddress) -> None:
    """A new address; the old one stops working at once."""
    row.token = _token()
    await db.flush()


@dataclass
class Result:
    address: str
    stored: bool
    lead_id: uuid.UUID | None = None
    created_lead: bool = False
    conversation_id: uuid.UUID | None = None


def _ours(address: str) -> bool:
    return address.lower().endswith("@" + get_settings().inbound_email_domain.lower())


async def receive(raw: bytes, recipients: list[str]) -> list[Result]:
    """One email delivered to Core (by the provider at go-live; the test endpoint until then).
    `recipients` are the envelope addresses, so a BCC is seen too."""
    results = []
    for rcpt in dict.fromkeys(r.strip().lower() for r in recipients):
        if not _ours(rcpt):
            continue
        hit = LOCAL.match(rcpt.split("@", 1)[0])
        if not hit:
            continue
        async with platform_session() as pdb:
            tenant_id = await pdb.scalar(
                select(Tenant.id).where(Tenant.slug == hit["slug"], Tenant.status == "active")
            )
        if tenant_id is None:
            continue
        async with tenant_session(tenant_id) as tdb:
            if not await is_enabled(tdb, tenant_id, "copy_in"):  # switched off (#44, H1)
                continue
        async with tenant_session(tenant_id) as db:
            row = await db.scalar(select(CopyInAddress).where(CopyInAddress.token == hit["token"]))
            if row is None:
                continue
            results.append(await _handle(db, row, rcpt, raw))
    return results


async def _users(db: AsyncSession) -> dict[str, uuid.UUID]:
    rows = (
        await db.execute(select(func.lower(User.email), User.id).where(User.status == "active"))
    ).all()
    return dict(rows)


async def _new_lead(
    db: AsyncSession, row: CopyInAddress, address: str, name: str, settings: TenantSettings
) -> Lead | None:
    cfg = settings.copy_in or {}
    source = await db.get(LeadSource, uuid.UUID(cfg["source_id"])) if cfg.get("source_id") else None
    if not cfg.get("create_leads") or source is None or not source.is_active:
        return None
    first, _, last = (name or "").strip().partition(" ")
    out = await I.intake(
        db,
        row.tenant_id,
        I.Incoming(
            identities=[L.IdentityInput(type="email", value=address, is_primary=True)],
            source_id=source.id,
            created_via="email",
            fields={"first_name": first or address.split("@")[0], "last_name": last or None},
            owner=row.user_id or I.RULES,
            enforce_required=False,
            via_label="the copy-in address",
        ),
        policy="update",
    )
    return out.lead


async def _handle(db: AsyncSession, row: CopyInAddress, rcpt: str, raw: bytes) -> Result:
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    header_id = (str(parsed.get("Message-ID") or "")).strip()[:300] or None
    if header_id and await db.scalar(
        select(Message.id).where(Message.message_id_header == header_id)
    ):
        return Result(rcpt, False)  # already kept (CC'd twice, or also synced from a mailbox)
    settings = await db.get(TenantSettings, row.tenant_id)
    exclusions = list(settings.mail_exclusions or [])
    users = await _users(db)
    from_name, sender = parseaddr(str(parsed.get("From", "")))
    sender = sender.lower()
    people = [
        (n, a.lower())
        for n, a in getaddresses(
            [str(v) for v in parsed.get_all("To", []) + parsed.get_all("Cc", [])]
        )
        if a
    ]

    def outside(a: str) -> bool:
        return a not in users and not _ours(a) and not excluded(a, exclusions)

    if sender in users:  # someone in the company wrote it: their email to these people
        others = [(n, a) for n, a in people if outside(a)]
        known = await _known(db, {a for _, a in others})
        lead = next((known[a] for _, a in others if a in known), None)
        created = False
        if lead is None and others:
            lead = await _new_lead(db, row, others[0][1], others[0][0], settings)
            created = lead is not None
        if lead is None:
            return Result(rcpt, False)
        msg = await IB.ingest_sent(
            db, raw, lead, user_id=users[sender], from_address=sender, via="copy_in"
        )
    else:
        if not sender or not outside(sender):
            return Result(rcpt, False)
        known = await _known(db, {sender})
        lead = known.get(sender)
        created = False
        if lead is None:
            lead = await _new_lead(db, row, sender, from_name, settings)
            created = lead is not None
            if lead is None:
                return Result(rcpt, False)
        msg = await IB.ingest(db, row.tenant_id, raw, dated=True)
    return Result(
        rcpt,
        msg is not None,
        lead.id,
        created,
        msg.conversation_id if msg else None,
    )

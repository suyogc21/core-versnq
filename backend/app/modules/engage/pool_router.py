"""Sending inboxes: the company's mailbox pool (step O1, Decision log #44). Admins connect any
number of inboxes (one by one or from a CSV), set each one's sender name, signature, owner,
daily limit and gap, and pause, resume or remove them. Admins and managers see their health."""

import csv
import io
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from app.core import secrets as SEC
from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, has_permission, require
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.engage import mailsync as MS
from app.modules.engage import pool as P
from app.modules.engage.mailbox_router import HOST
from app.modules.engage.models import Mailbox
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["sending inboxes"], dependencies=CRM)
Admin = Annotated[CurrentUser, require("mailboxes.manage")]

PRESETS = {
    "gmail": ("imap.gmail.com", 993, "smtp.gmail.com", 587, "starttls"),
    "zoho_in": ("imap.zoho.in", 993, "smtp.zoho.in", 465, "ssl"),
    "zoho": ("imap.zoho.com", 993, "smtp.zoho.com", 465, "ssl"),
}
MAX_IMPORT = 200


async def _viewer(actor: ActiveUser) -> CurrentUser:
    """Admins (who manage inboxes) and managers (who watch the team) see the pool's health."""
    if not (
        has_permission(actor.permissions, "mailboxes.manage")
        or has_permission(actor.permissions, "dashboards.team")
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied")
    return actor


Viewer = Annotated[CurrentUser, Depends(_viewer)]


class Limits(BaseModel):
    from_name: str | None = Field(default=None, max_length=120)
    signature: str | None = Field(default=None, max_length=2000)
    user_id: uuid.UUID | None = None  # whose inbox it is (replies, owner's leads first)
    daily_limit: int = Field(default=30, ge=1, le=2000)
    min_gap_minutes: int = Field(default=6, ge=0, le=1440)


class InboxIn(Limits):
    email_address: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    username: str | None = Field(default=None, max_length=254)
    password: str = Field(min_length=1, max_length=500)
    imap_host: str = Field(pattern=HOST, max_length=255)
    imap_port: int = 993
    smtp_host: str = Field(pattern=HOST, max_length=255)
    smtp_port: int = 587
    smtp_security: Literal["ssl", "starttls"] = "starttls"


class InboxPatch(BaseModel):
    from_name: str | None = Field(default=None, max_length=120)
    signature: str | None = Field(default=None, max_length=2000)
    user_id: uuid.UUID | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=2000)
    min_gap_minutes: int | None = Field(default=None, ge=0, le=1440)
    password: str | None = Field(default=None, max_length=500)  # a new app password


class InboxOut(BaseModel):
    id: uuid.UUID
    email_address: str
    personal: bool
    user_id: uuid.UUID | None
    user_name: str
    from_name: str | None
    signature: str | None
    daily_limit: int
    min_gap_minutes: int
    status: str
    paused_reason: str | None
    last_error: str | None
    last_sync_at: datetime | None
    sent_today: int
    sent_7d: int
    replies_7d: int
    bounces_7d: int


class ImportIn(BaseModel):
    csv: str = Field(max_length=200_000)


class ImportRow(BaseModel):
    row: int
    email_address: str
    ok: bool
    error: str | None = None


async def _tz(db, actor: CurrentUser) -> str:
    return (await db.get(TenantSettings, actor.user.tenant_id)).timezone


async def _out_all(db, actor: CurrentUser, only: uuid.UUID | None = None) -> list[InboxOut]:
    stats = {h["mailbox_id"]: h for h in await P.health(db, await _tz(db, actor))}
    q = select(Mailbox).where(Mailbox.in_pool).order_by(Mailbox.email_address)
    if only:
        q = select(Mailbox).where(Mailbox.id == only)
    rows = (await db.scalars(q)).all()
    names = dict(
        (
            await db.execute(
                select(User.id, User.name).where(User.id.in_([m.user_id for m in rows]))
            )
        ).all()
    )
    out = []
    for mb in rows:
        h = stats.get(mb.id, {})
        out.append(
            InboxOut(
                id=mb.id,
                email_address=mb.email_address,
                personal=mb.personal,
                user_id=mb.user_id,
                user_name=names.get(mb.user_id, ""),
                from_name=mb.from_name,
                signature=mb.signature,
                daily_limit=mb.daily_limit,
                min_gap_minutes=mb.min_gap_minutes,
                status=mb.status,
                paused_reason=mb.paused_reason,
                last_error=mb.last_error,
                last_sync_at=mb.last_sync_at,
                sent_today=h.get("sent_today", 0),
                sent_7d=h.get("sent_7d", 0),
                replies_7d=h.get("replies_7d", 0),
                bounces_7d=h.get("bounces_7d", 0),
            )
        )
    return out


async def _one(db, actor, mb: Mailbox) -> InboxOut:
    return (await _out_all(db, actor, mb.id))[0]


async def _owner(db, user_id: uuid.UUID | None) -> uuid.UUID | None:
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise Invalid("Choose an active user from your team")
    return user.id


async def _connect(db, actor: CurrentUser, body: InboxIn) -> Mailbox:
    address = body.email_address.strip().lower()
    taken = await db.scalar(select(Mailbox).where(func.lower(Mailbox.email_address) == address))
    if taken is not None and taken.status != "off":
        raise Invalid(f"{address} is already connected", code="mailbox_exists")
    mb = taken or Mailbox(id=uuid.uuid4(), tenant_id=actor.user.tenant_id, personal=False)
    mb.email_address = address
    mb.username = (body.username or address).strip()
    mb.imap_host, mb.imap_port = body.imap_host.strip().lower(), body.imap_port
    mb.smtp_host, mb.smtp_port = body.smtp_host.strip().lower(), body.smtp_port
    mb.smtp_security = body.smtp_security
    await MS.check(mb, body.password)  # refuses with a plain reason; nothing is saved then
    mb.user_id = await _owner(db, body.user_id) if not mb.personal else mb.user_id
    mb.from_name, mb.signature = body.from_name, body.signature
    mb.daily_limit, mb.min_gap_minutes = body.daily_limit, body.min_gap_minutes
    mb.password_enc = SEC.encrypt(body.password)
    mb.in_pool = True
    mb.connected_at, mb.sync_state, mb.last_sync_at = L.now(), {}, None
    mb.status, mb.last_error, mb.paused_reason, mb.sync_requested = "active", None, None, True
    if taken is None:
        db.add(mb)
    await db.flush()
    await audit(db, actor, "mailbox.pool_added", "mailbox", mb.id, None, {"email": address})
    return mb


@router.get("/sending-inboxes", response_model=list[InboxOut])
async def list_inboxes(db: CrmDb, actor: Viewer) -> list[InboxOut]:
    return await _out_all(db, actor)


@router.post("/sending-inboxes", response_model=InboxOut, status_code=status.HTTP_201_CREATED)
async def add_inbox(body: InboxIn, db: CrmDb, actor: Admin) -> InboxOut:
    """Signs in to the inbox (IMAP and SMTP) before saving it."""
    return await _one(db, actor, await _connect(db, actor, body))


@router.post("/sending-inboxes/import", response_model=list[ImportRow])
async def import_inboxes(body: ImportIn, db: CrmDb, actor: Admin) -> list[ImportRow]:
    """CSV with a header row: email, password, and optionally provider (gmail / zoho_in / zoho),
    imap_host, imap_port, smtp_host, smtp_port, smtp_security, username, from_name, owner_email,
    daily_limit, min_gap_minutes. Each row is checked on its own; bad rows are reported, not
    saved."""
    reader = csv.DictReader(io.StringIO(body.csv.strip()))
    if not reader.fieldnames or not {"email", "password"} <= {
        (f or "").strip().lower() for f in reader.fieldnames
    }:
        raise Invalid("The CSV needs a header row with at least: email, password")
    rows = list(reader)
    if len(rows) > MAX_IMPORT:
        raise Invalid(f"At most {MAX_IMPORT} inboxes per file")
    users = dict(
        (
            await db.execute(select(func.lower(User.email), User.id).where(User.status == "active"))
        ).all()
    )
    results = []
    for n, raw in enumerate(rows, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        address = row.get("email", "")
        preset = PRESETS.get(row.get("provider", "").lower())
        try:
            imap_host, imap_port, smtp_host, smtp_port, security = preset or (
                row.get("imap_host", ""),
                int(row.get("imap_port") or 993),
                row.get("smtp_host", ""),
                int(row.get("smtp_port") or 587),
                row.get("smtp_security") or "starttls",
            )
            owner = row.get("owner_email", "").lower()
            if owner and owner not in users:
                raise Invalid(f"No active user with the email {owner}")
            data = InboxIn(
                email_address=address,
                password=row.get("password", ""),
                username=row.get("username") or None,
                imap_host=imap_host,
                imap_port=imap_port,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_security=security,
                from_name=row.get("from_name") or None,
                user_id=users.get(owner) if owner else None,
                daily_limit=int(row.get("daily_limit") or 30),
                min_gap_minutes=int(row.get("min_gap_minutes") or 6),
            )
            async with db.begin_nested():
                await _connect(db, actor, data)
            results.append(ImportRow(row=n, email_address=address, ok=True))
        except Invalid as e:
            results.append(ImportRow(row=n, email_address=address, ok=False, error=str(e.detail)))
        except (ValidationError, ValueError) as e:
            first = e.errors()[0] if isinstance(e, ValidationError) else None
            reason = f"{first['loc'][-1]}: {first['msg']}" if first else "a number is not valid"
            results.append(ImportRow(row=n, email_address=address, ok=False, error=reason))
    return results


async def _pool_inbox(db, mb_id: uuid.UUID) -> Mailbox:
    mb = await db.get(Mailbox, mb_id)
    if mb is None or (not mb.in_pool and not mb.personal):
        raise NotFound("Inbox not found")
    return mb


@router.patch("/sending-inboxes/{mb_id}", response_model=InboxOut)
async def update_inbox(mb_id: uuid.UUID, body: InboxPatch, db: CrmDb, actor: Admin) -> InboxOut:
    mb = await _pool_inbox(db, mb_id)
    changes = body.model_dump(exclude_unset=True)
    if "password" in changes:
        password = changes.pop("password")
        if password:
            await MS.check(mb, password)
            mb.password_enc = SEC.encrypt(password)
            mb.status, mb.last_error = "active", None
    if "user_id" in changes:
        if mb.personal:
            raise Invalid("A personal mailbox always belongs to its user")
        mb.user_id = await _owner(db, changes.pop("user_id"))
    for field in ("daily_limit", "min_gap_minutes"):
        if changes.get(field) is None:
            changes.pop(field, None)
    for field, value in changes.items():
        setattr(mb, field, value)
    await db.flush()
    await audit(db, actor, "mailbox.pool_updated", "mailbox", mb.id, None, changes)
    return await _one(db, actor, mb)


@router.post("/sending-inboxes/{mb_id}/add", response_model=InboxOut)
async def add_personal(mb_id: uuid.UUID, db: CrmDb, actor: Admin) -> InboxOut:
    """Adds a user's own connected mailbox to the pool."""
    mb = await db.get(Mailbox, mb_id)
    if mb is None or mb.status == "off":
        raise NotFound("Mailbox not found")
    mb.in_pool = True
    await db.flush()
    await audit(
        db, actor, "mailbox.pool_added", "mailbox", mb.id, None, {"email": mb.email_address}
    )
    return await _one(db, actor, mb)


@router.post("/sending-inboxes/{mb_id}/check", response_model=InboxOut)
async def check_inbox(mb_id: uuid.UUID, db: CrmDb, actor: Admin) -> InboxOut:
    mb = await _pool_inbox(db, mb_id)
    try:
        await MS.check(mb, SEC.decrypt(mb.password_enc or ""))
    except Invalid as e:
        mb.status, mb.last_error = "error", str(e.detail)[:500]
        await db.flush()
        raise
    if mb.status == "error":
        mb.status, mb.last_error = "active", None
    await db.flush()
    return await _one(db, actor, mb)


@router.post("/sending-inboxes/{mb_id}/pause", response_model=InboxOut)
async def pause_inbox(mb_id: uuid.UUID, db: CrmDb, actor: Admin) -> InboxOut:
    mb = await _pool_inbox(db, mb_id)
    if mb.status == "active":
        mb.status, mb.paused_reason = "paused", f"Paused by {actor.user.name}"
    await db.flush()
    await audit(db, actor, "mailbox.paused", "mailbox", mb.id, None, None)
    return await _one(db, actor, mb)


@router.post("/sending-inboxes/{mb_id}/resume", response_model=InboxOut)
async def resume_inbox(mb_id: uuid.UUID, db: CrmDb, actor: Admin) -> InboxOut:
    mb = await _pool_inbox(db, mb_id)
    if mb.status != "paused":
        raise Invalid("Only a paused inbox can be resumed")
    mb.status, mb.paused_reason = "active", None
    await db.flush()
    await audit(db, actor, "mailbox.resumed", "mailbox", mb.id, None, None)
    return await _one(db, actor, mb)


@router.delete("/sending-inboxes/{mb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_inbox(mb_id: uuid.UUID, db: CrmDb, actor: Admin) -> None:
    """Takes it out of the pool. A company inbox is also disconnected (password forgotten); a
    user's own mailbox stays theirs. Emails already sent and received stay on the leads."""
    mb = await _pool_inbox(db, mb_id)
    mb.in_pool = False
    if not mb.personal:
        mb.status, mb.password_enc, mb.sync_requested = "off", None, False
    elif mb.status == "paused":
        mb.status, mb.paused_reason = "active", None
    await db.flush()
    await audit(db, actor, "mailbox.pool_removed", "mailbox", mb.id, {"email": mb.email_address})

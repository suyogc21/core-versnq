"""Connect my inbox (step 9b-3, Decision log #40): a user connects, checks and disconnects their
own mailbox; admins see who is connected, set the exclusion list, disconnect a mailbox and,
once disconnected, may remove the emails it synced (I5)."""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.core import secrets as SEC
from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import Activity
from app.modules.engage import mailsync as MS
from app.modules.engage.models import Conversation, Mailbox, Message
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["mailboxes"], dependencies=CRM)
Replier = Annotated[CurrentUser, require("inbox.reply")]
Admin = Annotated[CurrentUser, require("mailboxes.manage")]
HOST = r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
EXCLUSION = re.compile(r"^(@?[A-Za-z0-9.-]+\.[A-Za-z]{2,}|[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})$")


class MailboxIn(BaseModel):
    email_address: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    username: str | None = Field(default=None, max_length=254)  # usually the email address
    password: str | None = Field(default=None, max_length=500)  # needed to connect
    imap_host: str = Field(pattern=HOST, max_length=255)
    imap_port: int = 993
    smtp_host: str = Field(pattern=HOST, max_length=255)
    smtp_port: int = 587
    smtp_security: Literal["ssl", "starttls"] = "starttls"


class MailboxOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    email_address: str
    username: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    smtp_security: str
    status: str
    last_error: str | None
    connected_at: datetime
    last_sync_at: datetime | None
    synced: int  # emails kept from this mailbox


class Exclusions(BaseModel):
    items: list[str] = Field(max_length=500)


class RemovedOut(BaseModel):
    removed: int


async def _out(db, mb: Mailbox) -> MailboxOut:
    user = await db.get(User, mb.user_id)
    synced = await db.scalar(
        select(func.count()).select_from(Message).where(Message.mailbox_id == mb.id)
    )
    return MailboxOut(
        id=mb.id,
        user_id=mb.user_id,
        user_name=user.name if user else "",
        email_address=mb.email_address,
        username=mb.username,
        imap_host=mb.imap_host,
        imap_port=mb.imap_port,
        smtp_host=mb.smtp_host,
        smtp_port=mb.smtp_port,
        smtp_security=mb.smtp_security,
        status=mb.status,
        last_error=mb.last_error,
        connected_at=mb.connected_at,
        last_sync_at=mb.last_sync_at,
        synced=synced or 0,
    )


async def _mine(db, actor: CurrentUser) -> Mailbox | None:
    return await db.scalar(select(Mailbox).where(Mailbox.user_id == actor.user.id))


# ---------- my mailbox ----------
@router.get("/me/mailbox", response_model=MailboxOut | None)
async def my_mailbox(db: CrmDb, actor: Replier) -> MailboxOut | None:
    mb = await _mine(db, actor)
    return await _out(db, mb) if mb and mb.status != "off" else None


@router.put("/me/mailbox", response_model=MailboxOut)
async def connect_mailbox(body: MailboxIn, db: CrmDb, actor: Replier) -> MailboxOut:
    """Connects (or updates) the user's mailbox after signing in to both sides."""
    mb = await _mine(db, actor)
    address = body.email_address.strip().lower()
    password = body.password or (
        SEC.decrypt(mb.password_enc) if mb and mb.password_enc and mb.status != "off" else None
    )
    if not password:
        raise Invalid("Enter the mailbox's app password")
    if mb is None:
        mb = Mailbox(id=uuid.uuid4(), tenant_id=actor.user.tenant_id, user_id=actor.user.id)
        db.add(mb)
    fresh = mb.status in (None, "off") or (mb.email_address or "").lower() != address
    mb.email_address = address
    mb.username = (body.username or address).strip()
    mb.imap_host, mb.imap_port = body.imap_host.strip().lower(), body.imap_port
    mb.smtp_host, mb.smtp_port = body.smtp_host.strip().lower(), body.smtp_port
    mb.smtp_security = body.smtp_security
    await MS.check(mb, password)  # refuses with a plain reason; nothing is saved then
    mb.password_enc = SEC.encrypt(password)
    if fresh:  # a new connection pulls in the last 30 days again
        mb.connected_at, mb.sync_state, mb.last_sync_at = L.now(), {}, None
    mb.status, mb.last_error, mb.sync_requested = "active", None, True
    await db.flush()
    await audit(db, actor, "mailbox.connected", "mailbox", mb.id, None, {"email": address})
    return await _out(db, mb)


@router.post("/me/mailbox/sync", response_model=MailboxOut)
async def sync_now(db: CrmDb, actor: Replier) -> MailboxOut:
    mb = await _mine(db, actor)
    if mb is None or mb.status == "off":
        raise NotFound("Connect your mailbox first")
    mb.sync_requested = True
    await db.flush()
    return await _out(db, mb)


async def _disconnect(db, actor: CurrentUser, mb: Mailbox) -> None:
    mb.status, mb.password_enc, mb.sync_requested, mb.last_error = "off", None, False, None
    await db.flush()
    await audit(db, actor, "mailbox.disconnected", "mailbox", mb.id, {"email": mb.email_address})


@router.delete("/me/mailbox", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_mine(db: CrmDb, actor: Replier) -> None:
    """Stops syncing and forgets the password. Emails already synced stay on the leads (I5)."""
    mb = await _mine(db, actor)
    if mb is not None and mb.status != "off":
        await _disconnect(db, actor, mb)


# ---------- admins ----------
@router.get("/mailboxes", response_model=list[MailboxOut])
async def list_mailboxes(db: CrmDb, actor: Admin) -> list[MailboxOut]:
    rows = (await db.scalars(select(Mailbox).order_by(Mailbox.email_address))).all()
    return [await _out(db, mb) for mb in rows]


@router.post("/mailboxes/{mb_id}/disconnect", response_model=MailboxOut)
async def disconnect_one(mb_id: uuid.UUID, db: CrmDb, actor: Admin) -> MailboxOut:
    mb = await db.get(Mailbox, mb_id)
    if mb is None:
        raise NotFound("Mailbox not found")
    if mb.status != "off":
        await _disconnect(db, actor, mb)
    return await _out(db, mb)


@router.delete("/mailboxes/{mb_id}/emails", response_model=RemovedOut)
async def remove_synced(mb_id: uuid.UUID, db: CrmDb, actor: Admin) -> RemovedOut:
    """Removes the emails a disconnected mailbox synced in from mail apps, with their timeline
    entries. Emails written in Core stay: they are the company's own record."""
    mb = await db.get(Mailbox, mb_id)
    if mb is None:
        raise NotFound("Mailbox not found")
    if mb.status != "off":
        raise Invalid("Disconnect the mailbox first")
    synced_out = (
        select(Activity.data["message_id"].astext)
        .where(Activity.type_key == "email_sent", Activity.data["via"].astext == "mailbox")
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Message.id, Message.conversation_id).where(
                Message.mailbox_id == mb.id,
                (Message.direction == "in") | func.cast(Message.id, sa.String).in_(synced_out),
            )
        )
    ).all()
    ids = [r.id for r in rows]
    if ids:
        await db.execute(
            delete(Activity).where(Activity.data["message_id"].astext.in_([str(i) for i in ids]))
        )
        await db.execute(delete(Message).where(Message.id.in_(ids)))
        for conv_id in {r.conversation_id for r in rows if r.conversation_id}:
            left = await db.scalar(
                select(func.count()).select_from(Message).where(Message.conversation_id == conv_id)
            )
            if not left:
                await db.execute(delete(Conversation).where(Conversation.id == conv_id))
    await audit(db, actor, "mailbox.emails_removed", "mailbox", mb.id, None, {"removed": len(ids)})
    return RemovedOut(removed=len(ids))


@router.get("/mailboxes/exclusions", response_model=Exclusions)
async def get_exclusions(db: CrmDb, actor: Admin) -> Exclusions:
    settings = await db.get(TenantSettings, actor.user.tenant_id)
    return Exclusions(items=list(settings.mail_exclusions or []))


@router.put("/mailboxes/exclusions", response_model=Exclusions)
async def set_exclusions(body: Exclusions, db: CrmDb, actor: Admin) -> Exclusions:
    """Addresses (name@firm.com) and domains (firm.com or @firm.com) never synced from anyone's
    mailbox: lawyers, family, the company's own banks."""
    items = []
    for raw in body.items:
        item = raw.strip().lower()
        if not item:
            continue
        if not EXCLUSION.fullmatch(item):
            raise Invalid(f"{raw} is not an email address or a domain")
        if item not in items:
            items.append(item)
    settings = await db.get(TenantSettings, actor.user.tenant_id)
    before = list(settings.mail_exclusions or [])
    settings.mail_exclusions = items
    await db.flush()
    await audit(
        db, actor, "mailbox.exclusions", "settings", None, {"items": before}, {"items": items}
    )
    return Exclusions(items=items)

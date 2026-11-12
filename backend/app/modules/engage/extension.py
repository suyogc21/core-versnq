"""The Versnq WhatsApp extension (step 10a, Decision log #41): each rep's own WhatsApp, read in
WhatsApp Web, logged to Core. The extension never sends anything by itself.

Connecting: the rep makes a one-time code in My account (10 minutes) and types it into the
extension with the workspace address; the extension exchanges it for its own token
(`vq_ext_…`), which works only on /api/v1/extension/* and can be revoked by the rep or an admin.

The extension asks "is this number a lead?" (the number is not stored), shows the lead, can
create one through the normal intake, add a note or a follow-up date, and sends the messages of
an open chat with a known lead. Each message carries WhatsApp's own id, so nothing is logged
twice; a received message stops sequences that stop on replies; a sent one counts as contact.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.client_ip import client_ip
from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import (
    CurrentUser,
    TenantDb,
    WorkspaceDep,
    current_user,
    has_permission,
    require,
)
from app.modules.crm import access as A
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.identities import normalize
from app.modules.crm.models import (
    Customer,
    Deal,
    Lead,
    LeadIdentity,
    LeadSource,
    LeadStage,
)
from app.modules.crm.routing import mark_contacted
from app.modules.engage import inbox as IB
from app.modules.engage.models import (
    CannedReply,
    Conversation,
    ExtensionToken,
    Message,
    WhatsAppChatLink,
)
from app.modules.users.models import User

PREFIX = "vq_ext_"
CODE_TTL = timedelta(minutes=10)
REPLY_STOPS_WITHIN = timedelta(days=2)  # older messages pulled in by "Sync this chat" don't


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


# ---------- the extension's token (used by auth.deps) ----------
async def token_user(db: AsyncSession, token: str, version: str | None) -> User | None:
    row = await db.scalar(
        select(ExtensionToken).where(
            ExtensionToken.token_hash == _hash(token), ExtensionToken.revoked_at.is_(None)
        )
    )
    if row is None:
        return None
    user = await db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if row.last_used_at is None or now() - row.last_used_at > timedelta(seconds=60):
        row.last_used_at = now()
    if version:
        row.version = version[:20]
    return user


# ---------- shapes ----------
class CodeOut(BaseModel):
    code: str
    expires_at: datetime


class ExtensionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    device: str | None
    version: str | None
    connected: bool  # the code was exchanged
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ConnectIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)
    device: str | None = Field(default=None, max_length=120)


class ConnectOut(BaseModel):
    token: str
    user_name: str
    workspace: str


class LeadCard(BaseModel):
    id: uuid.UUID
    name: str
    org_name: str | None
    stage: str
    owner_name: str | None
    is_yours: bool
    next_follow_up_at: datetime | None
    open_deals: int
    open_deal_value: list[dict]  # [{currency, amount_minor}] — empty if amounts are hidden
    balance_due: list[dict]  # [{currency, due_minor}] — empty without invoices.read
    url: str


class LookupOut(BaseModel):
    lead: LeadCard | None
    phone: str | None  # the number, cleaned (E.164)


class NewLeadIn(BaseModel):
    phone: str | None = Field(default=None, max_length=40)
    chat_key: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class LinkIn(BaseModel):
    chat_key: str = Field(min_length=1, max_length=200)
    lead_id: uuid.UUID


class SearchHit(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None


class WaMessageIn(BaseModel):
    id: str = Field(min_length=1, max_length=200)  # WhatsApp's own id
    from_me: bool
    text: str = Field(default="", max_length=20000)
    kind: Literal["text", "photo", "video", "document", "voice", "sticker", "other"] = "text"
    at: datetime | None = None


class LogIn(BaseModel):
    lead_id: uuid.UUID
    messages: list[WaMessageIn] = Field(max_length=200)


class LogOut(BaseModel):
    logged: int
    skipped: int  # already in Core


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class FollowUpIn(BaseModel):
    at: datetime | None


class ReplyOut(BaseModel):
    id: uuid.UUID
    name: str
    body: str


# ---------- My account: codes and connected browsers ----------
account = APIRouter(prefix="/api/v1", tags=["extension"], dependencies=CRM)
Replier = Annotated[CurrentUser, require("inbox.reply")]
Admin = Annotated[CurrentUser, require("mailboxes.manage")]


async def _out(db, rows) -> list[ExtensionOut]:
    names = dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_({r.user_id for r in rows}))))
        .all()
    ) if rows else {}  # fmt: skip
    return [
        ExtensionOut(
            id=r.id,
            user_id=r.user_id,
            user_name=names.get(r.user_id, ""),
            device=r.device,
            version=r.version,
            connected=r.token_hash is not None,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked_at=r.revoked_at,
        )
        for r in rows
    ]


@account.post("/me/extension/code", response_model=CodeOut, status_code=status.HTTP_201_CREATED)
async def make_code(db: CrmDb, actor: Replier) -> CodeOut:
    """A one-time code to connect the WhatsApp extension in one browser (10 minutes)."""
    code = f"{secrets.randbelow(10**8):08d}"
    row = ExtensionToken(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        user_id=actor.user.id,
        code_hash=_hash(code),
        code_expires_at=now() + CODE_TTL,
    )
    db.add(row)
    await db.flush()
    return CodeOut(code=f"{code[:4]}-{code[4:]}", expires_at=row.code_expires_at)


@account.get("/me/extensions", response_model=list[ExtensionOut])
async def my_extensions(db: CrmDb, actor: Replier) -> list[ExtensionOut]:
    rows = (
        await db.scalars(
            select(ExtensionToken)
            .where(ExtensionToken.user_id == actor.user.id, ExtensionToken.token_hash.is_not(None))
            .order_by(ExtensionToken.created_at.desc())
        )
    ).all()
    return await _out(db, rows)


@account.get("/extensions", response_model=list[ExtensionOut])
async def all_extensions(db: CrmDb, actor: Admin) -> list[ExtensionOut]:
    rows = (
        await db.scalars(
            select(ExtensionToken)
            .where(ExtensionToken.token_hash.is_not(None))
            .order_by(ExtensionToken.last_used_at.desc().nulls_last())
        )
    ).all()
    return await _out(db, rows)


@account.post("/extensions/{ext_id}/revoke", response_model=list[ExtensionOut])
async def revoke(ext_id: uuid.UUID, db: CrmDb, actor: Replier) -> list[ExtensionOut]:
    """The rep revokes their own; an admin (mailboxes.manage) anyone's."""
    row = await db.get(ExtensionToken, ext_id)
    admin = has_permission(actor.permissions, "mailboxes.manage")
    if row is None or (row.user_id != actor.user.id and not admin):
        raise NotFound("Not found")
    if row.revoked_at is None:
        row.revoked_at = now()
        await db.flush()
        await audit(db, actor, "extension.revoked", "extension", row.id)
    return await (all_extensions(db, actor) if admin else my_extensions(db, actor))


# ---------- the extension itself ----------
router = APIRouter(prefix="/api/v1/extension", tags=["extension"], dependencies=CRM)


@router.post("/connect", response_model=ConnectOut)
async def connect(
    request: Request, body: ConnectIn, db: TenantDb, workspace: WorkspaceDep
) -> ConnectOut:
    """Exchanges a one-time code (made in My account) for the extension's own token. Tries are
    limited per address and per company, so codes can't be guessed."""
    await ratelimit.enforce(f"rl:extcode:ip:{client_ip(request)}", 10, 600)
    await ratelimit.enforce(f"rl:extcode:ws:{workspace.id}", 30, 600)
    code = "".join(ch for ch in body.code if ch.isdigit())
    row = await db.scalar(
        select(ExtensionToken)
        .where(ExtensionToken.code_hash == _hash(code), ExtensionToken.revoked_at.is_(None))
        .with_for_update()
    )
    if row is None or row.code_expires_at is None or row.code_expires_at < now():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That code is wrong or has expired")
    user = await db.get(User, row.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That code is wrong or has expired")
    token = PREFIX + secrets.token_urlsafe(32)
    row.code_hash, row.code_expires_at = None, None
    row.token_hash, row.device, row.last_used_at = _hash(token), body.device, now()
    await db.flush()
    return ConnectOut(token=token, user_name=user.name, workspace=workspace.slug)


Ext = Annotated[CurrentUser, Depends(current_user)]


async def _replier(actor: Ext) -> CurrentUser:
    if not has_permission(actor.permissions, "inbox.reply"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role can't use the inbox")
    return actor


Rep = Annotated[CurrentUser, Depends(_replier)]


async def _card(db: AsyncSession, actor: CurrentUser, lead: Lead, base: str) -> LeadCard:
    stage = await db.get(LeadStage, lead.stage_id)
    owner = await db.get(User, lead.owner_user_id) if lead.owner_user_id else None
    deals = (
        await db.execute(
            select(Deal.currency, func.count(), func.sum(Deal.amount_minor))
            .where(Deal.lead_id == lead.id, Deal.status == "open")
            .group_by(Deal.currency)
        )
    ).all()
    amounts_hidden = (await A.rules(db, actor, "deal")).access.get("amount") == "hidden"
    balance: list[dict] = []
    if has_permission(actor.permissions, "invoices.read"):
        from app.modules.money.service import balances

        customer = await db.scalar(select(Customer).where(Customer.lead_id == lead.id))
        if customer:
            balance = [
                {"currency": b["currency"], "due_minor": b["due_minor"]}
                for b in await balances(db, customer.id, date.today())
                if b.get("due_minor")
            ]
    return LeadCard(
        id=lead.id,
        name=lead.display_name,
        org_name=lead.org_name,
        stage=stage.name if stage else "",
        owner_name=owner.name if owner else None,
        is_yours=lead.owner_user_id == actor.user.id,
        next_follow_up_at=lead.next_follow_up_at,
        open_deals=sum(n for _, n, _ in deals),
        open_deal_value=[]
        if amounts_hidden
        else [{"currency": c, "amount_minor": int(a or 0)} for c, _, a in deals],
        balance_due=balance,
        url=f"{base}/leads/{lead.id}",
    )


async def _phone(db: AsyncSession, actor: CurrentUser, raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if not digits:
        return None
    if not digits.startswith("+"):
        digits = "+" + digits  # WhatsApp numbers always carry the country code
    try:
        return normalize("phone", digits, await L.tenant_country(db, actor.user.tenant_id))
    except Invalid:
        return None


async def _visible_lead(db: AsyncSession, actor: CurrentUser, lead_id: uuid.UUID) -> Lead:
    return await L.get_visible(db, actor, lead_id)


def _base(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


@router.get("/lookup", response_model=LookupOut)
async def lookup(
    request: Request,
    db: TenantDb,
    actor: Rep,
    phone: str | None = None,
    chat_key: str | None = None,
) -> LookupOut:
    """Is the open chat a lead this rep may see? The number is not stored."""
    number = await _phone(db, actor, phone)
    lead = None
    if number:
        lead = await db.scalar(
            select(Lead)
            .join(LeadIdentity, LeadIdentity.lead_id == Lead.id)
            .where(
                LeadIdentity.type == "phone",
                LeadIdentity.value_normalized == number,
                await L.visibility_filter(db, actor),
            )
            .order_by(Lead.is_open.desc(), Lead.last_activity_at.desc().nulls_last())
            .limit(1)
        )
    if lead is None and chat_key:
        link = await db.scalar(
            select(WhatsAppChatLink).where(
                WhatsAppChatLink.user_id == actor.user.id,
                WhatsAppChatLink.chat_key == chat_key[:200],
            )
        )
        if link:
            lead = await db.scalar(
                select(Lead).where(Lead.id == link.lead_id, await L.visibility_filter(db, actor))
            )
    return LookupOut(
        lead=await _card(db, actor, lead, _base(request)) if lead else None, phone=number
    )


@router.get("/search", response_model=list[SearchHit])
async def search(db: TenantDb, actor: Rep, q: str) -> list[SearchHit]:
    """For "Link to lead" when WhatsApp Web shows no number."""
    q = q.strip()
    if len(q) < 2:
        return []
    rows = (
        await db.scalars(
            select(Lead)
            .where(Lead.display_name.ilike(f"%{q}%"), await L.visibility_filter(db, actor))
            .order_by(Lead.last_activity_at.desc().nulls_last())
            .limit(8)
        )
    ).all()
    return [SearchHit(id=r.id, name=r.display_name, phone=r.primary_phone) for r in rows]


@router.post("/link", response_model=LookupOut)
async def link(request: Request, body: LinkIn, db: TenantDb, actor: Rep) -> LookupOut:
    lead = await _visible_lead(db, actor, body.lead_id)
    row = await db.scalar(
        select(WhatsAppChatLink).where(
            WhatsAppChatLink.user_id == actor.user.id, WhatsAppChatLink.chat_key == body.chat_key
        )
    )
    if row is None:
        row = WhatsAppChatLink(
            id=uuid.uuid4(),
            tenant_id=actor.user.tenant_id,
            user_id=actor.user.id,
            chat_key=body.chat_key,
            lead_id=lead.id,
        )
        db.add(row)
    row.lead_id = lead.id
    await db.flush()
    return LookupOut(lead=await _card(db, actor, lead, _base(request)), phone=None)


async def _whatsapp_source(db: AsyncSession) -> LeadSource:
    sources = (
        await db.scalars(
            select(LeadSource).where(LeadSource.is_active.is_(True)).order_by(LeadSource.position)
        )
    ).all()
    named = next((s for s in sources if s.name.strip().lower() == "whatsapp"), None)
    if named or sources:
        return named or sources[0]
    raise Invalid("Add a lead source first (Settings → Records and fields)")


@router.post("/leads", response_model=LookupOut, status_code=status.HTTP_201_CREATED)
async def create_lead(request: Request, body: NewLeadIn, db: TenantDb, actor: Rep) -> LookupOut:
    """Create a lead from the open chat (source "WhatsApp" if the company has one). Same
    duplicate rules as quick-add: an existing lead with this number is refused."""
    if not has_permission(actor.permissions, "leads.create"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role can't add leads")
    number = await _phone(db, actor, body.phone)
    if number is None and not body.chat_key:
        raise Invalid("No phone number in this chat; type the lead's number in Core instead")
    first, _, last = body.name.strip().partition(" ")
    out = await I.intake(
        db,
        actor.user.tenant_id,
        I.Incoming(
            identities=[L.IdentityInput(type="phone", value=number, is_primary=True)]
            if number
            else [],
            source_id=(await _whatsapp_source(db)).id,
            created_via="whatsapp",
            fields={"first_name": first, "last_name": last or None},
            owner=actor.user.id,
            enforce_required=False,
            via_label="WhatsApp",
        ),
        policy="refuse",
        actor=actor,
    )
    lead = out.lead
    if number is None and body.chat_key:
        db.add(
            WhatsAppChatLink(
                id=uuid.uuid4(),
                tenant_id=actor.user.tenant_id,
                user_id=actor.user.id,
                chat_key=body.chat_key,
                lead_id=lead.id,
            )
        )
        await db.flush()
    return LookupOut(lead=await _card(db, actor, lead, _base(request)), phone=number)


async def _conversation(db: AsyncSession, lead: Lead, actor: CurrentUser) -> Conversation:
    conv = await db.scalar(
        select(Conversation)
        .where(Conversation.lead_id == lead.id, Conversation.channel == "whatsapp")
        .order_by(Conversation.created_at)
        .limit(1)
    )
    if conv is None:
        conv = Conversation(
            id=uuid.uuid4(),
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            channel="whatsapp",
            subject="WhatsApp",
            status="open",
            created_by_user_id=actor.user.id,
        )
        db.add(conv)
        await db.flush()
    return conv


LABELS = {
    "photo": "[photo]",
    "video": "[video]",
    "document": "[document]",
    "voice": "[voice note]",
    "sticker": "[sticker]",
    "other": "[message]",
}


@router.post("/messages", response_model=LogOut)
async def log_messages(body: LogIn, db: TenantDb, actor: Rep) -> LogOut:
    """Messages from the open chat with this lead, in order. Already-logged ones are skipped."""
    lead = await _visible_lead(db, actor, body.lead_id)
    ids = [m.id for m in body.messages]
    seen = set(
        (await db.scalars(select(Message.external_id).where(Message.external_id.in_(ids)))).all()
    )
    conv = await _conversation(db, lead, actor)
    logged = 0
    contacted = replied = None
    for m in body.messages:
        if m.id in seen:
            continue
        seen.add(m.id)
        when = m.at or now()
        text = m.text.strip() or LABELS.get(m.kind, "[message]")
        if m.kind != "text" and m.text.strip():
            text = f"{LABELS[m.kind]} {m.text.strip()}"
        msg = Message(
            id=uuid.uuid4(),
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            channel="whatsapp",
            direction="out" if m.from_me else "in",
            conversation_id=conv.id,
            to_address=(lead.primary_phone or "") if m.from_me else "",
            from_address=None if m.from_me else lead.primary_phone,
            subject=None,
            body=text[:20000],
            token=secrets.token_urlsafe(24),
            status="sent" if m.from_me else "received",
            sent_at=when,
            sent_by_user_id=actor.user.id if m.from_me else None,
            external_id=m.id,
        )
        db.add(msg)
        await db.flush()
        if conv.last_message_at is None or when >= conv.last_message_at:
            IB._touch(conv, msg)
        await L.log(
            db,
            lead,
            "whatsapp_sent" if m.from_me else "whatsapp_received",
            ("WhatsApp sent: " if m.from_me else "WhatsApp received: ") + text[:120],
            actor if m.from_me else None,
            {"message_id": str(msg.id), "conversation_id": str(conv.id), "via": "extension"},
            body=text[:2000],
            occurred_at=when,
        )
        logged += 1
        if m.from_me:
            contacted = max(filter(None, [contacted, when]))
        elif now() - when < REPLY_STOPS_WITHIN:
            replied = msg
    if contacted:
        lead.last_activity_at = now()
        lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, contacted]))
        lead.first_response_at = lead.first_response_at or contacted
        await mark_contacted(db, lead)
    if replied:
        lead.last_activity_at = now()
        await IB._replied(db, lead, replied)
    return LogOut(logged=logged, skipped=len(body.messages) - logged)


@router.post("/leads/{lead_id}/note", response_model=LookupOut)
async def add_note(
    request: Request, lead_id: uuid.UUID, body: NoteIn, db: TenantDb, actor: Rep
) -> LookupOut:
    lead = await _visible_lead(db, actor, lead_id)
    await L.log(db, lead, "note", body.body[:200], actor, {"via": "extension"}, body=body.body)
    lead.last_activity_at = now()
    return LookupOut(lead=await _card(db, actor, lead, _base(request)), phone=None)


@router.put("/leads/{lead_id}/follow-up", response_model=LookupOut)
async def follow_up(
    request: Request, lead_id: uuid.UUID, body: FollowUpIn, db: TenantDb, actor: Rep
) -> LookupOut:
    lead = await _visible_lead(db, actor, lead_id)
    if not has_permission(actor.permissions, "leads.edit"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role can't edit leads")
    if body.at is not None and body.at < now() - timedelta(minutes=5):
        raise Invalid("Pick a time in the future")
    await L.set_follow_up(db, lead, body.at, actor)
    return LookupOut(lead=await _card(db, actor, lead, _base(request)), phone=None)


@router.get("/replies", response_model=list[ReplyOut])
async def replies(db: TenantDb, actor: Rep) -> list[ReplyOut]:
    """Saved replies (the rep's own and shared ones), to put into the WhatsApp message box."""
    rows = (
        await db.scalars(
            select(CannedReply)
            .where((CannedReply.is_shared.is_(True)) | (CannedReply.user_id == actor.user.id))
            .order_by(CannedReply.name)
        )
    ).all()
    return [ReplyOut(id=r.id, name=r.name, body=r.body) for r in rows]


class MeOut(BaseModel):
    name: str
    email: str


@router.get("/me", response_model=MeOut)
async def me(actor: Rep) -> MeOut:
    """Who is signed in, for the panel's header."""
    return MeOut(name=actor.user.name, email=actor.user.email)

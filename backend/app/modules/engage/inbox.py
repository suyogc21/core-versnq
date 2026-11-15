"""Conversations: the full email trail with each lead, and the shared inbox (step 9b-1,
Decision log #40).

Every email in or out with a lead belongs to a conversation. An incoming email is matched by
its thread headers first (it answers an email we sent or saw), then by the sender's address;
an unknown sender is not stored (I3). Incoming emails keep their CC list and attachments, go
on the lead's timeline, stop the person's sequences, and tell the conversation's people.

Who sees a conversation: anyone who can see its lead, plus colleagues added to it (they get the
conversation and the lead's basics only, I2). A private conversation is seen only by the person
who marked it, colleagues added to it and admins.
"""

import email
import email.policy
import re
import secrets
import uuid
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid, NotFound
from app.core.events import emit
from app.core.storage import check_type, clean_name, save
from app.modules.auth.deps import CurrentUser, has_permission
from app.modules.crm import leads as L
from app.modules.crm.customers import storage_used
from app.modules.crm.models import Lead, LeadIdentity, StoredFile, Suppression
from app.modules.crm.notify import notify
from app.modules.crm.routing import mark_contacted
from app.modules.engage import engine as E
from app.modules.engage import render as R
from app.modules.engage import sender as S
from app.modules.engage.models import (
    Conversation,
    ConversationMember,
    Enrolment,
    Mailbox,
    Message,
    MessageAttachment,
    Sequence,
)
from app.modules.settings.models import TenantSettings
from app.platform.models import Tenant

ADMINS = ("owner", "admin")
MAX_ATTACHMENT = 15 * 1024 * 1024
SUBJECT_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw)\s*:\s*)+", re.IGNORECASE)


def base_subject(subject: str | None) -> str:
    return SUBJECT_PREFIX.sub("", subject or "").strip().lower()


# ---------- who sees what ----------
async def visible(db: AsyncSession, actor: CurrentUser):
    """SQL condition: conversations this person may see."""
    member = select(ConversationMember.conversation_id).where(
        ConversationMember.user_id == actor.user.id
    )
    is_member = Conversation.id.in_(member)
    has_lead = Conversation.lead_id.isnot(None)  # cold campaign threads: the outreach inbox
    if actor.role.key in ADMINS:
        return has_lead
    lead_ok = Conversation.lead_id.in_(select(Lead.id).where(await L.visibility_filter(db, actor)))
    not_private = or_(
        Conversation.is_private.is_(False), Conversation.private_user_id == actor.user.id
    )
    return and_(has_lead, or_(is_member, and_(lead_ok, not_private)))


async def get_visible(db: AsyncSession, actor: CurrentUser, conv_id: uuid.UUID) -> Conversation:
    conv = await db.scalar(
        select(Conversation).where(Conversation.id == conv_id, await visible(db, actor))
    )
    if conv is None:
        raise NotFound("Conversation not found")
    return conv


async def is_member(db: AsyncSession, conv: Conversation, user_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(
            select(ConversationMember.id).where(
                ConversationMember.conversation_id == conv.id, ConversationMember.user_id == user_id
            )
        )
    )


async def assignee_of(db: AsyncSession, conv: Conversation) -> uuid.UUID | None:
    if conv.assignee_user_id:
        return conv.assignee_user_id
    if conv.lead_id is None:  # a cold campaign thread with no owner (step O2)
        return None
    lead = await db.get(Lead, conv.lead_id)
    return lead.owner_user_id if lead else None


async def can_manage(db: AsyncSession, actor: CurrentUser, conv: Conversation) -> bool:
    """Take over, hand on, add colleagues: the person it belongs to, managers, admins."""
    return (
        actor.role.key in ADMINS
        or has_permission(actor.permissions, "inbox.take_over")
        or (await assignee_of(db, conv) == actor.user.id)
    )


# ---------- conversations ----------
async def open_conversation(
    db: AsyncSession,
    lead: Lead,
    subject: str | None,
    *,
    by: uuid.UUID | None = None,
    enrolment_id: uuid.UUID | None = None,
) -> Conversation:
    conv = Conversation(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        channel="email",
        subject=(subject or "")[:300] or None,
        status="open",
        enrolment_id=enrolment_id,
        created_by_user_id=by,
    )
    db.add(conv)
    await db.flush()
    return conv


async def for_enrolment(
    db: AsyncSession, enrolment: Enrolment, lead: Lead, subject: str
) -> Conversation:
    """A sequence's emails to one person share one conversation, so a reply lands there."""
    conv = await db.scalar(
        select(Conversation).where(Conversation.enrolment_id == enrolment.id).limit(1)
    )
    return conv or await open_conversation(db, lead, subject, enrolment_id=enrolment.id)


def _touch(conv: Conversation, msg: Message) -> None:
    conv.last_message_at = msg.sent_at or msg.created_at or L.now()
    conv.last_direction = msg.direction
    if msg.direction == "in":
        conv.last_inbound_at = conv.last_message_at
        conv.status = "open"


# ---------- incoming ----------
def _text_of(parsed) -> str:
    part = parsed.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"<(br|/p|/div)\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _ids(value: str | None) -> list[str]:
    return re.findall(r"<[^>]+>", value or "")


async def _lead_for_address(db: AsyncSession, address: str) -> Lead | None:
    return await db.scalar(
        select(Lead)
        .join(LeadIdentity, LeadIdentity.lead_id == Lead.id)
        .where(LeadIdentity.type == "email", LeadIdentity.value_normalized == address.lower())
        .order_by(Lead.is_open.desc(), Lead.last_activity_at.desc().nulls_last())
        .limit(1)
    )


def _date_of(parsed) -> datetime | None:
    try:
        when = parsedate_to_datetime(parsed.get("Date", ""))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


async def _answered(db: AsyncSession, parsed) -> Message | None:
    """The email we already have that this one answers (by its thread headers)."""
    thread_ids = _ids(parsed.get("In-Reply-To")) + _ids(parsed.get("References"))
    if not thread_ids:
        return None
    return await db.scalar(
        select(Message)
        .where(Message.message_id_header.in_(thread_ids))
        .order_by(Message.created_at.desc())
        .limit(1)
    )


async def _conversation_for(
    db: AsyncSession,
    lead: Lead,
    answered: Message | None,
    subject: str,
    by: uuid.UUID | None = None,
) -> Conversation:
    conv = (
        await db.get(Conversation, answered.conversation_id)
        if answered and answered.conversation_id and answered.lead_id == lead.id
        else None
    )
    if conv is None:
        conv = await db.scalar(
            select(Conversation)
            .where(Conversation.lead_id == lead.id, Conversation.channel == "email")
            .order_by(Conversation.last_message_at.desc().nulls_last())
            .limit(1)
        )
        if conv is not None and base_subject(conv.subject) != base_subject(subject):
            conv = None
    return conv or await open_conversation(db, lead, subject, by=by)


async def _seen(db: AsyncSession, header_id: str | None) -> bool:
    return bool(
        header_id
        and await db.scalar(select(Message.id).where(Message.message_id_header == header_id))
    )


async def message_event(
    db: AsyncSession, msg: Message, *, channel: str, official: bool | None = None
) -> None:
    """message.received / message.sent (Decision log #43). Ids and small details only.
    channel: email / whatsapp (company number) / whatsapp_extension (a rep's own WhatsApp)."""
    await emit(
        db,
        msg.tenant_id,
        "message.received" if msg.direction == "in" else "message.sent",
        {
            "conversation_id": str(msg.conversation_id),
            "lead_id": str(msg.lead_id) if msg.lead_id else None,
            "message_id": str(msg.id),
            "channel": channel,
            "direction": msg.direction,
            "official": official,
            # step O2 (the contract with ACE): null when not a campaign email / not the pool
            "contact_id": str(msg.contact_id) if msg.contact_id else None,
            "campaign_id": str(msg.campaign_id) if msg.campaign_id else None,
            "mailbox_id": str(msg.mailbox_id) if msg.mailbox_id else None,
            "auto_submitted": bool(msg.auto_submitted),
        },
    )


async def ingest(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    raw: bytes,
    *,
    mailbox: Mailbox | None = None,
    quiet: bool = False,
    dated: bool = False,
) -> Message | None:
    """One incoming email (the test inbox, a user's connected mailbox (step 9b-3); the provider
    and the copy-in address later). Returns the stored message, or None if it matches no lead.
    `quiet` (older emails pulled in when a mailbox is first connected): kept on the trail, but
    nobody is notified and no sequence is stopped."""
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    header_id = (parsed.get("Message-ID") or "").strip()[:300] or None
    if await _seen(db, header_id):
        return None  # already have it (the same email seen twice)
    from_addr = parseaddr(parsed.get("From", ""))[1].lower()
    in_reply_to = (parsed.get("In-Reply-To") or "").strip()[:300] or None
    refs = parsed.get("References") or ""

    answered = await _answered(db, parsed)
    lead = await db.get(Lead, answered.lead_id) if answered and answered.lead_id else None
    if lead is None and answered is not None and answered.contact_id:
        from app.modules.outreach import replies  # outreach builds on this module

        return await replies.ingest(db, tenant_id, parsed, answered, mailbox=mailbox, quiet=quiet)
    if lead is None and from_addr:
        lead = await _lead_for_address(db, from_addr)
    if lead is None and from_addr:
        from app.modules.outreach import replies

        return await replies.ingest(db, tenant_id, parsed, None, mailbox=mailbox, quiet=quiet)
    if lead is None:
        return None  # unknown sender: not stored (Decision log #40, I3)

    subject = (parsed.get("Subject") or "").strip()[:300]
    conv = await _conversation_for(db, lead, answered, subject)
    when = (_date_of(parsed) if mailbox or dated else None) or L.now()

    to_addrs = [a for _, a in getaddresses(parsed.get_all("To", []))]
    cc = [a for _, a in getaddresses(parsed.get_all("Cc", [])) if a]
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        lead_id=lead.id,
        channel="email",
        direction="in",
        conversation_id=conv.id,
        enrolment_id=answered.enrolment_id if answered else None,
        to_address=(to_addrs[0] if to_addrs else "")[:320],
        from_address=from_addr[:320],
        subject=subject or None,
        body=_text_of(parsed)[:100000],
        token=secrets.token_urlsafe(24),
        status="received",
        message_id_header=header_id,
        in_reply_to=in_reply_to,
        references=refs[:5000] or None,
        cc=cc[:50],
        sent_at=when,
        mailbox_id=mailbox.id if mailbox else None,
    )
    db.add(msg)
    await db.flush()
    await _attachments(db, tenant_id, lead, msg, parsed)
    if not quiet or conv.last_message_at is None or when > conv.last_message_at:
        _touch(conv, msg)

    if answered and answered.direction == "out" and answered.replied_at is None:
        answered.replied_at = L.now()
    await L.log(
        db,
        lead,
        "email_received",
        f"Email received: {subject or '(no subject)'}",
        None,
        {"message_id": str(msg.id), "conversation_id": str(conv.id), "from": from_addr},
        body=msg.body[:2000],
        occurred_at=when,
    )
    if quiet:
        return msg
    await message_event(db, msg, channel="email")
    from app.modules.replies import service as RS  # replies build on this module

    await RS.supersede(db, conv.id, msg)  # a waiting draft is now out of date (step O3)
    lead.last_activity_at = L.now()
    await _replied(db, lead, msg)
    people = [await assignee_of(db, conv)] + list(
        (
            await db.scalars(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conv.id
                )
            )
        ).all()
    )
    await notify(
        db,
        tenant_id,
        [p for p in people if p],
        "inbox",
        f"New email from {lead.display_name}: {subject or '(no subject)'}",
        lead.id,
    )
    return msg


async def ingest_sent(
    db: AsyncSession,
    raw: bytes,
    lead: Lead,
    *,
    user_id: uuid.UUID | None,
    from_address: str,
    mailbox_id: uuid.UUID | None = None,
    via: str = "mailbox",
    quiet: bool = False,
) -> Message | None:
    """An email a user sent to a lead from their own mail app: found in their Sent folder
    (step 9b-3, via "mailbox") or copied to a copy-in address (step 9b-2, via "copy_in").
    Emails sent from Core are already kept and are skipped by their Message-ID."""
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    header_id = (parsed.get("Message-ID") or "").strip()[:300] or None
    if await _seen(db, header_id):
        return None
    subject = (parsed.get("Subject") or "").strip()[:300]
    answered = await _answered(db, parsed)
    conv = await _conversation_for(db, lead, answered, subject, by=user_id)
    when = _date_of(parsed) or L.now()
    to = (lead.primary_email or "").lower()
    others = [
        a.lower()
        for _, a in getaddresses(parsed.get_all("To", []) + parsed.get_all("Cc", []))
        if a and a.lower() != to
    ]
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        channel="email",
        direction="out",
        conversation_id=conv.id,
        to_address=to[:320],
        from_address=from_address[:320],
        subject=subject or None,
        body=_text_of(parsed)[:100000],
        token=secrets.token_urlsafe(24),
        status="sent",
        message_id_header=header_id,
        in_reply_to=(parsed.get("In-Reply-To") or "").strip()[:300] or None,
        references=(parsed.get("References") or "")[:5000] or None,
        cc=others[:50],
        sent_at=when,
        sent_by_user_id=user_id,
        mailbox_id=mailbox_id,
    )
    db.add(msg)
    await db.flush()
    await _attachments(db, lead.tenant_id, lead, msg, parsed)
    if conv.last_message_at is None or when >= conv.last_message_at:
        _touch(conv, msg)
    await L.log(
        db,
        lead,
        "email_sent",
        f"Email sent from {from_address}: {subject or '(no subject)'}",
        None,
        {"message_id": str(msg.id), "conversation_id": str(conv.id), "via": via},
        body=msg.body[:2000],
        occurred_at=when,
    )
    if not quiet:
        await message_event(db, msg, channel="email")
        lead.last_activity_at = L.now()
        lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, when]))
        lead.first_response_at = lead.first_response_at or when
        await mark_contacted(db, lead)
    return msg


async def _attachments(
    db: AsyncSession, tenant_id: uuid.UUID, lead: Lead, msg: Message, parsed
) -> None:
    """Keep each attachment as a file on the lead (same checks and quota as uploads). One that
    is too big, of a refused type or over quota is noted on the message instead."""
    settings = await db.get(TenantSettings, tenant_id)
    skipped = []
    for part in parsed.iter_attachments():
        name = clean_name(part.get_filename() or "attachment")
        data = part.get_content()
        if isinstance(data, str):
            data = data.encode()
        try:
            if len(data) > MAX_ATTACHMENT:
                raise Invalid("too big")
            content_type, ext = check_type(data, name, allow_office=True)
            if await storage_used(db) + len(data) > settings.storage_quota_bytes:
                raise Invalid("storage full")
        except Invalid as e:
            skipped.append(f"{name} ({e.detail})")
            continue
        saved = save(tenant_id, data, ext, content_type)
        stored = StoredFile(
            tenant_id=tenant_id,
            lead_id=lead.id,
            path=saved.path,
            original_name=name,
            content_type=content_type,
            size_bytes=saved.size_bytes,
            sha256=saved.sha256,
        )
        db.add(stored)
        await db.flush()
        db.add(MessageAttachment(tenant_id=tenant_id, message_id=msg.id, file_id=stored.id))
    if skipped:
        msg.error = ("Attachments not kept: " + ", ".join(skipped))[:300]
    await db.flush()


async def _replied(db: AsyncSession, lead: Lead, msg: Message) -> None:
    """A reply stops the person's sequences that stop on replies, and tells automations."""
    for e in (
        await db.scalars(
            select(Enrolment).where(Enrolment.lead_id == lead.id, Enrolment.status == "active")
        )
    ).all():
        seq = await db.get(Sequence, e.sequence_id)
        if "reply" in (seq.stop_on or []):
            await E.end(db, e, "stopped", "reply")
        await emit(
            db,
            lead.tenant_id,
            "sequence.replied",
            {"lead_id": str(lead.id), "sequence_id": str(seq.id), "message_id": str(msg.id)},
        )


# ---------- outgoing (one-to-one) ----------
async def send(
    db: AsyncSession,
    actor: CurrentUser,
    lead: Lead,
    conv: Conversation | None,
    *,
    subject: str,
    body: str,
    cc: list[str],
) -> Message:
    """A person writes to a lead from the CRM (a new email or a reply)."""
    to = lead.primary_email
    if not to:
        raise Invalid(f"{lead.display_name} has no email address", code="no_email")
    reasons = set(
        (
            await db.scalars(
                select(Suppression.reason).where(
                    Suppression.channel == "email", Suppression.value_normalized == to.lower()
                )
            )
        ).all()
    )
    if reasons & {"bounce", "complaint"}:
        raise Invalid(
            "This address bounced or complained before; it can't be emailed",
            code="email_suppressed",
        )
    opted_out = lead.email_consent == "opted_out" or "opt_out" in reasons
    last_in = None
    if conv is not None:
        last_in = await db.scalar(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.direction == "in")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    if opted_out and last_in is None:
        raise Invalid(
            f"{lead.display_name} opted out of email; "
            "you can only answer them when they write to you",
            code="email_opted_out",
        )
    cc = [c.strip() for c in cc if c.strip()][:20]
    for c in cc:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c):
            raise Invalid(f"{c} is not an email address", code="invalid_cc")
    tenant = await db.get(Tenant, lead.tenant_id)
    from app.modules.engage import mailsync as MS  # it uses this module

    own = await MS.usable_mailbox(db, actor.user.id)
    if own is not None:  # the user's own connected mailbox (step 9b-3)
        from_name, from_email = actor.user.name, own.email_address
    else:
        from_name, from_email = await S.sender_address(db, tenant.name)
        from_name = (
            f"{actor.user.name} · {from_name}" if actor.user.status != "integration" else from_name
        )
    token = secrets.token_urlsafe(24)
    built = R.build_email(
        body,
        track_base=f"{E.workspace_url(tenant.slug)}/api/v1/t",
        token=token,
        unsubscribe_url=None,
    )
    header_id = S.new_message_id(from_email)
    previous = (
        await db.scalar(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        if conv
        else None
    )
    if conv is None:
        conv = await open_conversation(db, lead, subject, by=actor.user.id)
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        channel="email",
        direction="out",
        conversation_id=conv.id,
        to_address=to,
        from_address=from_email,
        subject=subject[:300],
        body=body,
        links=built.links,
        token=token,
        status="queued",
        message_id_header=header_id,
        in_reply_to=previous.message_id_header if previous else None,
        references=((previous.references or "") + " " + (previous.message_id_header or "")).strip()[
            :5000
        ]
        if previous
        else None,
        cc=cc,
        sent_by_user_id=actor.user.id,
        mailbox_id=own.id if own else None,
    )
    db.add(msg)
    await db.flush()
    try:
        sent = await S.send(
            db,
            to=to,
            subject=msg.subject,
            text=built.text,
            html=built.html,
            from_name=from_name,
            from_email=from_email,
            unsubscribe_url=None,
            message_id=header_id,
            cc=cc,
            in_reply_to=msg.in_reply_to,
            references=previous.references if previous else None,
            box=MS.box(own) if own else None,
        )
    except Invalid as err:
        msg.status, msg.error = "failed", str(err.detail)[:300]
        await db.flush()
        raise
    if own is not None:
        await MS.save_to_sent(own, sent.as_bytes())
    msg.status, msg.sent_at = "sent", L.now()
    _touch(conv, msg)
    await L.log(
        db,
        lead,
        "email_sent",
        f"Email sent: {msg.subject}",
        actor,
        {"message_id": str(msg.id), "conversation_id": str(conv.id)},
        body=body[:2000],
    )
    await message_event(db, msg, channel="email")
    now = L.now()
    lead.last_activity_at = now
    lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, now]))
    lead.first_response_at = lead.first_response_at or now
    await mark_contacted(db, lead)
    return msg

"""Answering a campaign reply from the outreach inbox (step O2): from the inbox the contact
was emailed from, in the same thread. An address that bounced or complained can't be emailed;
one that unsubscribed can still be answered, because they wrote to us."""

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import Suppression
from app.modules.engage import inbox as IB
from app.modules.engage import mailsync as MS
from app.modules.engage import render as R
from app.modules.engage import sender as S
from app.modules.engage.models import Conversation, Mailbox, Message
from app.modules.outreach.models import Contact


async def reply(db: AsyncSession, actor: CurrentUser, conv: Conversation, body: str) -> Message:
    contact = await db.get(Contact, conv.contact_id)
    to = contact.email
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
    previous = await db.scalar(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    sent_from = await db.scalar(
        select(Message.mailbox_id)
        .where(
            Message.conversation_id == conv.id,
            Message.direction == "out",
            Message.mailbox_id.isnot(None),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    mb = await db.get(Mailbox, sent_from) if sent_from else None
    if mb is None or mb.status in ("off", "error"):
        raise Invalid(
            "The inbox this person was emailed from is not connected any more",
            code="mailbox_needs_reconnect",
        )
    subject = (previous.subject if previous else conv.subject) or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    text = f"{body}\n\n{mb.signature}" if mb.signature else body
    token = secrets.token_urlsafe(24)
    built = R.build_email(text, track_base=None, token=token, unsubscribe_url=None)
    header_id = S.new_message_id(mb.email_address)
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=conv.tenant_id,
        lead_id=conv.lead_id,
        contact_id=contact.id,
        campaign_id=conv.campaign_id,
        channel="email",
        direction="out",
        conversation_id=conv.id,
        to_address=to,
        from_address=mb.email_address,
        subject=subject[:300],
        body=text,
        links=[],
        token=token,
        status="queued",
        message_id_header=header_id,
        in_reply_to=previous.message_id_header if previous else None,
        references=(
            ((previous.references or "") + " " + (previous.message_id_header or "")).strip()[:5000]
            if previous
            else None
        ),
        sent_by_user_id=actor.user.id,
        mailbox_id=mb.id,
    )
    db.add(msg)
    await db.flush()
    owner_name = mb.from_name or actor.user.name
    try:
        sent = await S.send(
            db,
            to=to,
            subject=msg.subject,
            text=built.text,
            html=built.html,
            from_name=owner_name,
            from_email=mb.email_address,
            unsubscribe_url=None,
            message_id=header_id,
            in_reply_to=msg.in_reply_to,
            references=previous.references if previous else None,
            box=MS.box(mb),
        )
    except Invalid as err:
        msg.status, msg.error = "failed", str(err.detail)[:300]
        await db.flush()
        raise
    await MS.save_to_sent(mb, sent.as_bytes())
    mb.last_sent_at = L.now()
    msg.status, msg.sent_at = "sent", L.now()
    IB._touch(conv, msg)
    await IB.message_event(db, msg, channel="email")
    return msg

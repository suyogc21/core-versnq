"""Replies to campaign emails (step O2). An email that answers a campaign email, or comes from
a contact in a campaign, is kept on that contact's conversation in the outreach inbox. A real
reply stops that person in that campaign (not their colleagues); an auto-reply (out of office)
is kept and marked, and the campaign carries on."""

import re
import secrets
import uuid
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm import leads as L
from app.modules.crm.notify import notify
from app.modules.engage import inbox as IB
from app.modules.engage.models import Conversation, Mailbox, Message
from app.modules.outreach.models import Campaign, CampaignContact, Contact

AUTO_SUBJECT = re.compile(
    r"^\s*(automatic reply|auto[- ]?reply|out of (the )?office|autoresponse|away from)",
    re.IGNORECASE,
)


def is_auto_reply(parsed: EmailMessage) -> bool:
    auto = (parsed.get("Auto-Submitted") or "").strip().lower()
    if auto and auto != "no":
        return True
    if parsed.get("X-Autoreply") or parsed.get("X-Autorespond"):
        return True
    if (parsed.get("Precedence") or "").strip().lower() in ("auto_reply", "bulk", "junk"):
        return True
    return bool(AUTO_SUBJECT.match(parsed.get("Subject") or ""))


async def known_contacts(db: AsyncSession, addresses: set[str]) -> set[str]:
    """Addresses (lower-case) of contacts who are in a campaign and not yet leads."""
    if not addresses:
        return set()
    rows = await db.scalars(
        select(Contact.email)
        .join(CampaignContact, CampaignContact.contact_id == Contact.id)
        .where(Contact.lead_id.is_(None))
        .where(func.lower(Contact.email).in_(addresses))
    )
    return {e.lower() for e in rows.all()}


async def _contact_for(
    db: AsyncSession, answered: Message | None, from_addr: str
) -> tuple[Contact, uuid.UUID] | None:
    if answered is not None and answered.contact_id and answered.campaign_id:
        contact = await db.get(Contact, answered.contact_id)
        if contact is not None:
            return contact, answered.campaign_id
    if not from_addr:
        return None
    row = (
        await db.execute(
            select(Contact, CampaignContact.campaign_id)
            .join(CampaignContact, CampaignContact.contact_id == Contact.id)
            .where(func.lower(Contact.email) == from_addr, Contact.lead_id.is_(None))
            .order_by(CampaignContact.last_sent_at.desc().nulls_last())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def ingest(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    parsed: EmailMessage,
    answered: Message | None,
    *,
    mailbox: Mailbox | None,
    quiet: bool,
) -> Message | None:
    from_addr = parseaddr(parsed.get("From", ""))[1].lower()
    found = await _contact_for(db, answered, from_addr)
    if found is None:
        return None  # unknown sender: not stored (Decision log #40, I3)
    contact, campaign_id = found
    campaign = await db.get(Campaign, campaign_id)
    subject = (parsed.get("Subject") or "").strip()[:300]
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.contact_id == contact.id, Conversation.campaign_id == campaign_id
        )
    )
    if conv is None:
        conv = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            lead_id=contact.lead_id,
            contact_id=contact.id,
            campaign_id=campaign_id,
            channel="email",
            subject=subject or None,
            status="open",
            assignee_user_id=campaign.owner_user_id if campaign else None,
        )
        db.add(conv)
        await db.flush()
    auto = is_auto_reply(parsed)
    to_addrs = [a for _, a in getaddresses(parsed.get_all("To", []))]
    when = (IB._date_of(parsed) if mailbox else None) or L.now()
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        lead_id=contact.lead_id,
        contact_id=contact.id,
        campaign_id=campaign_id,
        campaign_step_id=answered.campaign_step_id if answered else None,
        channel="email",
        direction="in",
        conversation_id=conv.id,
        to_address=(to_addrs[0] if to_addrs else "")[:320],
        from_address=from_addr[:320],
        subject=subject or None,
        body=IB._text_of(parsed)[:100000],
        token=secrets.token_urlsafe(24),
        status="received",
        message_id_header=(parsed.get("Message-ID") or "").strip()[:300] or None,
        in_reply_to=(parsed.get("In-Reply-To") or "").strip()[:300] or None,
        references=(parsed.get("References") or "")[:5000] or None,
        cc=[a for _, a in getaddresses(parsed.get_all("Cc", [])) if a][:50],
        sent_at=when,
        mailbox_id=mailbox.id if mailbox else None,
        auto_submitted=auto,
    )
    db.add(msg)
    await db.flush()
    if not auto:
        IB._touch(conv, msg)
    if quiet:
        return msg
    await IB.message_event(db, msg, channel="email")
    if auto:
        return msg
    from app.modules.replies import service as RS

    await RS.supersede(db, conv.id, msg)  # a waiting draft is now out of date (step O3)
    if answered is not None and answered.direction == "out" and answered.replied_at is None:
        answered.replied_at = L.now()
    cc = await db.scalar(
        select(CampaignContact).where(
            CampaignContact.campaign_id == campaign_id, CampaignContact.contact_id == contact.id
        )
    )
    if cc is not None and cc.status in ("pending", "active"):
        cc.status, cc.ended_reason, cc.next_run_at = "replied", "replied", None
    people = [conv.assignee_user_id or (campaign.owner_user_id if campaign else None)]
    await notify(
        db,
        tenant_id,
        [p for p in people if p],
        "inbox",
        f"Reply from {contact.name} ({campaign.name if campaign else 'campaign'}): "
        f"{subject or '(no subject)'}",
        None,
    )
    return msg

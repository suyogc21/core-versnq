"""The campaign runner (step O2). Every 30 seconds the worker sends each company's due campaign
emails: inside the campaign's sending hours, under its daily cap and each inbox's own limit and
gap (O1), always from the same inbox for the same contact, the contact's version (A/B…) of each
step. Before every email the promise is checked again: a contact who is now a lead, or whose
address is blocked, is never emailed. Nothing to send from yet → the contact waits, never skips.
"""

import secrets
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.core.tenancy import tenant_session
from app.modules.crm import consent as C
from app.modules.engage import engine as E
from app.modules.engage import pool as P
from app.modules.engage import render as R
from app.modules.engage import sender as S
from app.modules.engage.models import Conversation, Mailbox, Message
from app.modules.outreach import service as O
from app.modules.outreach.models import Campaign, CampaignContact, CampaignStep, Contact
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User
from app.platform.models import Tenant

DUE_BATCH = 100
WAIT = timedelta(minutes=5)  # every inbox busy: look again soon
RETRY_AFTER = timedelta(minutes=15)
MAX_SEND_TRIES = 3


def now() -> datetime:
    return datetime.now(UTC)


def tz_of(campaign: Campaign, settings: TenantSettings) -> str:
    return (campaign.schedule or {}).get("timezone") or settings.timezone


def window(campaign: Campaign) -> dict:
    return {**O.DEFAULT_SCHEDULE, **(campaign.schedule or {})}


async def sent_today(db: AsyncSession, campaign: Campaign, tz: str) -> int:
    start = datetime.combine(datetime.now(ZoneInfo(tz)).date(), time.min, ZoneInfo(tz))
    return (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.campaign_id == campaign.id,
                Message.direction == "out",
                Message.sent_at >= start,
            )
        )
        or 0
    )


async def _conversation(
    db: AsyncSession, campaign: Campaign, contact: Contact, subject: str
) -> Conversation:
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.contact_id == contact.id, Conversation.campaign_id == campaign.id
        )
    )
    if conv is None:
        conv = Conversation(
            id=uuid.uuid4(),
            tenant_id=campaign.tenant_id,
            lead_id=contact.lead_id,
            contact_id=contact.id,
            campaign_id=campaign.id,
            channel="email",
            subject=subject[:300] or None,
            status="open",
            assignee_user_id=campaign.owner_user_id,
        )
        db.add(conv)
        await db.flush()
    return conv


async def _inbox(
    db: AsyncSession, cc: CampaignContact, campaign: Campaign, tz: str
) -> Mailbox | None:
    """The contact's own inbox when it can send now; a new one only when theirs was paused,
    broken or taken out of the campaign (or on the first email)."""
    allowed = [uuid.UUID(i) for i in campaign.mailbox_ids or []]
    if cc.mailbox_id:
        mb = await db.get(Mailbox, cc.mailbox_id)
        usable = (
            mb is not None
            and mb.status == "active"
            and mb.in_pool
            and (not allowed or mb.id in allowed)
        )
        if usable:
            return mb if await P.ready_now(db, mb, tz) else None
    mb = await P.choose(db, tz, owner_user_id=campaign.owner_user_id, only=allowed or None)
    if mb is not None:
        cc.mailbox_id = mb.id
    return mb


async def _send(
    db: AsyncSession,
    tenant: Tenant,
    campaign: Campaign,
    step: CampaignStep,
    cc: CampaignContact,
    contact: Contact,
    mb: Mailbox,
) -> str:
    """'sent', 'retry' or 'failed'."""
    owner = await db.get(User, mb.user_id) if mb.user_id else None
    from_name = mb.from_name or (owner.name if owner else tenant.name)
    variant = step.variants[cc.variant % len(step.variants)]
    values = O.values_for(contact, from_name, tenant.name)
    previous = await db.scalar(
        select(Message)
        .where(
            Message.campaign_id == campaign.id,
            Message.contact_id == contact.id,
            Message.direction == "out",
            Message.status != "failed",
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    subject = R.fill(variant.get("subject") or "", values).strip()
    threaded = not subject and previous is not None
    if threaded:
        subject = previous.subject or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
    body = R.fill(variant["body"], values)
    if mb.signature:
        body = f"{body}\n\n{mb.signature}"
    token = secrets.token_urlsafe(24)
    base = E.workspace_url(tenant.slug)
    unsubscribe = f"{base}/api/v1/u/{token}"
    built = R.build_email(
        body,
        track_base=f"{base}/api/v1/t",
        token=token,
        unsubscribe_url=unsubscribe,
        track_opens=campaign.track_opens,
        track_links=campaign.track_clicks,
    )
    header_id = S.new_message_id(mb.email_address)
    conv = await _conversation(db, campaign, contact, subject)
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=campaign.tenant_id,
        lead_id=None,
        contact_id=contact.id,
        campaign_id=campaign.id,
        campaign_step_id=step.id,
        variant=cc.variant % len(step.variants),
        channel="email",
        direction="out",
        to_address=contact.email,
        from_address=mb.email_address,
        subject=subject[:300],
        body=body,
        links=built.links if campaign.track_clicks else [],
        token=token,
        status="queued",
        message_id_header=header_id,
        in_reply_to=previous.message_id_header if threaded else None,
        references=(
            ((previous.references or "") + " " + (previous.message_id_header or "")).strip()[:5000]
            if threaded
            else None
        ),
        conversation_id=conv.id,
        mailbox_id=mb.id,
    )
    db.add(msg)
    await db.flush()
    from app.modules.engage import inbox as IB
    from app.modules.engage import mailsync as MS

    mb.last_sent_at = now()  # the gap counts from the attempt
    try:
        sent = await S.send(
            db,
            to=contact.email,
            subject=msg.subject,
            text=built.text,
            html=built.html,
            from_name=from_name,
            from_email=mb.email_address,
            unsubscribe_url=unsubscribe,
            message_id=header_id,
            in_reply_to=msg.in_reply_to,
            references=previous.references if threaded else None,
            box=MS.box(mb),
        )
        msg.provider_id = sent["Message-ID"]
    except Invalid as err:
        msg.status, msg.error = "failed", str(err.detail)[:300]
        tries = await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.contact_id == contact.id,
                Message.campaign_step_id == step.id,
                Message.status == "failed",
            )
        )
        return "failed" if tries >= MAX_SEND_TRIES else "retry"
    msg.status, msg.sent_at = "sent", now()
    IB._touch(conv, msg)
    await IB.message_event(db, msg, channel="email")
    return "sent"


async def advance(
    db: AsyncSession, cc: CampaignContact, campaign: Campaign, tenant: Tenant, settings
) -> None:
    contact = await db.get(Contact, cc.contact_id)
    step = await db.scalar(
        select(CampaignStep).where(
            CampaignStep.campaign_id == campaign.id, CampaignStep.position == cc.position
        )
    )
    if contact is None or step is None or not step.variants:
        cc.status, cc.ended_reason, cc.next_run_at = "finished", "all_steps_sent", None
        return
    # The promise, checked at every send: already ours, or blocked → never a cold email.
    if lead := await O.lead_for_email(db, contact.email):
        await O.became_lead(db, contact, lead)
        return
    if contact.status != "active" or await C.is_suppressed(db, "email", [contact.email.lower()]):
        await O.stop(db, contact.id, "stopped", "suppressed")
        return
    tz = tz_of(campaign, settings)
    opens = E.next_open(now(), window(campaign), tz)
    if opens > now():
        cc.next_run_at = opens
        return
    if await sent_today(db, campaign, tz) >= campaign.daily_cap:
        tomorrow = datetime.combine(
            datetime.now(ZoneInfo(tz)).date() + timedelta(days=1), time.min, ZoneInfo(tz)
        )
        cc.next_run_at = E.next_open(tomorrow.astimezone(UTC), window(campaign), tz)
        return
    mb = await _inbox(db, cc, campaign, tz)
    if mb is None:
        cc.next_run_at = now() + WAIT
        return
    outcome = await _send(db, tenant, campaign, step, cc, contact, mb)
    if outcome == "retry":
        cc.next_run_at = now() + RETRY_AFTER
        return
    if outcome == "sent":
        cc.last_sent_at = now()
    nxt = await db.scalar(
        select(CampaignStep).where(
            CampaignStep.campaign_id == campaign.id, CampaignStep.position == cc.position + 1
        )
    )
    cc.position += 1
    if nxt is None:
        cc.status, cc.ended_reason, cc.next_run_at = "finished", "all_steps_sent", None
    else:
        cc.next_run_at = now() + timedelta(days=nxt.wait_days)


async def _finish_done(db: AsyncSession) -> None:
    """A running campaign with nobody left to email is finished."""
    running = (await db.scalars(select(Campaign).where(Campaign.status == "running"))).all()
    for c in running:
        left = await db.scalar(
            select(CampaignContact.id)
            .where(CampaignContact.campaign_id == c.id, CampaignContact.status.in_(O.OPEN))
            .limit(1)
        )
        if left is None:
            c.status = "finished"


async def run_due(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as db:
        due = (
            await db.execute(
                select(CampaignContact, Campaign)
                .join(Campaign, Campaign.id == CampaignContact.campaign_id)
                .where(
                    Campaign.status == "running",
                    CampaignContact.status == "active",
                    CampaignContact.next_run_at <= now(),
                )
                .order_by(CampaignContact.next_run_at)
                .limit(DUE_BATCH)
                .with_for_update(of=CampaignContact, skip_locked=True)
            )
        ).all()
        if due:
            tenant = await db.get(Tenant, tenant_id)
            settings = await db.get(TenantSettings, tenant_id)
            for cc, campaign in due:
                if cc.status != "active":  # stopped by an earlier contact's check this run
                    continue
                async with db.begin_nested():
                    await advance(db, cc, campaign, tenant, settings)
        await _finish_done(db)
        return len(due)


async def run_all(tenant_ids: list[uuid.UUID]) -> int:
    return sum([await run_due(t) for t in tenant_ids])

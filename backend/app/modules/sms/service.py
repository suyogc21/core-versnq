"""SMS (finishing plan, batch 5d): send to a lead, receive replies and STOP, delivery status.

Rules (CLAUDE.md rule 8, honour opt-outs):
- Nobody who opted out of SMS, or whose number is on the SMS suppression list, gets an SMS.
- "STOP" (and the usual stop words) from a number opts that lead out and suppresses the number,
  even when no lead has it.
- With MSG91 (India) only DLT-registered templates can be sent (TRAI); free text is refused.
- Every SMS in or out is an activity on the lead's timeline and an event (sms.sent / sms.received).
"""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Invalid
from app.core.events import emit
from app.modules.crm import consent as C
from app.modules.crm import leads as L
from app.modules.crm.identities import normalize
from app.modules.crm.models import Lead, LeadIdentity
from app.modules.engage import render as R
from app.modules.sms import providers as P
from app.modules.sms.models import SmsAccount, SmsMessage, SmsTemplate
from app.platform.models import Tenant

# Carriers' and Twilio's usual opt-out words (Twilio's default list, as remembered: UNVERIFIED).
STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "optout"}
MAX_BODY = 1600


def now() -> datetime:
    return datetime.now(UTC)


def is_stop(text: str) -> bool:
    return re.sub(r"[^a-z]", "", (text or "").casefold()) in STOP_WORDS


async def account(db: AsyncSession) -> SmsAccount | None:
    return await db.scalar(select(SmsAccount).limit(1))


async def phones_of(db: AsyncSession, lead: Lead) -> list[str]:
    rows = await db.scalars(
        select(LeadIdentity.value_normalized).where(
            LeadIdentity.lead_id == lead.id, LeadIdentity.type.in_(["phone", "whatsapp"])
        )
    )
    return list(dict.fromkeys(rows.all()))


async def opted_out(db: AsyncSession, lead: Lead) -> bool:
    return lead.sms_consent == "opted_out" or await C.is_suppressed(
        db, "sms", await phones_of(db, lead)
    )


def status_url(acct: SmsAccount, slug: str) -> str:
    return f"https://{slug}.{get_settings().base_domain}/api/v1/sms/{acct.webhook_token}/status"


async def send(
    db: AsyncSession,
    lead: Lead,
    *,
    body: str | None = None,
    template: SmsTemplate | None = None,
    actor_user_id: uuid.UUID | None = None,
    enrolment_id: uuid.UUID | None = None,
    step_id: uuid.UUID | None = None,
) -> SmsMessage:
    """Send one SMS to the lead's number. Refusals raise Invalid with a code."""
    acct = await account(db)
    if acct is None:
        raise Invalid("Connect an SMS provider in Settings → SMS first", code="sms_not_set_up")
    if await opted_out(db, lead):
        raise Invalid(f"{lead.display_name} opted out of SMS", code="sms_opted_out")
    phones = await phones_of(db, lead)
    to = lead.primary_phone or (phones[0] if phones else None)
    if not to:
        raise Invalid(f"{lead.display_name} has no phone number", code="sms_no_number")
    if acct.provider == "msg91" and (template is None or not template.dlt_template_id):
        raise Invalid(
            "In India every SMS must use a DLT-registered template: choose one",
            code="sms_template_required",
        )
    tenant = await db.get(Tenant, lead.tenant_id)
    from app.modules.engage.engine import values_for  # it builds on crm, not the other way

    values = await values_for(db, lead, tenant.name if tenant else "")
    text = R.fill(template.body if template else (body or ""), values).strip()
    if not text:
        raise Invalid("Write the SMS", code="sms_empty")
    if len(text) > MAX_BODY:
        raise Invalid(f"An SMS can be at most {MAX_BODY} characters", code="sms_too_long")
    variables = [
        str(values.get(name) or (fallback or "").strip())
        for name, fallback in R.VAR.findall(template.body if template else "")
    ]
    msg = SmsMessage(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        direction="out",
        number=to,
        body=text,
        status="queued",
        provider=acct.provider,
        template_id=template.id if template else None,
        enrolment_id=enrolment_id,
        step_id=step_id,
        sent_by_user_id=actor_user_id,
    )
    db.add(msg)
    result = await P.client(acct).send(
        to=to,
        body=text,
        variables=variables,
        provider_template_id=template.provider_template_id if template else None,
        status_url=status_url(acct, tenant.slug if tenant else ""),
    )
    if result.error:
        msg.status, msg.error = "failed", result.error[:300]
    else:
        msg.status, msg.provider_id = "sent", result.provider_id
    await db.flush()
    summary = f"SMS {'sent' if msg.status == 'sent' else 'not sent'}: {text[:120]}"
    await L.log(
        db,
        lead,
        "sms_sent",
        summary,
        None,
        {"sms_id": str(msg.id), "status": msg.status, "error": msg.error},
        body=text,
    )
    if msg.status == "sent":
        lead.last_contacted_at = now()
        await emit(db, lead.tenant_id, "sms.sent", {"lead_id": str(lead.id), "sms_id": str(msg.id)})
    return msg


async def find_lead_by_number(
    db: AsyncSession, tenant_id: uuid.UUID, raw: str
) -> tuple[str, Lead | None]:
    country = await L.tenant_country(db, tenant_id)
    phone = normalize("phone", raw[:40], country)
    from app.modules.calls.service import find_lead  # open leads first, then the most recent

    return phone, await find_lead(db, phone)


async def incoming(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    number: str,
    body: str,
    provider: str,
    provider_id: str | None,
) -> SmsMessage | None:
    """A reply. STOP opts out (the number is suppressed even without a lead). Repeats of the
    same provider message are ignored. Unknown numbers that aren't STOP are not kept."""
    if provider_id and await db.scalar(
        select(SmsMessage.id).where(
            SmsMessage.provider == provider, SmsMessage.provider_id == provider_id
        )
    ):
        return None
    try:
        phone, lead = await find_lead_by_number(db, tenant_id, number)
    except Invalid:
        return None
    stop = is_stop(body)
    if stop:
        await C.suppress(db, tenant_id, "sms", [phone], "opt_out")
    if lead is None:
        return None
    msg = SmsMessage(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        lead_id=lead.id,
        direction="in",
        number=phone,
        body=(body or "")[:MAX_BODY],
        status="received",
        provider=provider,
        provider_id=provider_id,
    )
    db.add(msg)
    await db.flush()
    await L.log(
        db,
        lead,
        "sms_received",
        f"SMS received: {(body or '')[:120]}",
        None,
        {"sms_id": str(msg.id), "stop": stop},
        body=(body or "")[:MAX_BODY],
    )
    lead.last_activity_at = now()
    if stop:
        await C.record(db, lead, "sms", "opted_out", "unsubscribe")
    await emit(db, tenant_id, "sms.received", {"lead_id": str(lead.id), "sms_id": str(msg.id)})
    return msg


DELIVERED = {"delivered", "1", "success"}
FAILED = {"undelivered", "failed", "2", "16", "rejected", "ndnc"}


async def status_update(
    db: AsyncSession, provider: str, provider_id: str, status: str, error: str | None = None
) -> bool:
    """The provider's delivery report. Returns False when the message isn't ours."""
    msg = await db.scalar(
        select(SmsMessage).where(
            SmsMessage.provider == provider, SmsMessage.provider_id == provider_id
        )
    )
    if msg is None:
        return False
    s = (status or "").strip().lower()
    if s in DELIVERED and msg.status != "delivered":
        msg.status, msg.delivered_at = "delivered", now()
    elif s in FAILED and msg.status != "delivered":
        msg.status, msg.error = "failed", (error or s)[:300]
    return True

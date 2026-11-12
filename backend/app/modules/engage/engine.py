"""The sequence engine (step 9a, Decision log #39).

A lead in a sequence has an enrolment pointing at its next step. Every 30 seconds the worker
runs each company's due enrolments: emails go out inside quiet hours and under the daily cap,
tasks are made for the owner, waits push the next run, and check steps jump. Before every step
the stop rules are checked, and at every email consent, unsubscribes and the suppression list
are checked again (rule 8), so nobody is emailed after opting out, even mid-sequence.
"""

import secrets
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Invalid
from app.core.events import emit
from app.core.tenancy import tenant_session
from app.modules.auth.deps import CurrentUser
from app.modules.crm import consent as C
from app.modules.crm import leads as L
from app.modules.crm.models import Customer, Deal, Lead, Task
from app.modules.engage import render as R
from app.modules.engage import sender as S
from app.modules.engage.models import (
    Enrolment,
    Message,
    MessageEvent,
    MessageTemplate,
    Sequence,
    SequenceStep,
)
from app.modules.money.models import Payment
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User
from app.platform.models import Tenant

STOP_RULES = {
    "reply": "they replied",
    "customer": "they became a customer",
    "deal_won": "a deal was won",
    "payment": "a payment arrived",
    "closed": "the lead was closed",
}
REASONS = STOP_RULES | {
    "opted_out": "they opted out of email",
    "unsubscribed": "they unsubscribed",
    "bounced": "their email bounced",
    "complaint": "they marked an email as spam",
    "suppressed": "their address is on the do-not-contact list",
    "manual": "stopped by hand",
    "sequence_off": "the sequence was switched off",
    "lead_deleted": "the lead was deleted",
}
STEPS_PER_RUN = 10  # check and task steps run straight on; this bounds one run
MAX_SEND_TRIES = 3
RETRY_AFTER = timedelta(minutes=15)
DUE_BATCH = 100


def now() -> datetime:
    return datetime.now(UTC)


# ---------- quiet hours and the daily cap ----------
def _hhmm(text: str) -> time | None:
    """'09:30' → 09:30; '24:00' → None (until midnight)."""
    h, m = text.split(":")
    return None if int(h) == 24 else time(int(h), int(m))


def next_open(at: datetime, engage: dict, tz: str) -> datetime:
    """`at` if it is inside sending hours, else the start of the next sending window."""
    zone = ZoneInfo(tz)
    local = at.astimezone(zone)
    start_t = _hhmm(engage.get("from", "09:00")) or time.min
    end_t = _hhmm(engage.get("to", "20:00"))
    days = set(engage.get("days", [0, 1, 2, 3, 4, 5]))
    for i in range(8):
        d = local.date() + timedelta(days=i)
        if d.weekday() not in days:
            continue
        start = datetime.combine(d, start_t, zone)
        end = (
            datetime.combine(d + timedelta(days=1), time.min, zone)
            if end_t is None
            else datetime.combine(d, end_t, zone)
        )
        if local < start:
            return start.astimezone(UTC)
        if start <= local < end:
            return at
    return at + timedelta(days=1)  # no sending days set: try again tomorrow


async def _sent_today(db: AsyncSession, tz: str) -> int:
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    start = datetime.combine(today, time.min, zone)
    return (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.channel == "email", Message.direction == "out", Message.sent_at >= start)
        )
        or 0
    )


def _tomorrow_open(engage: dict, tz: str) -> datetime:
    zone = ZoneInfo(tz)
    tomorrow = datetime.combine(datetime.now(zone).date() + timedelta(days=1), time.min, zone)
    return next_open(tomorrow.astimezone(UTC), engage, tz)


# ---------- variables ----------
async def values_for(db: AsyncSession, lead: Lead, company: str) -> dict[str, str | None]:
    owner = await db.get(User, lead.owner_user_id) if lead.owner_user_id else None
    v: dict[str, str | None] = {
        "lead.first_name": lead.first_name,
        "lead.last_name": lead.last_name,
        "lead.name": lead.display_name,
        "lead.company": lead.org_name,
        "lead.city": lead.city,
        "lead.email": lead.primary_email,
        "lead.phone": lead.primary_phone,
        "owner.name": owner.name if owner else None,
        "owner.email": owner.email if owner else None,
        "owner.phone": owner.phone if owner else None,
        "company.name": company,
    }
    for k, val in (lead.custom_fields or {}).items():
        v[f"lead.cf.{k}"] = ", ".join(map(str, val)) if isinstance(val, list) else str(val)
    return v


def workspace_url(slug: str) -> str:
    return f"https://{slug}.{get_settings().base_domain}"


# ---------- enrol / stop ----------
async def enrol(
    db: AsyncSession, actor: CurrentUser | None, seq: Sequence, lead: Lead
) -> Enrolment | str:
    """Puts a lead into a sequence. Returns the enrolment, or why it was skipped."""
    if not seq.is_active:
        return "the sequence is switched off"
    if not lead.is_open:
        return "the lead is closed"
    active = (
        await db.scalars(
            select(Enrolment).where(Enrolment.lead_id == lead.id, Enrolment.status == "active")
        )
    ).all()
    if any(e.sequence_id == seq.id for e in active):
        return "already in this sequence"
    if active and not seq.allow_with_others:
        others = await db.scalars(
            select(Sequence).where(Sequence.id.in_([e.sequence_id for e in active]))
        )
        if not all(o.allow_with_others for o in others.all()):
            return "already in another sequence"
    if lead.email_consent == "opted_out":
        has_email = await db.scalar(
            select(SequenceStep.id).where(
                SequenceStep.sequence_id == seq.id, SequenceStep.kind == "email"
            )
        )
        if has_email:
            return "they opted out of email"
    e = Enrolment(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        sequence_id=seq.id,
        lead_id=lead.id,
        status="active",
        position=1,
        next_run_at=now(),
        enrolled_by_user_id=actor.user.id if actor else None,
        started_at=now(),
    )
    db.add(e)
    await db.flush()
    await L.log(
        db,
        lead,
        "sequence_enrolled",
        f"Added to {seq.name}",
        actor,
        {"sequence_id": str(seq.id), "enrolment_id": str(e.id)},
    )
    await emit(
        db,
        lead.tenant_id,
        "sequence.enrolled",
        {"lead_id": str(lead.id), "sequence_id": str(seq.id), "enrolment_id": str(e.id)},
    )
    return e


async def end(
    db: AsyncSession,
    e: Enrolment,
    status: str,
    reason: str | None,
    actor: CurrentUser | None = None,
) -> None:
    if e.status != "active":
        return
    e.status, e.ended_reason, e.ended_at, e.next_run_at = status, reason, now(), None
    seq = await db.get(Sequence, e.sequence_id)
    lead = await db.get(Lead, e.lead_id)
    if lead is None:
        return
    summary = (
        f"{seq.name}: finished"
        if status == "completed"
        else f"{seq.name} stopped: {REASONS.get(reason, reason)}"
    )
    await L.log(
        db,
        lead,
        "sequence_ended",
        summary,
        actor,
        {"sequence_id": str(seq.id), "enrolment_id": str(e.id), "status": status, "reason": reason},
    )


async def stop_all(db: AsyncSession, lead_id: uuid.UUID, reason: str) -> None:
    for e in (
        await db.scalars(
            select(Enrolment).where(Enrolment.lead_id == lead_id, Enrolment.status == "active")
        )
    ).all():
        await end(db, e, "stopped", reason)


async def _stop_reason(db: AsyncSession, e: Enrolment, seq: Sequence, lead: Lead) -> str | None:
    if lead.email_consent == "opted_out":
        return "opted_out"
    flags = (
        await db.execute(
            select(
                func.bool_or(Message.unsubscribed_at.isnot(None)),
                func.bool_or(Message.bounced_at.isnot(None)),
                func.bool_or(Message.replied_at.isnot(None)),
            ).where(Message.enrolment_id == e.id)
        )
    ).one()
    if flags[0]:
        return "unsubscribed"
    if flags[1]:
        return "bounced"
    rules = set(seq.stop_on or [])
    if "closed" in rules and not lead.is_open:
        return "closed"
    if "reply" in rules:
        replied = flags[2] or await db.scalar(
            select(Message.id)
            .where(
                Message.lead_id == lead.id,
                Message.direction == "in",
                Message.created_at >= e.started_at,
            )
            .limit(1)
        )
        if replied:
            return "reply"
    if "customer" in rules and await db.scalar(
        select(Customer.id).where(Customer.lead_id == lead.id, Customer.since >= e.started_at)
    ):
        return "customer"
    if "deal_won" in rules and await db.scalar(
        select(Deal.id)
        .where(Deal.lead_id == lead.id, Deal.status == "won", Deal.closed_at >= e.started_at)
        .limit(1)
    ):
        return "deal_won"
    if "payment" in rules and await db.scalar(
        select(Payment.id)
        .where(
            Payment.lead_id == lead.id, Payment.status == "ok", Payment.created_at >= e.started_at
        )
        .limit(1)
    ):
        return "payment"
    return None


# ---------- steps ----------
async def _check(db: AsyncSession, e: Enrolment, lead: Lead, cfg: dict) -> bool:
    kind = cfg.get("if")
    if kind in ("opened", "clicked", "replied"):
        col = {
            "opened": Message.opened_at,
            "clicked": Message.clicked_at,
            "replied": Message.replied_at,
        }[kind]
        return bool(
            await db.scalar(
                select(Message.id).where(Message.enrolment_id == e.id, col.isnot(None)).limit(1)
            )
        )
    if kind == "tag":
        from app.modules.crm import tags as T

        return bool(
            await db.scalar(
                select(Lead.id).where(
                    Lead.id == lead.id, T.has_any(Lead.id, [uuid.UUID(cfg["tag_id"])])
                )
            )
        )
    if kind == "field":
        value = (lead.custom_fields or {}).get(cfg.get("field", ""))
        wanted = str(cfg.get("value", ""))
        return (
            wanted in [str(v) for v in value] if isinstance(value, list) else str(value) == wanted
        )
    return False


async def _email(
    db: AsyncSession, e: Enrolment, seq: Sequence, step: SequenceStep, lead: Lead, tenant: Tenant
) -> str:
    """Send one email step. Returns 'sent', 'skipped', 'retry' or a stop reason."""
    to = lead.primary_email
    if not to:
        await L.log(
            db,
            lead,
            "email_sent",
            f"{seq.name}: email skipped — no email address",
            None,
            {"sequence_id": str(seq.id), "skipped": True},
        )
        return "skipped"
    if lead.email_consent == "opted_out":
        return "opted_out"
    if await C.is_suppressed(db, "email", [to.lower()]):
        return "suppressed"
    tpl = await db.get(MessageTemplate, uuid.UUID(step.config["template_id"]))
    if tpl is None or not tpl.is_active:
        await L.log(
            db,
            lead,
            "email_sent",
            f"{seq.name}: email skipped — its template is missing or off",
            None,
            {"sequence_id": str(seq.id), "skipped": True},
        )
        return "skipped"
    values = await values_for(db, lead, tenant.name)
    subject = R.fill(tpl.subject or "", values).strip() or tpl.name
    body = R.fill(tpl.body, values)
    token = secrets.token_urlsafe(24)
    base = workspace_url(tenant.slug)
    unsubscribe = f"{base}/api/v1/u/{token}"
    built = R.build_email(
        body, track_base=f"{base}/api/v1/t", token=token, unsubscribe_url=unsubscribe
    )
    from_name, from_email = await S.sender_address(db, tenant.name)
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        channel="email",
        direction="out",
        enrolment_id=e.id,
        step_id=step.id,
        template_id=tpl.id,
        to_address=to,
        from_address=from_email,
        subject=subject,
        body=body,
        links=built.links,
        token=token,
        status="queued",
    )
    db.add(msg)
    await db.flush()
    try:
        msg.provider_id = await S.send(
            db,
            to=to,
            subject=subject,
            text=built.text,
            html=built.html,
            from_name=from_name,
            from_email=from_email,
            unsubscribe_url=unsubscribe,
        )
    except Invalid as err:
        msg.status, msg.error = "failed", str(err.detail)[:300]
        tries = await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.enrolment_id == e.id, Message.step_id == step.id, Message.status == "failed"
            )
        )
        if tries >= MAX_SEND_TRIES:
            await L.log(
                db,
                lead,
                "email_sent",
                f"{seq.name}: email not sent — {msg.error}",
                None,
                {"sequence_id": str(seq.id), "message_id": str(msg.id), "failed": True},
            )
            return "skipped"
        return "retry"
    msg.status, msg.sent_at = "sent", now()
    await L.log(
        db,
        lead,
        "email_sent",
        f"Email sent: {subject}",
        None,
        {"sequence_id": str(seq.id), "sequence": seq.name, "message_id": str(msg.id)},
        body=body[:2000],
    )
    lead.last_activity_at = now()
    return "sent"


async def _task(db: AsyncSession, seq: Sequence, step: SequenceStep, lead: Lead) -> None:
    cfg = step.config
    if not lead.owner_user_id:
        await L.log(
            db,
            lead,
            "sequence_enrolled",
            f"{seq.name}: task “{cfg['title']}” skipped — no owner",
            None,
            {"sequence_id": str(seq.id)},
        )
        return
    task = Task(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        title=cfg["title"][:200],
        notes=f"From the sequence {seq.name}",
        due_at=now() + timedelta(hours=int(cfg.get("due_in_hours", 0))),
        owner_user_id=lead.owner_user_id,
        status="open",
        priority="normal",
        created_from="sequence",
    )
    db.add(task)
    await db.flush()
    await emit(
        db, lead.tenant_id, "task.created", {"task_id": str(task.id), "lead_id": str(lead.id)}
    )


async def advance(db: AsyncSession, e: Enrolment, tenant: Tenant, settings: TenantSettings) -> None:
    """Run this enrolment's steps until it must wait (a wait step, quiet hours, the cap)."""
    seq = await db.get(Sequence, e.sequence_id)
    lead = await db.get(Lead, e.lead_id)
    if lead is None:
        e.status, e.ended_reason, e.ended_at, e.next_run_at = "stopped", "lead_deleted", now(), None
        return
    if not seq.is_active:
        await end(db, e, "stopped", "sequence_off")
        return
    steps = {
        s.position: s
        for s in (
            await db.scalars(select(SequenceStep).where(SequenceStep.sequence_id == seq.id))
        ).all()
    }
    engage, tz = settings.engage or {}, settings.timezone
    for _ in range(STEPS_PER_RUN):
        if reason := await _stop_reason(db, e, seq, lead):
            await end(db, e, "stopped", reason)
            return
        step = steps.get(e.position)
        if step is None:
            await end(db, e, "completed", None)
            return
        if step.kind == "wait":
            e.position += 1
            e.next_run_at = now() + timedelta(hours=float(step.config.get("hours", 24)))
            return
        if step.kind == "check":
            e.position = (
                int(step.config["go_to"])
                if await _check(db, e, lead, step.config)
                else e.position + 1
            )
            continue
        if step.kind == "task":
            await _task(db, seq, step, lead)
            e.position += 1
            continue
        if step.kind == "email":
            opens = next_open(now(), engage, tz)
            if opens > now():
                e.next_run_at = opens
                return
            if await _sent_today(db, tz) >= int(engage.get("daily_cap", 200)):
                e.next_run_at = _tomorrow_open(engage, tz)
                return
            outcome = await _email(db, e, seq, step, lead, tenant)
            if outcome == "retry":
                e.next_run_at = now() + RETRY_AFTER
                return
            if outcome in REASONS:
                await end(db, e, "stopped", outcome)
                return
            e.position += 1
            continue
        e.position += 1  # a step kind this slice does not run (WhatsApp arrives in step 10)
    e.next_run_at = now()  # many quick steps: carry on next run


async def run_due(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as db:
        due = (
            await db.scalars(
                select(Enrolment)
                .where(Enrolment.status == "active", Enrolment.next_run_at <= now())
                .order_by(Enrolment.next_run_at)
                .limit(DUE_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not due:
            return 0
        tenant = await db.get(Tenant, tenant_id)
        settings = await db.get(TenantSettings, tenant_id)
        for e in due:
            await advance(db, e, tenant, settings)
        return len(due)


async def run_all(tenant_ids: list[uuid.UUID]) -> int:
    return sum([await run_due(t) for t in tenant_ids])


# ---------- tracking ----------
async def _event(db: AsyncSession, msg: Message, kind: str, data: dict | None = None) -> None:
    db.add(MessageEvent(tenant_id=msg.tenant_id, message_id=msg.id, type=kind, data=data or {}))


async def record_open(db: AsyncSession, msg: Message) -> None:
    await _event(db, msg, "open")
    if msg.opened_at is None:
        msg.opened_at = now()
        if lead := await db.get(Lead, msg.lead_id) if msg.lead_id else None:
            await L.log(
                db,
                lead,
                "email_event",
                f"Opened: {msg.subject} (estimated)",
                None,
                {"message_id": str(msg.id), "event": "open"},
            )


async def record_click(db: AsyncSession, msg: Message, index: int) -> str | None:
    if not 0 <= index < len(msg.links or []):
        return None
    url = msg.links[index]
    await _event(db, msg, "click", {"url": url})
    if msg.clicked_at is None:
        msg.clicked_at = now()
        msg.opened_at = msg.opened_at or msg.clicked_at  # a click means it was opened
        if lead := await db.get(Lead, msg.lead_id) if msg.lead_id else None:
            await L.log(
                db,
                lead,
                "email_event",
                f"Clicked a link in: {msg.subject}",
                None,
                {"message_id": str(msg.id), "event": "click", "url": url},
            )
    return url


async def _opt_out(db: AsyncSession, msg: Message, reason: str, consent_source: str) -> None:
    await C.suppress(db, msg.tenant_id, "email", [msg.to_address.lower()], reason)
    lead = await db.get(Lead, msg.lead_id) if msg.lead_id else None
    if lead is not None:
        if reason in ("opt_out", "complaint") and lead.email_consent != "opted_out":
            await C.record(
                db,
                lead,
                "email",
                "opted_out",
                consent_source,
                evidence={"message_id": str(msg.id), "reason": reason},
            )
        await stop_all(
            db,
            lead.id,
            {"opt_out": "unsubscribed", "bounce": "bounced", "complaint": "complaint"}[reason],
        )


async def unsubscribe(db: AsyncSession, msg: Message) -> None:
    if msg.unsubscribed_at is not None:
        return
    msg.unsubscribed_at = now()
    await _event(db, msg, "unsubscribe")
    await _opt_out(db, msg, "opt_out", "unsubscribe")
    if lead := await db.get(Lead, msg.lead_id) if msg.lead_id else None:
        await L.log(
            db,
            lead,
            "email_event",
            f"Unsubscribed from emails ({msg.subject})",
            None,
            {"message_id": str(msg.id), "event": "unsubscribe"},
        )


async def record_bounce(db: AsyncSession, msg: Message, *, hard: bool, detail: str = "") -> None:
    """A hard bounce (address doesn't exist) suppresses it and stops sequences; a soft one
    (mailbox full, server busy) is only recorded."""
    await _event(db, msg, "bounce", {"hard": hard, "detail": detail[:300]})
    if hard:
        msg.bounced_at, msg.status = now(), "bounced"
        await _opt_out(db, msg, "bounce", "unsubscribe")
    if lead := await db.get(Lead, msg.lead_id) if msg.lead_id else None:
        await L.log(
            db,
            lead,
            "email_event",
            f"Email bounced{'' if hard else ' (temporary)'}: {msg.subject}",
            None,
            {"message_id": str(msg.id), "event": "bounce", "hard": hard},
        )


async def record_complaint(db: AsyncSession, msg: Message) -> None:
    await _event(db, msg, "complaint")
    await _opt_out(db, msg, "complaint", "unsubscribe")


async def record_delivered(db: AsyncSession, msg: Message) -> None:
    await _event(db, msg, "delivered")
    if msg.status == "sent":
        msg.status = "delivered"

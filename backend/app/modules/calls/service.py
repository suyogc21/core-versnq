"""The call pipeline (step C1, docs/plans/calls-plan.md). Every call, from our Android app (the
rep's own SIM), the company's own Twilio or later Exotel, goes the same way:

1. reported: number, direction, status, when, how long, by whom, and the source's own id (a
   repeat is the same call);
2. matched to the lead by number (an unknown number is not kept, unless the company makes
   leads from unknown incoming calls: personal calls stay out of the CRM);
3. on the timeline at once (direction, length, later the recording and ACE's summary); the rep
   then adds the Outcome and next follow-up with the usual one-step rules;
4. a missed incoming call becomes a "call back" task for the lead's owner;
5. the recording (if the company records calls) is kept for `keep_days` (30 by default), then
   removed by the nightly job; the call stays on the timeline.
Events: call.logged, call.recorded (ACE fetches and analyses it), call.analyzed.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.errors import Invalid
from app.core.events import emit
from app.modules.auth.deps import CurrentUser
from app.modules.calls.models import CALL_DEFAULTS, Call
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.identities import normalize
from app.modules.crm.models import Activity, Lead, LeadIdentity, LeadSource, Task
from app.modules.crm.notify import notify
from app.modules.crm.routing import mark_contacted
from app.modules.settings.models import TenantSettings

STATUSES = ("answered", "missed", "no_answer", "busy", "failed")
WORDS = {"answered": "", "missed": "Missed call", "no_answer": "No answer", "busy": "Busy",
         "failed": "Call failed"}  # fmt: skip


def length(seconds: int) -> str:
    m, s = divmod(max(seconds, 0), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def summary_of(call: Call) -> str:
    if call.status != "answered":
        word = WORDS[call.status]
        return word if call.status == "missed" else f"{word} (outgoing)"
    way = "Incoming" if call.direction == "in" else "Outgoing"
    return f"{way} call · {length(call.duration_seconds)}"


async def settings_of(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    s = await db.get(TenantSettings, tenant_id)
    return {**CALL_DEFAULTS, **((s.calls if s else None) or {})}


async def find_lead(db: AsyncSession, phone: str) -> Lead | None:
    """The lead with this number: open leads first, then the most recently active."""
    return await db.scalar(
        select(Lead)
        .join(LeadIdentity, LeadIdentity.lead_id == Lead.id)
        .where(LeadIdentity.type == "phone", LeadIdentity.value_normalized == phone)
        .order_by(Lead.is_open.desc(), Lead.last_activity_at.desc().nulls_last())
        .limit(1)
    )


async def _new_lead(db: AsyncSession, tenant_id: uuid.UUID, phone: str) -> Lead | None:
    sources = (
        await db.scalars(
            select(LeadSource).where(LeadSource.is_active.is_(True)).order_by(LeadSource.position)
        )
    ).all()
    source = next((s for s in sources if s.name.strip().lower() == "phone"), None) or (
        sources[0] if sources else None
    )
    if source is None:
        return None
    out = await I.intake(
        db,
        tenant_id,
        I.Incoming(
            identities=[L.IdentityInput(type="phone", value=phone, is_primary=True)],
            source_id=source.id,
            created_via="call",
            fields={},
            owner=I.RULES,
            enforce_required=False,
            via_label="a phone call",
        ),
        policy="update",
    )
    return out.lead


async def report(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    actor: CurrentUser | None,
    user_id: uuid.UUID | None,
    source: str,
    external_id: str,
    direction: str,
    status: str,
    number: str,
    started_at: datetime,
    duration_seconds: int,
) -> Call | None:
    """Record one call. Returns the same call for a repeat, and None when the number is not a
    lead's and the company doesn't make leads from unknown calls (nothing is kept then)."""
    same = await db.scalar(
        select(Call).where(Call.source == source, Call.external_id == external_id)
    )
    if same is not None:
        return same
    if started_at > L.now() + timedelta(minutes=5):
        raise Invalid("A call can't start in the future")
    country = await L.tenant_country(db, tenant_id)
    phone = normalize("phone", number, country)  # raises Invalid for a bad number
    lead = await find_lead(db, phone)
    if lead is None:
        cfg = await settings_of(db, tenant_id)
        if direction != "in" or not cfg["new_leads"]:
            return None
        lead = await _new_lead(db, tenant_id, phone)
        if lead is None:
            return None
    if status != "answered":
        duration_seconds = 0
    call = Call(
        id=uuid.uuid4(), tenant_id=tenant_id, lead_id=lead.id, user_id=user_id,
        direction=direction, status=status, number=phone, started_at=started_at,
        duration_seconds=duration_seconds, source=source, external_id=external_id,
    )  # fmt: skip
    db.add(call)
    await db.flush()
    activity = await L.log(
        db, lead, "call", summary_of(call), actor,
        {"call_id": str(call.id), "direction": direction, "status": status,
         "duration_seconds": duration_seconds, "source": source, "recording": False},
        occurred_at=started_at,
    )  # fmt: skip
    call.activity_id = activity.id
    lead.last_activity_at = max(filter(None, [lead.last_activity_at, started_at]))
    if status == "answered":
        lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, started_at]))
        lead.first_response_at = lead.first_response_at or started_at
        await mark_contacted(db, lead)
    elif direction == "in":  # a missed incoming call: the owner calls back
        owner = lead.owner_user_id or user_id
        if owner:
            db.add(Task(
                tenant_id=tenant_id, lead_id=lead.id, title=f"Call back {lead.display_name}"[:200],
                due_at=L.now(), owner_user_id=owner, priority="high", created_from="call",
            ))  # fmt: skip
            await notify(db, tenant_id, [owner], "missed_call",
                         f"Missed call from {lead.display_name}", lead.id)  # fmt: skip
    lead.version += 1
    await emit(db, tenant_id, "call.logged", {
        "call_id": str(call.id), "lead_id": str(lead.id), "direction": direction,
        "status": status, "duration_seconds": duration_seconds, "source": source,
        "user_id": str(user_id) if user_id else None,
    })  # fmt: skip
    return call


async def _activity(db: AsyncSession, call: Call) -> Activity | None:
    return await db.get(Activity, call.activity_id) if call.activity_id else None


async def attach_recording(db: AsyncSession, call: Call, data: bytes, name: str) -> Call:
    cfg = await settings_of(db, call.tenant_id)
    if not cfg["record"]:
        raise Invalid("Your company doesn't keep call recordings", code="recording_off")
    if call.recording_path or call.recording_removed_at:
        raise Invalid("This call already has its recording", code="recording_exists")
    kind = storage.sniff_audio(data[:16], name)
    if kind is None:
        raise Invalid("Send the recording as MP3, M4A, AAC, AMR, WAV, OGG or WEBM audio")
    from app.modules.crm.customers import storage_used  # every file counts against the quota

    s = await db.get(TenantSettings, call.tenant_id)
    if await storage_used(db) + await recordings_used(db) + len(data) > s.storage_quota_bytes:
        raise Invalid("Your company has used all of its file storage", code="storage_full")
    saved = storage.save(call.tenant_id, data, kind[1], kind[0])
    call.recording_path, call.recording_type = saved.path, saved.content_type
    call.recording_bytes = saved.size_bytes
    if act := await _activity(db, call):
        act.data = {**act.data, "recording": True}
    await db.flush()
    await emit(db, call.tenant_id, "call.recorded", {
        "call_id": str(call.id), "lead_id": str(call.lead_id) if call.lead_id else None,
        "duration_seconds": call.duration_seconds, "content_type": call.recording_type,
        "recording_url": f"/api/v1/calls/{call.id}/recording",
    })  # fmt: skip
    return call


async def recordings_used(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.coalesce(func.sum(Call.recording_bytes), 0)).where(
                Call.recording_path.is_not(None)
            )
        )
    )


async def save_analysis(db: AsyncSession, call: Call, summary: str, analysis: dict) -> Call:
    """A newer analysis replaces the old one; the same one sent again (a retry) changes nothing
    and sends no second call.analyzed. Never a second timeline entry."""
    if call.analyzed_at is not None and call.summary == summary and call.analysis == analysis:
        return call
    call.summary, call.analysis, call.analyzed_at = summary, analysis, datetime.now(UTC)
    if act := await _activity(db, call):
        act.data = {**act.data, "summary": summary[:2000]}
    await db.flush()
    await emit(db, call.tenant_id, "call.analyzed", {
        "call_id": str(call.id), "lead_id": str(call.lead_id) if call.lead_id else None,
        "summary": summary[:2000],
    })  # fmt: skip
    return call


async def expire_recordings(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Nightly: recordings older than the company's keep_days are removed; the call stays."""
    keep = int((await settings_of(db, tenant_id))["keep_days"])
    cutoff = datetime.now(UTC) - timedelta(days=keep)
    old = (
        await db.scalars(
            select(Call).where(Call.recording_path.is_not(None), Call.started_at < cutoff)
        )
    ).all()
    for call in old:
        storage.remove(call.recording_path)
        call.recording_path, call.recording_removed_at = None, datetime.now(UTC)
        if act := await _activity(db, call):
            act.data = {**act.data, "recording": False, "recording_removed": True}
    return len(old)

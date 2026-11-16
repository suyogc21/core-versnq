"""Calls (step C1, docs/plans/calls-plan.md): report a call, its recording, ACE's analysis, the
Outcome; list and play calls with the lead visibility rules."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import storage
from app.core.errors import Forbidden, NotFound
from app.modules.auth.deps import CurrentUser, require
from app.modules.calls import phone
from app.modules.calls import service as S
from app.modules.calls.models import Call
from app.modules.crm import leads as L
from app.modules.crm import work as W
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import Activity, Lead
from app.modules.settings.models import TenantSettings

router = APIRouter(prefix="/api/v1", tags=["calls"], dependencies=CRM)
Worker = Annotated[CurrentUser, require("leads.edit")]
Admin = Annotated[CurrentUser, require("settings.manage")]
Status = Literal["answered", "missed", "no_answer", "busy", "failed"]


class CallIn(BaseModel):
    """Reported by our phone app for the signed-in rep (the rep's own SIM)."""

    external_id: str = Field(min_length=1, max_length=100)  # the phone's own id for the call
    direction: Literal["in", "out"]
    status: Status
    number: str = Field(min_length=3, max_length=40)  # the other side
    started_at: datetime
    duration_seconds: int = Field(default=0, ge=0, le=86400)


class CallOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID | None
    lead_name: str | None = None
    user_id: uuid.UUID | None
    direction: str
    status: str
    number: str
    started_at: datetime
    duration_seconds: int
    source: str
    activity_id: uuid.UUID | None
    outcome: str | None = None
    has_recording: bool
    recording_removed: bool
    summary: str | None
    analysis: dict
    analyzed_at: datetime | None


class ReportOut(BaseModel):
    tracked: bool  # false: the number isn't a lead's, so nothing was kept
    call: CallOut | None = None


class OutcomeIn(BaseModel):
    disposition: str = Field(min_length=1, max_length=60)
    body: str | None = Field(default=None, max_length=10000)
    next_follow_up_at: datetime | None = None


class AnalysisIn(BaseModel):
    """ACE's analysis of the recording (step C5)."""

    summary: str = Field(min_length=1, max_length=4000)
    intent: str | None = Field(default=None, max_length=40)
    next_step: str | None = Field(default=None, max_length=500)
    red_flags: list[Annotated[str, Field(max_length=200)]] = Field(default=[], max_length=10)
    language: str | None = Field(default=None, max_length=20)
    transcript: str | None = Field(default=None, max_length=200000)


class CallSettings(BaseModel):
    record: bool = True
    keep_days: int = Field(default=30, ge=1, le=3650)
    new_leads: bool = False  # an unknown incoming number makes a lead


async def _out(db, calls: list[Call]) -> list[CallOut]:
    lead_ids = {c.lead_id for c in calls if c.lead_id}
    names = dict((await db.execute(select(Lead.id, Lead.display_name).where(
        Lead.id.in_(lead_ids)))).all()) if lead_ids else {}  # fmt: skip
    act_ids = {c.activity_id for c in calls if c.activity_id}
    outcomes = dict((await db.execute(select(Activity.id, Activity.disposition).where(
        Activity.id.in_(act_ids)))).all()) if act_ids else {}  # fmt: skip
    return [
        CallOut(
            id=c.id,
            lead_id=c.lead_id,
            lead_name=names.get(c.lead_id),
            user_id=c.user_id,
            direction=c.direction,
            status=c.status,
            number=c.number,
            started_at=c.started_at,
            duration_seconds=c.duration_seconds,
            source=c.source,
            activity_id=c.activity_id,
            outcome=outcomes.get(c.activity_id),
            has_recording=bool(c.recording_path),
            recording_removed=c.recording_removed_at is not None,
            summary=c.summary,
            analysis=c.analysis or {},
            analyzed_at=c.analyzed_at,
        )  # fmt: skip
        for c in calls
    ]


async def _visible(db, actor: CurrentUser, call_id: uuid.UUID) -> Call:
    """A call the caller may see: its lead is visible to them (the lead visibility rules)."""
    call = await db.get(Call, call_id)
    if call is None or call.lead_id is None:
        raise NotFound("Call not found")
    await L.get_visible(db, actor, call.lead_id)  # 404 when not visible
    return call


@router.post("/calls", response_model=ReportOut)
async def report_call(body: CallIn, request: Request, db: CrmDb, actor: Worker) -> ReportOut:
    await phone.note_call(db, request)
    call = await S.report(
        db, actor.user.tenant_id, actor=actor, user_id=actor.user.id, source="app",
        external_id=body.external_id, direction=body.direction, status=body.status,
        number=body.number, started_at=body.started_at, duration_seconds=body.duration_seconds,
    )  # fmt: skip
    if call is None:
        return ReportOut(tracked=False)
    return ReportOut(tracked=True, call=(await _out(db, [call]))[0])


@router.get("/calls", response_model=list[CallOut])
async def list_calls(
    db: CrmDb,
    actor: Worker,
    lead_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    status: Status | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CallOut]:
    q = (
        select(Call)
        .join(Lead, Lead.id == Call.lead_id)
        .where(await L.visibility_filter(db, actor))
        .order_by(Call.started_at.desc())
        .limit(limit)
    )
    if lead_id:
        q = q.where(Call.lead_id == lead_id)
    if user_id:
        q = q.where(Call.user_id == user_id)
    if status:
        q = q.where(Call.status == status)
    if before:
        q = q.where(Call.started_at < before)
    return await _out(db, list((await db.scalars(q)).all()))


@router.get("/calls/{call_id}", response_model=CallOut)
async def get_call(call_id: uuid.UUID, db: CrmDb, actor: Worker) -> CallOut:
    return (await _out(db, [await _visible(db, actor, call_id)]))[0]


@router.post("/calls/{call_id}/outcome", response_model=CallOut)
async def log_outcome(call_id: uuid.UUID, body: OutcomeIn, db: CrmDb, actor: Worker) -> CallOut:
    """The rep's Outcome and next follow-up for a reported call: the usual one-step rules."""
    call = await _visible(db, actor, call_id)
    lead = await L.get_visible(db, actor, call.lead_id)
    activity = await db.get(Activity, call.activity_id) if call.activity_id else None
    await W.log_activity(
        db, actor, lead, type_key="call", body=body.body,
        data={"disposition": body.disposition}, occurred_at=call.started_at,
        next_follow_up_at=body.next_follow_up_at, existing=activity,
    )  # fmt: skip
    return (await _out(db, [call]))[0]


@router.put("/calls/{call_id}/recording", response_model=CallOut)
async def upload_recording(
    call_id: uuid.UUID, request: Request, db: CrmDb, actor: Worker
) -> CallOut:
    """The raw audio as the body; X-File-Name gives its name. Only the call's own rep (their
    phone) or an integration may send it."""
    call = await _visible(db, actor, call_id)
    if call.user_id != actor.user.id and actor.user.status != "integration":
        raise Forbidden("Only the rep's own phone can send this recording")
    data = await storage.read_upload(request, limit=storage.MAX_AUDIO_BYTES)
    name = storage.clean_name(request.headers.get("x-file-name", "recording"))
    await S.attach_recording(db, call, data, name)
    return (await _out(db, [call]))[0]


@router.get("/calls/{call_id}/recording")
async def play_recording(call_id: uuid.UUID, db: CrmDb, actor: Worker) -> FileResponse:
    call = await _visible(db, actor, call_id)
    if not call.recording_path:
        raise NotFound("This call has no recording", code="no_recording")
    return FileResponse(
        storage.full_path(call.recording_path), media_type=call.recording_type,
        headers={"Cache-Control": "private, no-store"},
    )  # fmt: skip


@router.put("/calls/{call_id}/analysis", response_model=CallOut)
async def save_analysis(call_id: uuid.UUID, body: AnalysisIn, db: CrmDb, actor: Worker) -> CallOut:
    """ACE's summary of the call (only an integration key, i.e. ACE, sends this)."""
    if actor.user.status != "integration":
        raise Forbidden("Only ACE sends call analyses")
    call = await _visible(db, actor, call_id)
    analysis = body.model_dump(exclude={"summary"}, exclude_none=True)
    await S.save_analysis(db, call, body.summary, analysis)
    return (await _out(db, [call]))[0]


@router.get("/call-settings", response_model=CallSettings)
async def get_call_settings(db: CrmDb, actor: Worker) -> CallSettings:
    return CallSettings(**await S.settings_of(db, actor.user.tenant_id))


@router.put("/call-settings", response_model=CallSettings)
async def put_call_settings(body: CallSettings, db: CrmDb, actor: Admin) -> CallSettings:
    s = await db.get(TenantSettings, actor.user.tenant_id)
    before = dict(s.calls or {})
    s.calls = body.model_dump()
    await audit(db, actor, "call_settings.updated", "settings", None, before, s.calls)
    return body

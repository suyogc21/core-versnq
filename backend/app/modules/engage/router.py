"""Sequences, templates, enrolments, results and sending settings (step 9a, Decision log #39),
plus the public tracking and unsubscribe links that sit in every email."""

import base64
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import Conflict, Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import Customer, Deal, Lead, Tag
from app.modules.engage import engine as E
from app.modules.engage import render as R
from app.modules.engage.models import (
    Enrolment,
    Message,
    MessageTemplate,
    Sequence,
    SequenceStep,
)
from app.modules.settings.models import TenantSettings
from app.platform.models import Tenant

router = APIRouter(prefix="/api/v1", tags=["sequences"], dependencies=CRM)
public = APIRouter(prefix="/api/v1", tags=["sequences-public"], dependencies=CRM)
Manager = Annotated[CurrentUser, require("sequences.manage")]
Editor = Annotated[CurrentUser, require("leads.edit")]

MAX_STEPS = 30
MAX_ENROL = 500


# ---------- templates ----------
class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel: Literal["email"] = "email"  # WhatsApp templates arrive in step 10
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    is_active: bool = True


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    is_active: bool | None = None


class TemplateOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    channel: str
    subject: str | None
    body: str
    is_active: bool
    updated_at: datetime


class PreviewIn(BaseModel):
    lead_id: uuid.UUID


class PreviewOut(BaseModel):
    subject: str
    body: str


async def _custom_keys(db) -> set[str]:
    return set(await L.lead_fields(db))


async def _template(db, t_id: uuid.UUID) -> MessageTemplate:
    t = await db.get(MessageTemplate, t_id)
    if t is None:
        raise NotFound("Template not found")
    return t


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(db: CrmDb, actor: Manager) -> list[MessageTemplate]:
    return list((await db.scalars(select(MessageTemplate).order_by(MessageTemplate.name))).all())


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(body: TemplateIn, db: CrmDb, actor: Manager) -> MessageTemplate:
    keys = await _custom_keys(db)
    R.check(body.subject, keys)
    R.check(body.body, keys)
    name = " ".join(body.name.split())
    if await db.scalar(
        select(MessageTemplate.id).where(func.lower(MessageTemplate.name) == name.lower())
    ):
        raise Conflict(f"A template called {name} already exists")
    t = MessageTemplate(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        name=name,
        channel=body.channel,
        subject=body.subject.strip(),
        body=body.body,
        is_active=body.is_active,
        created_by_user_id=actor.user.id,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    await audit(db, actor, "template.created", "template", t.id, None, {"name": name})
    return t


@router.patch("/templates/{t_id}", response_model=TemplateOut)
async def update_template(t_id: uuid.UUID, body: TemplatePatch, db: CrmDb, actor: Manager):
    t = await _template(db, t_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    keys = await _custom_keys(db)
    for k in ("subject", "body"):
        if k in changes:
            R.check(changes[k], keys)
    if "name" in changes:
        changes["name"] = " ".join(changes["name"].split())
    for k, v in changes.items():
        setattr(t, k, v)
    await audit(db, actor, "template.updated", "template", t.id, None, {"fields": list(changes)})
    await db.flush()
    await db.refresh(t)
    return t


@router.delete("/templates/{t_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(t_id: uuid.UUID, db: CrmDb, actor: Manager) -> None:
    t = await _template(db, t_id)
    used = await db.scalar(
        select(Sequence.name)
        .join(SequenceStep, SequenceStep.sequence_id == Sequence.id)
        .where(SequenceStep.config["template_id"].astext == str(t.id))
        .limit(1)
    )
    if used:
        raise Conflict(f"The sequence {used} uses this template. Switch it off instead.")
    await db.delete(t)
    await audit(db, actor, "template.deleted", "template", t_id, {"name": t.name})


@router.post("/templates/{t_id}/preview", response_model=PreviewOut)
async def preview_template(t_id: uuid.UUID, body: PreviewIn, db: CrmDb, actor: Manager):
    """The template filled in for a real lead, before anything is sent."""
    t = await _template(db, t_id)
    lead = await L.get_visible(db, actor, body.lead_id)
    tenant = await db.get(Tenant, actor.user.tenant_id)
    values = await E.values_for(db, lead, tenant.name)
    return PreviewOut(subject=R.fill(t.subject or "", values), body=R.fill(t.body, values))


# ---------- sequences ----------
StopRule = Literal["reply", "customer", "deal_won", "payment", "closed"]


class StepIn(BaseModel):
    kind: Literal["email", "task", "wait", "check"]  # WhatsApp steps arrive in step 10
    template_id: uuid.UUID | None = None  # email
    title: str | None = Field(default=None, max_length=200)  # task
    task_type: Literal["call", "linkedin_connect", "linkedin_message", "other"] = "other"
    due_in_hours: int = Field(default=0, ge=0, le=24 * 30)
    hours: float | None = Field(default=None, gt=0, le=24 * 90)  # wait
    check_if: Literal["opened", "clicked", "replied", "tag", "field"] | None = None
    tag_id: uuid.UUID | None = None
    field: str | None = Field(default=None, max_length=60)
    value: str | None = Field(default=None, max_length=200)
    go_to: int | None = Field(default=None, ge=1)


class StepOut(BaseModel):
    id: uuid.UUID
    position: int
    kind: str
    config: dict


class SequenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    allow_with_others: bool = False
    stop_on: list[StopRule] = list(E.STOP_RULES)


class SequencePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    allow_with_others: bool | None = None
    stop_on: list[StopRule] | None = None


class SequenceOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    allow_with_others: bool
    stop_on: list[str]
    steps: list[StepOut]
    active: int
    completed: int
    stopped: int
    updated_at: datetime


async def _seq_out(db, seqs: list[Sequence]) -> list[SequenceOut]:
    ids = [s.id for s in seqs]
    counts: dict[tuple, int] = {}
    if ids:
        for sid, st, n in (
            await db.execute(
                select(Enrolment.sequence_id, Enrolment.status, func.count())
                .where(Enrolment.sequence_id.in_(ids))
                .group_by(Enrolment.sequence_id, Enrolment.status)
            )
        ).all():
            counts[(sid, st)] = n
    steps: dict[uuid.UUID, list[StepOut]] = {i: [] for i in ids}
    if ids:
        for s in (
            await db.scalars(
                select(SequenceStep)
                .where(SequenceStep.sequence_id.in_(ids))
                .order_by(SequenceStep.position)
            )
        ).all():
            steps[s.sequence_id].append(
                StepOut(id=s.id, position=s.position, kind=s.kind, config=s.config)
            )
    return [
        SequenceOut(
            id=s.id,
            name=s.name,
            description=s.description,
            is_active=s.is_active,
            allow_with_others=s.allow_with_others,
            stop_on=s.stop_on,
            steps=steps[s.id],
            active=counts.get((s.id, "active"), 0),
            completed=counts.get((s.id, "completed"), 0),
            stopped=counts.get((s.id, "stopped"), 0),
            updated_at=s.updated_at,
        )
        for s in seqs
    ]


async def _sequence(db, s_id: uuid.UUID) -> Sequence:
    s = await db.get(Sequence, s_id)
    if s is None:
        raise NotFound("Sequence not found")
    return s


@router.get("/sequences", response_model=list[SequenceOut])
async def list_sequences(db: CrmDb, actor: ActiveUser) -> list[SequenceOut]:
    """Anyone who can see leads may pick a sequence to put a lead into."""
    return await _seq_out(
        db, list((await db.scalars(select(Sequence).order_by(Sequence.name))).all())
    )


@router.post("/sequences", response_model=SequenceOut, status_code=status.HTTP_201_CREATED)
async def create_sequence(body: SequenceIn, db: CrmDb, actor: Manager) -> SequenceOut:
    name = " ".join(body.name.split())
    if await db.scalar(select(Sequence.id).where(func.lower(Sequence.name) == name.lower())):
        raise Conflict(f"A sequence called {name} already exists")
    s = Sequence(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        name=name,
        description=body.description,
        is_active=False,
        allow_with_others=body.allow_with_others,
        stop_on=sorted(set(body.stop_on)),
        created_by_user_id=actor.user.id,
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    await audit(db, actor, "sequence.created", "sequence", s.id, None, {"name": name})
    return (await _seq_out(db, [s]))[0]


@router.get("/sequences/{s_id}", response_model=SequenceOut)
async def get_sequence(s_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> SequenceOut:
    return (await _seq_out(db, [await _sequence(db, s_id)]))[0]


@router.patch("/sequences/{s_id}", response_model=SequenceOut)
async def update_sequence(s_id: uuid.UUID, body: SequencePatch, db: CrmDb, actor: Manager):
    s = await _sequence(db, s_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_active") and not await db.scalar(
        select(SequenceStep.id).where(SequenceStep.sequence_id == s.id).limit(1)
    ):
        raise Invalid("Add at least one step before switching the sequence on")
    for k, v in changes.items():
        if k == "name" and v:
            v = " ".join(v.split())
        if k == "stop_on" and v is not None:
            v = sorted(set(v))
        if v is not None or k == "description":
            setattr(s, k, v)
    if changes.get("is_active") is False:  # switched off: everyone in it stops now
        for e in (
            await db.scalars(
                select(Enrolment).where(Enrolment.sequence_id == s.id, Enrolment.status == "active")
            )
        ).all():
            await E.end(db, e, "stopped", "sequence_off", actor)
    await audit(db, actor, "sequence.updated", "sequence", s.id, None, changes)
    await db.flush()
    await db.refresh(s)
    return (await _seq_out(db, [s]))[0]


@router.put("/sequences/{s_id}/steps", response_model=SequenceOut)
async def set_steps(s_id: uuid.UUID, body: list[StepIn], db: CrmDb, actor: Manager):
    """Replace the steps. People already in the sequence carry on from their step number."""
    s = await _sequence(db, s_id)
    if len(body) > MAX_STEPS:
        raise Invalid(f"A sequence can have up to {MAX_STEPS} steps")
    out = []
    for i, st in enumerate(body, start=1):
        if st.kind == "email":
            t = await db.get(MessageTemplate, st.template_id) if st.template_id else None
            if t is None or t.channel != "email":
                raise Invalid(f"Step {i}: choose an email template")
            cfg = {"template_id": str(t.id)}
        elif st.kind == "task":
            title = " ".join((st.title or "").split())
            if not title:
                raise Invalid(f"Step {i}: give the task a title")
            cfg = {"title": title, "task_type": st.task_type, "due_in_hours": st.due_in_hours}
        elif st.kind == "wait":
            if not st.hours:
                raise Invalid(f"Step {i}: wait how long?")
            cfg = {"hours": st.hours}
        else:
            if not st.check_if or not st.go_to or st.go_to == i or st.go_to > len(body) + 1:
                raise Invalid(f"Step {i}: choose what to check and which step to go to")
            cfg = {"if": st.check_if, "go_to": st.go_to}
            if st.check_if == "tag":
                if not st.tag_id or not await db.get(Tag, st.tag_id):
                    raise Invalid(f"Step {i}: choose a tag")
                cfg["tag_id"] = str(st.tag_id)
            if st.check_if == "field":
                if st.field not in await L.lead_fields(db):
                    raise Invalid(f"Step {i}: choose a field")
                cfg |= {"field": st.field, "value": st.value or ""}
        out.append((st.kind, cfg))
    for old in (
        await db.scalars(select(SequenceStep).where(SequenceStep.sequence_id == s.id))
    ).all():
        await db.delete(old)
    await db.flush()
    for i, (kind, cfg) in enumerate(out, start=1):
        db.add(
            SequenceStep(tenant_id=s.tenant_id, sequence_id=s.id, position=i, kind=kind, config=cfg)
        )
    await audit(db, actor, "sequence.steps_saved", "sequence", s.id, None, {"steps": len(out)})
    await db.flush()
    return (await _seq_out(db, [s]))[0]


@router.delete("/sequences/{s_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sequence(s_id: uuid.UUID, db: CrmDb, actor: Manager) -> None:
    s = await _sequence(db, s_id)
    if await db.scalar(select(Enrolment.id).where(Enrolment.sequence_id == s.id).limit(1)):
        raise Conflict("People have been through this sequence; switch it off to keep its results")
    await db.delete(s)
    await audit(db, actor, "sequence.deleted", "sequence", s_id, {"name": s.name})


# ---------- enrolments ----------
class EnrolIn(BaseModel):
    lead_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_ENROL)


class EnrolSkipped(BaseModel):
    lead_id: uuid.UUID
    name: str | None
    reason: str


class EnrolOut(BaseModel):
    enrolled: int
    skipped: list[EnrolSkipped]


class EnrolmentOut(BaseModel):
    id: uuid.UUID
    sequence_id: uuid.UUID
    sequence_name: str
    lead_id: uuid.UUID
    lead_name: str | None = None
    status: str
    position: int
    steps: int
    next_run_at: datetime | None
    ended_reason: str | None
    started_at: datetime
    ended_at: datetime | None


async def _enrolments_out(db, rows: list[Enrolment]) -> list[EnrolmentOut]:
    seq_ids = {e.sequence_id for e in rows}
    names = (
        dict(
            (
                await db.execute(select(Sequence.id, Sequence.name).where(Sequence.id.in_(seq_ids)))
            ).all()
        )
        if rows
        else {}
    )
    counts = (
        dict(
            (
                await db.execute(
                    select(SequenceStep.sequence_id, func.count())
                    .where(SequenceStep.sequence_id.in_(seq_ids))
                    .group_by(SequenceStep.sequence_id)
                )
            ).all()
        )
        if rows
        else {}
    )
    leads = (
        dict(
            (
                await db.execute(
                    select(Lead.id, Lead.display_name).where(Lead.id.in_({e.lead_id for e in rows}))
                )
            ).all()
        )
        if rows
        else {}
    )
    return [
        EnrolmentOut(
            id=e.id,
            sequence_id=e.sequence_id,
            sequence_name=names.get(e.sequence_id, "—"),
            lead_id=e.lead_id,
            lead_name=leads.get(e.lead_id),
            status=e.status,
            position=e.position,
            steps=counts.get(e.sequence_id, 0),
            next_run_at=e.next_run_at,
            ended_reason=E.REASONS.get(e.ended_reason, e.ended_reason) if e.ended_reason else None,
            started_at=e.started_at,
            ended_at=e.ended_at,
        )
        for e in rows
    ]


@router.post("/sequences/{s_id}/enrol", response_model=EnrolOut)
async def enrol(s_id: uuid.UUID, body: EnrolIn, db: CrmDb, actor: Editor) -> EnrolOut:
    """Put leads you can see into the sequence. Each one that can't go in says why."""
    s = await _sequence(db, s_id)
    visible = await L.visibility_filter(db, actor)
    leads = {
        lead.id: lead
        for lead in (
            await db.scalars(select(Lead).where(Lead.id.in_(body.lead_ids), visible))
        ).all()
    }
    done, skipped = 0, []
    for lead_id in dict.fromkeys(body.lead_ids):
        lead = leads.get(lead_id)
        if lead is None:
            skipped.append(EnrolSkipped(lead_id=lead_id, name=None, reason="not found"))
            continue
        out = await E.enrol(db, actor, s, lead)
        if isinstance(out, str):
            skipped.append(EnrolSkipped(lead_id=lead.id, name=lead.display_name, reason=out))
        else:
            done += 1
    await db.flush()
    return EnrolOut(enrolled=done, skipped=skipped)


@router.get("/sequences/{s_id}/enrolments", response_model=list[EnrolmentOut])
async def sequence_enrolments(
    s_id: uuid.UUID,
    db: CrmDb,
    actor: ActiveUser,
    status_: Annotated[
        Literal["active", "completed", "stopped"] | None, Query(alias="status")
    ] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[EnrolmentOut]:
    await _sequence(db, s_id)
    q = (
        select(Enrolment)
        .join(Lead, Lead.id == Enrolment.lead_id)
        .where(Enrolment.sequence_id == s_id, await L.visibility_filter(db, actor))
    )
    if status_:
        q = q.where(Enrolment.status == status_)
    rows = (await db.scalars(q.order_by(Enrolment.started_at.desc()).limit(limit))).all()
    return await _enrolments_out(db, list(rows))


@router.get("/leads/{lead_id}/sequences", response_model=list[EnrolmentOut])
async def lead_enrolments(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> list[EnrolmentOut]:
    lead = await L.get_visible(db, actor, lead_id)
    rows = (
        await db.scalars(
            select(Enrolment)
            .where(Enrolment.lead_id == lead.id)
            .order_by(Enrolment.started_at.desc())
        )
    ).all()
    return await _enrolments_out(db, list(rows))


@router.post("/enrolments/{e_id}/stop", response_model=EnrolmentOut)
async def stop_enrolment(e_id: uuid.UUID, db: CrmDb, actor: Editor) -> EnrolmentOut:
    e = await db.get(Enrolment, e_id)
    if e is None:
        raise NotFound("Not found")
    await L.get_visible(db, actor, e.lead_id)
    await E.end(db, e, "stopped", "manual", actor)
    await db.flush()
    return (await _enrolments_out(db, [e]))[0]


# ---------- results ----------
class StepStats(BaseModel):
    position: int
    kind: str
    sent: int = 0
    delivered: int = 0
    opened: int = 0
    clicked: int = 0
    replied: int = 0
    bounced: int = 0
    unsubscribed: int = 0


class SequenceStats(BaseModel):
    enrolled: int
    active: int
    completed: int
    stopped: int
    got_a_deal: int
    became_customers: int
    steps: list[StepStats]


@router.get("/sequences/{s_id}/stats", response_model=SequenceStats)
async def sequence_stats(s_id: uuid.UUID, db: CrmDb, actor: Manager) -> SequenceStats:
    s = await _sequence(db, s_id)
    by_status = dict(
        (
            await db.execute(
                select(Enrolment.status, func.count())
                .where(Enrolment.sequence_id == s.id)
                .group_by(Enrolment.status)
            )
        ).all()
    )
    deal = (
        select(Deal.id)
        .where(Deal.lead_id == Enrolment.lead_id, Deal.created_at >= Enrolment.started_at)
        .exists()
    )
    cust = (
        select(Customer.id)
        .where(Customer.lead_id == Enrolment.lead_id, Customer.since >= Enrolment.started_at)
        .exists()
    )
    got_deal, became = (
        await db.execute(
            select(func.count().filter(deal), func.count().filter(cust)).where(
                Enrolment.sequence_id == s.id
            )
        )
    ).one()
    steps = (
        await db.scalars(
            select(SequenceStep)
            .where(SequenceStep.sequence_id == s.id)
            .order_by(SequenceStep.position)
        )
    ).all()
    rows = {
        r.step_id: r
        for r in (
            await db.execute(
                select(
                    Message.step_id,
                    func.count().filter(Message.sent_at.isnot(None)).label("sent"),
                    func.count().filter(Message.status == "delivered").label("delivered"),
                    func.count().filter(Message.opened_at.isnot(None)).label("opened"),
                    func.count().filter(Message.clicked_at.isnot(None)).label("clicked"),
                    func.count().filter(Message.replied_at.isnot(None)).label("replied"),
                    func.count().filter(Message.bounced_at.isnot(None)).label("bounced"),
                    func.count().filter(Message.unsubscribed_at.isnot(None)).label("unsubscribed"),
                )
                .join(Enrolment, Enrolment.id == Message.enrolment_id)
                .where(Enrolment.sequence_id == s.id)
                .group_by(Message.step_id)
            )
        ).all()
    }
    out = []
    for st in steps:
        r = rows.get(st.id)
        out.append(
            StepStats(
                position=st.position,
                kind=st.kind,
                **(
                    {
                        k: getattr(r, k)
                        for k in (
                            "sent",
                            "delivered",
                            "opened",
                            "clicked",
                            "replied",
                            "bounced",
                            "unsubscribed",
                        )
                    }
                    if r
                    else {}
                ),
            )
        )
    return SequenceStats(
        enrolled=sum(by_status.values()),
        active=by_status.get("active", 0),
        completed=by_status.get("completed", 0),
        stopped=by_status.get("stopped", 0),
        got_a_deal=got_deal,
        became_customers=became,
        steps=out,
    )


# ---------- sending settings ----------
class SendingSettings(BaseModel):
    from_: str = Field(alias="from", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    to: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$")
    days: list[int] = Field(min_length=1, max_length=7)
    daily_cap: int = Field(ge=1, le=100000)
    model_config = {"populate_by_name": True}


@router.get("/engage/settings", response_model=SendingSettings, response_model_by_alias=True)
async def get_sending(db: CrmDb, actor: Manager) -> SendingSettings:
    s = await db.get(TenantSettings, actor.user.tenant_id)
    return SendingSettings.model_validate(s.engage)


@router.put("/engage/settings", response_model=SendingSettings, response_model_by_alias=True)
async def set_sending(body: SendingSettings, db: CrmDb, actor: Manager) -> SendingSettings:
    if any(d not in range(7) for d in body.days):
        raise Invalid("Days are 0 (Monday) to 6 (Sunday)")
    if body.to <= body.from_:
        raise Invalid("Sending must end after it starts")
    s = await db.get(TenantSettings, actor.user.tenant_id)
    before = dict(s.engage or {})
    s.engage = body.model_dump(by_alias=True) | {"days": sorted(set(body.days))}
    await audit(db, actor, "engage.settings_updated", "settings", None, before, s.engage)
    return SendingSettings.model_validate(s.engage)


# ---------- public: tracking and unsubscribe (no sign-in) ----------
PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


async def _by_token(db, token: str) -> Message | None:
    if len(token) > 48:
        return None
    return await db.scalar(select(Message).where(Message.token == token))


@public.get("/t/o/{token}.gif")
async def track_open(token: str, db: CrmDb) -> Response:
    msg = await _by_token(db, token)
    if msg is not None:
        await E.record_open(db, msg)
    return Response(PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@public.get("/t/c/{token}/{index}")
async def track_click(token: str, index: int, db: CrmDb) -> Response:
    """Only ever redirects to a link that was in the email (never an open redirect)."""
    msg = await _by_token(db, token)
    url = await E.record_click(db, msg, index) if msg is not None else None
    if url is None:
        return HTMLResponse("<p>This link has expired.</p>", status_code=404)
    return RedirectResponse(url, status_code=302)


def _page(title: str, text: str, form: bool = False, token: str = "") -> HTMLResponse:
    button = (
        f'<form method="post" action="/api/v1/u/{token}"><button type="submit" '
        'style="padding:8px 16px;font-size:14px">Unsubscribe</button></form>'
        if form
        else ""
    )
    return HTMLResponse(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{title}</title><div style="font-family:Arial,sans-serif;max-width:480px;'
        f'margin:60px auto;padding:0 16px"><h2>{title}</h2><p>{text}</p>{button}</div>'
    )


@public.get("/u/{token}")
async def unsubscribe_page(token: str, db: CrmDb) -> HTMLResponse:
    """Shows a button (link scanners open links; only the button unsubscribes)."""
    msg = await _by_token(db, token)
    if msg is None:
        return _page("Link expired", "This unsubscribe link is no longer valid.")
    if msg.unsubscribed_at:
        return _page("You're unsubscribed", "You won't get these emails any more.")
    return _page("Unsubscribe", "Stop getting these emails?", form=True, token=token)


@public.post("/u/{token}")
async def unsubscribe(token: str, db: CrmDb) -> HTMLResponse:
    """The button, and mail apps' one-click unsubscribe (RFC 8058)."""
    msg = await _by_token(db, token)
    if msg is None:
        return _page("Link expired", "This unsubscribe link is no longer valid.")
    await E.unsubscribe(db, msg)
    return _page("You're unsubscribed", "You won't get these emails any more.")

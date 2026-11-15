"""Outreach routes (step O2): campaigns, their contacts and steps, results, the outreach inbox,
contacts and Convert to lead. Behind the `outreach` module switch (off until Versnq staff turn
it on). campaigns.manage: build and run campaigns (sees every campaign); outreach.reply: the
replies of the campaigns one may see (all with campaigns.manage, otherwise one's own)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import Invalid, NotFound
from app.core.modules import require_module
from app.modules.auth.deps import CurrentUser, has_permission, require
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.imports import read_csv
from app.modules.engage import render as R
from app.modules.engage.models import Conversation, Mailbox, Message
from app.modules.outreach import service as O
from app.modules.outreach.models import Campaign, CampaignContact, CampaignStep, Contact
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User

router = APIRouter(
    prefix="/api/v1", tags=["outreach"], dependencies=[*CRM, require_module("outreach")]
)
Manager = Annotated[CurrentUser, require("campaigns.manage")]
Replier = Annotated[CurrentUser, require("outreach.reply")]
HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$|^24:00$"


# ---------- shapes ----------
class CampaignSchedule(BaseModel):
    timezone: str | None = Field(default=None, max_length=60)
    days: list[int] = Field(default=[0, 1, 2, 3, 4], max_length=7)
    from_: str = Field(default="09:00", alias="from", pattern=HHMM)
    to: str = Field(default="18:00", pattern=HHMM)

    model_config = {"populate_by_name": True}


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    owner_user_id: uuid.UUID | None = None
    mailbox_ids: list[uuid.UUID] = Field(default=[], max_length=500)
    schedule: CampaignSchedule | None = None
    daily_cap: int = Field(default=500, ge=1, le=100000)
    track_opens: bool = False
    track_clicks: bool = False


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    owner_user_id: uuid.UUID | None = None
    mailbox_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    schedule: CampaignSchedule | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=100000)
    track_opens: bool | None = None
    track_clicks: bool | None = None


class CampaignCounts(BaseModel):
    contacts: int = 0
    active: int = 0
    sent: int = 0
    opened: int = 0
    clicked: int = 0
    replied: int = 0
    bounced: int = 0
    unsubscribed: int = 0


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    owner_user_id: uuid.UUID | None
    owner_name: str | None
    mailbox_ids: list[uuid.UUID]
    schedule: dict
    daily_cap: int
    track_opens: bool
    track_clicks: bool
    launched_at: datetime | None
    created_at: datetime
    counts: CampaignCounts


class CampaignVariant(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class CampaignStepIn(BaseModel):
    wait_days: int = Field(default=0, ge=0, le=365)
    variants: list[CampaignVariant] = Field(min_length=1, max_length=O.MAX_VARIANTS)


class CampaignStepsIn(BaseModel):
    steps: list[CampaignStepIn] = Field(min_length=1, max_length=O.MAX_STEPS)


class CampaignStepOut(CampaignStepIn):
    id: uuid.UUID
    position: int


class ContactImportIn(BaseModel):
    csv: str = Field(min_length=1, max_length=20_000_000)
    mapping: dict[str, Literal[
        "email", "first_name", "last_name", "company", "title", "phone", "website",
        "variable", "ignore",
    ]] | None = None  # fmt: skip
    filename: str | None = Field(default=None, max_length=200)
    dry_run: bool = False


class ContactImportOut(BaseModel):
    rows: int
    added: int
    duplicates_in_file: int
    invalid_email: int
    already_lead: int
    suppressed: int
    already_in_campaign: int
    variables: list[str]
    problems: list[dict]
    mapping: dict[str, str]


class ContactOut(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str | None
    last_name: str | None
    company: str | None
    title: str | None
    phone: str | None
    website: str | None
    variables: dict
    status: str
    lead_id: uuid.UUID | None
    campaign_ids: list[uuid.UUID] = []


class CampaignContactOut(BaseModel):
    contact: ContactOut
    status: str
    position: int
    variant: int
    next_run_at: datetime | None
    ended_reason: str | None
    mailbox_id: uuid.UUID | None
    last_sent_at: datetime | None


class CampaignPreviewIn(BaseModel):
    position: int = Field(default=1, ge=1)
    variant: int = Field(default=0, ge=0)
    contact_id: uuid.UUID | None = None


class CampaignPreviewOut(BaseModel):
    subject: str
    body: str
    missing: list[str]


class CampaignStatRow(BaseModel):
    """One step, or one version of a step, or one inbox, in the results."""

    key: str
    label: str
    sent: int = 0
    opened: int = 0
    clicked: int = 0
    replied: int = 0
    bounced: int = 0
    unsubscribed: int = 0


class CampaignStatsOut(BaseModel):
    totals: CampaignCounts
    steps: list[CampaignStatRow]
    variants: list[CampaignStatRow]
    inboxes: list[CampaignStatRow]


class OutreachMessage(BaseModel):
    id: uuid.UUID
    direction: str
    from_address: str | None
    to_address: str
    subject: str | None
    body: str
    status: str
    sent_at: datetime | None
    auto_submitted: bool
    mailbox_id: uuid.UUID | None


class OutreachConversation(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID | None
    campaign_name: str | None
    contact: ContactOut
    subject: str | None
    last_message_at: datetime | None
    last_direction: str | None
    state: str  # new / replied / converted / not_interested / waiting
    assignee_user_id: uuid.UUID | None


class OutreachDetail(OutreachConversation):
    messages: list[OutreachMessage]


class OutreachReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=50000)


# ---------- helpers ----------
def _contact_out(c: Contact, campaign_ids: list[uuid.UUID] | None = None) -> ContactOut:
    return ContactOut(
        id=c.id, email=c.email, first_name=c.first_name, last_name=c.last_name,
        company=c.company, title=c.title, phone=c.phone, website=c.website,
        variables=c.variables or {}, status=c.status, lead_id=c.lead_id,
        campaign_ids=campaign_ids or [],
    )  # fmt: skip


async def _counts(db, campaign_ids: list[uuid.UUID]) -> dict[uuid.UUID, CampaignCounts]:
    out = {i: CampaignCounts() for i in campaign_ids}
    if not campaign_ids:
        return out
    rows = await db.execute(
        select(CampaignContact.campaign_id, CampaignContact.status, func.count())
        .where(CampaignContact.campaign_id.in_(campaign_ids))
        .group_by(CampaignContact.campaign_id, CampaignContact.status)
    )
    for cid, st, n in rows.all():
        out[cid].contacts += n
        if st in O.OPEN:
            out[cid].active += n
    rows = await db.execute(
        select(
            Message.campaign_id,
            func.count(Message.sent_at),
            func.count(Message.opened_at),
            func.count(Message.clicked_at),
            func.count(Message.replied_at),
            func.count(Message.bounced_at),
            func.count(Message.unsubscribed_at),
        )
        .where(Message.campaign_id.in_(campaign_ids), Message.direction == "out")
        .group_by(Message.campaign_id)
    )
    for cid, sent, opened, clicked, replied, bounced, unsub in rows.all():
        c = out[cid]
        c.sent, c.opened, c.clicked = sent, opened, clicked
        c.replied, c.bounced, c.unsubscribed = replied, bounced, unsub
    return out


async def _out(db, campaigns: list[Campaign]) -> list[CampaignOut]:
    counts = await _counts(db, [c.id for c in campaigns])
    owners = {c.owner_user_id for c in campaigns if c.owner_user_id}
    names = (
        dict((await db.execute(select(User.id, User.name).where(User.id.in_(owners)))).all())
        if owners
        else {}
    )
    return [
        CampaignOut(
            id=c.id,
            name=c.name,
            description=c.description,
            status=c.status,
            owner_user_id=c.owner_user_id,
            owner_name=names.get(c.owner_user_id),
            mailbox_ids=[uuid.UUID(i) for i in c.mailbox_ids or []],
            schedule=c.schedule or {},
            daily_cap=c.daily_cap,
            track_opens=c.track_opens,
            track_clicks=c.track_clicks,
            launched_at=c.launched_at,
            created_at=c.created_at,
            counts=counts[c.id],
        )  # fmt: skip
        for c in campaigns
    ]


async def _check_refs(db, owner_user_id: uuid.UUID | None, mailbox_ids: list[uuid.UUID]) -> None:
    if owner_user_id and not await db.scalar(
        select(User.id).where(User.id == owner_user_id, User.status == "active")
    ):
        raise Invalid("The owner must be an active member of the team")
    if mailbox_ids:
        found = await db.scalar(
            select(func.count())
            .select_from(Mailbox)
            .where(Mailbox.id.in_(mailbox_ids), Mailbox.in_pool)
        )
        if found != len(set(mailbox_ids)):
            raise Invalid("Choose inboxes from the sending inboxes", code="mailbox_not_in_pool")


def _schedule(s: CampaignSchedule | None, tz: str) -> dict:
    s = s or CampaignSchedule()
    if not s.days or any(d not in range(7) for d in s.days):
        raise Invalid("Choose at least one sending day")
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(s.timezone or tz)
    except (KeyError, ValueError):
        raise Invalid(f"Unknown time zone {s.timezone}") from None
    return {"timezone": s.timezone or tz, "days": sorted(set(s.days)), "from": s.from_, "to": s.to}


def _editable(c: Campaign) -> None:
    if c.status == "finished":
        raise Invalid("This campaign has finished", code="campaign_finished")


# ---------- campaigns ----------
@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(db: CrmDb, actor: Replier) -> list[CampaignOut]:
    rows = (
        await db.scalars(
            select(Campaign).where(O.campaign_filter(actor)).order_by(Campaign.created_at.desc())
        )
    ).all()
    return await _out(db, list(rows))


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(body: CampaignIn, db: CrmDb, actor: Manager) -> CampaignOut:
    await _check_refs(db, body.owner_user_id, body.mailbox_ids)
    settings = await db.get(TenantSettings, actor.user.tenant_id)
    c = Campaign(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        name=body.name.strip(),
        description=body.description,
        status="draft",
        owner_user_id=body.owner_user_id or actor.user.id,
        mailbox_ids=[str(i) for i in body.mailbox_ids],
        schedule=_schedule(body.schedule, settings.timezone),
        daily_cap=body.daily_cap,
        track_opens=body.track_opens,
        track_clicks=body.track_clicks,
        created_by_user_id=actor.user.id,
    )
    db.add(c)
    await db.flush()
    await audit(db, actor, "campaign.created", "campaign", c.id, None, {"name": c.name})
    return (await _out(db, [c]))[0]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: uuid.UUID, db: CrmDb, actor: Replier) -> CampaignOut:
    return (await _out(db, [await O.get_campaign(db, actor, campaign_id)]))[0]


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID, body: CampaignPatch, db: CrmDb, actor: Manager
) -> CampaignOut:
    c = await O.get_campaign(db, actor, campaign_id)
    _editable(c)
    data = body.model_dump(exclude_unset=True)
    await _check_refs(db, data.get("owner_user_id"), data.get("mailbox_ids") or [])
    if "schedule" in data:
        settings = await db.get(TenantSettings, actor.user.tenant_id)
        c.schedule = _schedule(body.schedule, settings.timezone)
    for key in ("name", "description", "owner_user_id", "daily_cap", "track_opens",
                "track_clicks"):  # fmt: skip
        if key in data and (data[key] is not None or key == "description"):
            setattr(c, key, data[key].strip() if key == "name" else data[key])
    if data.get("mailbox_ids") is not None:
        c.mailbox_ids = [str(i) for i in data["mailbox_ids"]]
    await audit(db, actor, "campaign.updated", "campaign", c.id, None,
                {k: str(v) for k, v in data.items() if k != "description"})  # fmt: skip
    return (await _out(db, [c]))[0]


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: uuid.UUID, db: CrmDb, actor: Manager) -> None:
    c = await O.get_campaign(db, actor, campaign_id)
    if c.status != "draft":
        raise Invalid("Only a draft can be deleted; pause it instead", code="campaign_not_draft")
    await audit(db, actor, "campaign.deleted", "campaign", c.id, {"name": c.name}, None)
    await db.delete(c)


@router.post("/campaigns/{campaign_id}/launch", response_model=CampaignOut)
async def launch(campaign_id: uuid.UUID, db: CrmDb, actor: Manager) -> CampaignOut:
    c = await O.get_campaign(db, actor, campaign_id)
    if c.status != "draft":
        raise Invalid("This campaign was already launched", code="campaign_not_draft")
    problems = await O.launch_problems(db, c)
    if problems:
        raise Invalid(problems[0], {"problems": problems}, code="campaign_not_ready")
    now = L.now()
    pending = (
        await db.scalars(
            select(CampaignContact)
            .where(CampaignContact.campaign_id == c.id, CampaignContact.status == "pending")
            .order_by(CampaignContact.created_at, CampaignContact.id)
        )
    ).all()
    for i, cc in enumerate(pending):  # split evenly across the versions
        cc.status, cc.next_run_at, cc.variant = "active", now, i
    c.status, c.launched_at = "running", now
    await audit(db, actor, "campaign.launched", "campaign", c.id, None, {"contacts": len(pending)})
    return (await _out(db, [c]))[0]


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignOut)
async def pause(campaign_id: uuid.UUID, db: CrmDb, actor: Manager) -> CampaignOut:
    c = await O.get_campaign(db, actor, campaign_id)
    if c.status != "running":
        raise Invalid("Only a running campaign can be paused", code="campaign_not_running")
    c.status = "paused"
    await audit(db, actor, "campaign.paused", "campaign", c.id, None, None)
    return (await _out(db, [c]))[0]


@router.post("/campaigns/{campaign_id}/resume", response_model=CampaignOut)
async def resume(campaign_id: uuid.UUID, db: CrmDb, actor: Manager) -> CampaignOut:
    c = await O.get_campaign(db, actor, campaign_id)
    if c.status != "paused":
        raise Invalid("Only a paused campaign can be resumed", code="campaign_not_paused")
    c.status = "running"
    await audit(db, actor, "campaign.resumed", "campaign", c.id, None, None)
    return (await _out(db, [c]))[0]


# ---------- steps ----------
async def _steps(db, campaign_id: uuid.UUID) -> list[CampaignStep]:
    return list(
        (
            await db.scalars(
                select(CampaignStep)
                .where(CampaignStep.campaign_id == campaign_id)
                .order_by(CampaignStep.position)
            )
        ).all()
    )


def _step_out(s: CampaignStep) -> CampaignStepOut:
    return CampaignStepOut(id=s.id, position=s.position, wait_days=s.wait_days,
                   variants=[CampaignVariant(**v) for v in s.variants])  # fmt: skip


@router.get("/campaigns/{campaign_id}/steps", response_model=list[CampaignStepOut])
async def get_steps(campaign_id: uuid.UUID, db: CrmDb, actor: Replier) -> list[CampaignStepOut]:
    await O.get_campaign(db, actor, campaign_id)
    return [_step_out(s) for s in await _steps(db, campaign_id)]


@router.put("/campaigns/{campaign_id}/steps", response_model=list[CampaignStepOut])
async def put_steps(
    campaign_id: uuid.UUID, body: CampaignStepsIn, db: CrmDb, actor: Manager
) -> list[CampaignStepOut]:
    """The whole sequence at once. Once launched, steps can be edited and added, not removed
    (people are part-way through them)."""
    c = await O.get_campaign(db, actor, campaign_id)
    _editable(c)
    raw = [s.model_dump() for s in body.steps]
    O.check_steps(raw)
    existing = await _steps(db, c.id)
    if c.status != "draft" and len(raw) < len(existing):
        raise Invalid("After launch, steps can be changed or added, not removed")
    for n, s in enumerate(raw, 1):
        variants = [{"subject": (v["subject"] or "").strip() or None, "body": v["body"]}
                    for v in s["variants"]]  # fmt: skip
        if n <= len(existing):
            existing[n - 1].wait_days, existing[n - 1].variants = s["wait_days"], variants
        else:
            db.add(CampaignStep(tenant_id=c.tenant_id, campaign_id=c.id, position=n,
                                wait_days=s["wait_days"], variants=variants))  # fmt: skip
    for extra in existing[len(raw) :]:
        await db.delete(extra)
    await db.flush()
    await audit(db, actor, "campaign.steps_saved", "campaign", c.id, None, {"steps": len(raw)})
    return [_step_out(s) for s in await _steps(db, c.id)]


@router.post("/campaigns/{campaign_id}/preview", response_model=CampaignPreviewOut)
async def preview(
    campaign_id: uuid.UUID, body: CampaignPreviewIn, db: CrmDb, actor: Replier
) -> CampaignPreviewOut:
    c = await O.get_campaign(db, actor, campaign_id)
    step = next((s for s in await _steps(db, c.id) if s.position == body.position), None)
    if step is None:
        raise NotFound("Step not found")
    variant = step.variants[body.variant % len(step.variants)]
    contact = None
    if body.contact_id:
        contact = await db.scalar(
            select(Contact)
            .join(CampaignContact, CampaignContact.contact_id == Contact.id)
            .where(Contact.id == body.contact_id, CampaignContact.campaign_id == c.id)
        )
    if contact is None:
        contact = await db.scalar(
            select(Contact)
            .join(CampaignContact, CampaignContact.contact_id == Contact.id)
            .where(CampaignContact.campaign_id == c.id)
            .order_by(CampaignContact.created_at)
            .limit(1)
        )
    from app.platform.models import Tenant

    tenant = await db.get(Tenant, c.tenant_id)
    values = O.values_for(contact, actor.user.name, tenant.name) if contact else {}
    missing = sorted({
        name for text in (variant.get("subject") or "", variant["body"])
        for name, fb in R.VAR.findall(text) if not fb.strip() and not values.get(name)
    })  # fmt: skip
    return CampaignPreviewOut(
        subject=R.fill(variant.get("subject") or "", values) or "(replies in the same thread)",
        body=R.fill(variant["body"], values),
        missing=missing,
    )


# ---------- contacts in a campaign ----------
@router.post("/campaigns/{campaign_id}/contacts/import", response_model=ContactImportOut)
async def import_contacts(
    campaign_id: uuid.UUID, body: ContactImportIn, db: CrmDb, actor: Manager
) -> ContactImportOut:
    c = await O.get_campaign(db, actor, campaign_id)
    _editable(c)
    header, _ = read_csv(body.csv)
    mapping = {**O.guess_mapping(header), **(body.mapping or {})}
    report = await O.import_contacts(
        db, actor, c, body.csv, mapping, dry_run=body.dry_run,
        source=f"import of {body.filename or 'a CSV file'} ({c.name})",
    )  # fmt: skip
    if not body.dry_run:
        await audit(db, actor, "campaign.contacts_imported", "campaign", c.id, None,
                    {"added": report.added, "rows": report.rows})  # fmt: skip
    return ContactImportOut(**report.__dict__, mapping=mapping)


@router.get("/campaigns/{campaign_id}/contacts", response_model=list[CampaignContactOut])
async def campaign_contacts(
    campaign_id: uuid.UUID,
    db: CrmDb,
    actor: Replier,
    status_: Annotated[str | None, Query(alias="status", max_length=12)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CampaignContactOut]:
    c = await O.get_campaign(db, actor, campaign_id)
    query = (
        select(CampaignContact, Contact)
        .join(Contact, Contact.id == CampaignContact.contact_id)
        .where(CampaignContact.campaign_id == c.id)
    )
    if status_:
        query = query.where(CampaignContact.status == status_)
    if q:
        term = f"%{q.strip()}%"
        query = query.where(
            Contact.email.ilike(term) | Contact.first_name.ilike(term)
            | Contact.last_name.ilike(term) | Contact.company.ilike(term)
        )  # fmt: skip
    rows = (
        await db.execute(query.order_by(CampaignContact.created_at).offset(offset).limit(limit))
    ).all()
    return [
        CampaignContactOut(
            contact=_contact_out(ct),
            status=cc.status,
            position=cc.position,
            variant=cc.variant,
            next_run_at=cc.next_run_at,
            ended_reason=cc.ended_reason,
            mailbox_id=cc.mailbox_id,
            last_sent_at=cc.last_sent_at,
        )  # fmt: skip
        for cc, ct in rows
    ]


@router.post(
    "/campaigns/{campaign_id}/contacts/{contact_id}/stop", response_model=CampaignContactOut
)
async def stop_contact(
    campaign_id: uuid.UUID, contact_id: uuid.UUID, db: CrmDb, actor: Replier
) -> CampaignContactOut:
    """Not interested: this person gets nothing more from this campaign."""
    c = await O.get_campaign(db, actor, campaign_id)
    cc = await db.scalar(
        select(CampaignContact).where(
            CampaignContact.campaign_id == c.id, CampaignContact.contact_id == contact_id
        )
    )
    if cc is None:
        raise NotFound("Contact not found in this campaign")
    if cc.status in O.OPEN or cc.status == "replied":
        cc.status, cc.ended_reason, cc.next_run_at = "stopped", "not_interested", None
    await audit(db, actor, "campaign.contact_stopped", "contact", contact_id, None,
                {"campaign_id": str(c.id)})  # fmt: skip
    ct = await db.get(Contact, contact_id)
    return CampaignContactOut(
        contact=_contact_out(ct), status=cc.status, position=cc.position, variant=cc.variant,
        next_run_at=cc.next_run_at, ended_reason=cc.ended_reason, mailbox_id=cc.mailbox_id,
        last_sent_at=cc.last_sent_at,
    )  # fmt: skip


# ---------- results ----------
def _row(key, label, sent, opened, clicked, replied, bounced, unsub) -> CampaignStatRow:
    return CampaignStatRow(key=str(key), label=label, sent=sent, opened=opened, clicked=clicked,
               replied=replied, bounced=bounced, unsubscribed=unsub)  # fmt: skip


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStatsOut)
async def stats(campaign_id: uuid.UUID, db: CrmDb, actor: Replier) -> CampaignStatsOut:
    c = await O.get_campaign(db, actor, campaign_id)
    steps = {s.id: s for s in await _steps(db, c.id)}
    cols = (
        func.count(Message.sent_at), func.count(Message.opened_at),
        func.count(Message.clicked_at), func.count(Message.replied_at),
        func.count(Message.bounced_at), func.count(Message.unsubscribed_at),
    )  # fmt: skip
    base = select().where(Message.campaign_id == c.id, Message.direction == "out")
    by_step = (await db.execute(
        base.add_columns(Message.campaign_step_id, *cols).group_by(Message.campaign_step_id)
    )).all()  # fmt: skip
    by_variant = (await db.execute(
        base.add_columns(Message.campaign_step_id, Message.variant, *cols)
        .group_by(Message.campaign_step_id, Message.variant)
    )).all()  # fmt: skip
    by_inbox = (await db.execute(
        base.add_columns(Message.mailbox_id, *cols).group_by(Message.mailbox_id)
    )).all()  # fmt: skip
    boxes = dict((await db.execute(select(Mailbox.id, Mailbox.email_address))).all())

    def pos(step_id):
        return steps[step_id].position if step_id in steps else 0

    return CampaignStatsOut(
        totals=(await _counts(db, [c.id]))[c.id],
        steps=[_row(pos(sid), f"Step {pos(sid)}", *n)
               for sid, *n in sorted(by_step, key=lambda r: pos(r[0]))],
        variants=[_row(f"{pos(sid)}.{v}", f"Step {pos(sid)} · {chr(65 + (v or 0))}", *n)
                  for sid, v, *n in sorted(by_variant, key=lambda r: (pos(r[0]), r[1] or 0))],
        inboxes=[_row(mid, boxes.get(mid, "removed inbox"), *n) for mid, *n in by_inbox],
    )  # fmt: skip


# ---------- contacts ----------
@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(
    db: CrmDb,
    actor: Manager,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ContactOut]:
    query = select(Contact)
    if q:
        term = f"%{q.strip()}%"
        query = query.where(Contact.email.ilike(term) | Contact.company.ilike(term))
    rows = (
        await db.scalars(query.order_by(Contact.created_at.desc()).offset(offset).limit(limit))
    ).all()
    return [_contact_out(c, await _campaign_ids(db, c.id)) for c in rows]


async def _campaign_ids(db, contact_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await db.scalars(
                select(CampaignContact.campaign_id).where(CampaignContact.contact_id == contact_id)
            )
        ).all()
    )


async def _visible_contact(db, actor: CurrentUser, contact_id: uuid.UUID) -> Contact:
    q = select(Contact).where(Contact.id == contact_id)
    if not O.sees_all(actor):
        q = q.where(
            Contact.id.in_(
                select(CampaignContact.contact_id)
                .join(Campaign, Campaign.id == CampaignContact.campaign_id)
                .where(O.campaign_filter(actor))
            )
        )
    contact = await db.scalar(q)
    if contact is None:
        raise NotFound("Contact not found")
    return contact


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: uuid.UUID, db: CrmDb, actor: Replier) -> ContactOut:
    c = await _visible_contact(db, actor, contact_id)
    return _contact_out(c, await _campaign_ids(db, c.id))


class ContactConvertOut(BaseModel):
    lead_id: uuid.UUID


@router.post("/contacts/{contact_id}/convert", response_model=ContactConvertOut)
async def convert(contact_id: uuid.UUID, db: CrmDb, actor: Replier) -> ContactConvertOut:
    contact = await _visible_contact(db, actor, contact_id)
    if not has_permission(actor.permissions, "leads.create"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied")
    lead = await O.convert(db, actor, contact)
    await audit(db, actor, "contact.converted", "contact", contact.id, None,
                {"lead_id": str(lead.id)})  # fmt: skip
    return ContactConvertOut(lead_id=lead.id)


@router.post("/contacts/{contact_id}/unsubscribe", response_model=ContactOut)
async def unsubscribe(contact_id: uuid.UUID, db: CrmDb, actor: Replier) -> ContactOut:
    contact = await _visible_contact(db, actor, contact_id)
    await O.unsubscribe(db, contact)
    await audit(db, actor, "contact.unsubscribed", "contact", contact.id, None, None)
    return _contact_out(contact, await _campaign_ids(db, contact.id))


# ---------- the outreach inbox ----------
async def _state(db, conv: Conversation, contact: Contact) -> str:
    if contact.status == "converted":
        return "converted"
    cc = await db.scalar(
        select(CampaignContact).where(
            CampaignContact.campaign_id == conv.campaign_id,
            CampaignContact.contact_id == contact.id,
        )
    )
    if cc is not None and cc.ended_reason == "not_interested":
        return "not_interested"
    if conv.last_direction == "in":
        return "new"
    return "replied" if conv.last_inbound_at else "waiting"


async def _conv_out(db, conv: Conversation, names: dict) -> OutreachConversation:
    contact = await db.get(Contact, conv.contact_id)
    return OutreachConversation(
        id=conv.id, campaign_id=conv.campaign_id, campaign_name=names.get(conv.campaign_id),
        contact=_contact_out(contact), subject=conv.subject, last_message_at=conv.last_message_at,
        last_direction=conv.last_direction, state=await _state(db, conv, contact),
        assignee_user_id=conv.assignee_user_id,
    )  # fmt: skip


async def _outreach_conv(db, actor: CurrentUser, conv_id: uuid.UUID) -> Conversation:
    conv = await db.scalar(
        select(Conversation).where(Conversation.id == conv_id, O.conversation_filter(actor))
    )
    if conv is None:
        raise NotFound("Conversation not found")
    return conv


@router.get("/outreach/conversations", response_model=list[OutreachConversation])
async def outreach_inbox(
    db: CrmDb,
    actor: Replier,
    campaign_id: uuid.UUID | None = None,
    mailbox_id: uuid.UUID | None = None,
    state: Annotated[str | None, Query(max_length=20)] = None,
    include_auto: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OutreachConversation]:
    """Every campaign reply (threads where the person wrote back), newest first."""
    replies = select(Message.conversation_id).where(Message.direction == "in")
    if not include_auto:
        replies = replies.where(Message.auto_submitted.is_(False))
    if mailbox_id:
        replies = replies.where(Message.mailbox_id == mailbox_id)
    q = select(Conversation).where(O.conversation_filter(actor), Conversation.id.in_(replies))
    if campaign_id:
        q = q.where(Conversation.campaign_id == campaign_id)
    rows = (await db.scalars(q.order_by(Conversation.last_message_at.desc().nulls_last()))).all()
    names = dict((await db.execute(select(Campaign.id, Campaign.name))).all())
    out = [await _conv_out(db, c, names) for c in rows]
    if state:
        out = [o for o in out if o.state == state]
    return out[offset : offset + limit]


async def _detail(db, conv: Conversation) -> OutreachDetail:
    names = dict((await db.execute(select(Campaign.id, Campaign.name))).all())
    base = await _conv_out(db, conv, names)
    msgs = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.sent_at.asc().nulls_last(), Message.created_at)
        )
    ).all()
    return OutreachDetail(
        **base.model_dump(),
        messages=[
            OutreachMessage(
                id=m.id,
                direction=m.direction,
                from_address=m.from_address,
                to_address=m.to_address,
                subject=m.subject,
                body=m.body,
                status=m.status,
                sent_at=m.sent_at,
                auto_submitted=m.auto_submitted,
                mailbox_id=m.mailbox_id,
            )  # fmt: skip
            for m in msgs
        ],
    )


@router.get("/outreach/conversations/{conv_id}", response_model=OutreachDetail)
async def outreach_conversation(conv_id: uuid.UUID, db: CrmDb, actor: Replier) -> OutreachDetail:
    return await _detail(db, await _outreach_conv(db, actor, conv_id))


@router.post("/outreach/conversations/{conv_id}/reply", response_model=OutreachDetail)
async def outreach_reply(
    conv_id: uuid.UUID, body: OutreachReplyIn, db: CrmDb, actor: Replier
) -> OutreachDetail:
    """Answer from the same inbox, in the same thread (no unsubscribe footer: a person's
    answer to a person)."""
    conv = await _outreach_conv(db, actor, conv_id)
    from app.modules.outreach import replying

    await replying.reply(db, actor, conv, body.body)
    return await _detail(db, conv)

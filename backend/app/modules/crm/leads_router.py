"""Leads API: list, create, view, edit, assign, delete."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, inspect, or_, select

from app.core.errors import Conflict, Forbidden, Invalid
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import CustomFieldUniqueValue, Lead, LeadIdentity
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/leads", tags=["leads"], dependencies=CRM)
Creator = Annotated[CurrentUser, require("leads.create")]
Editor = Annotated[CurrentUser, require("leads.edit")]
Assigner = Annotated[CurrentUser, require("leads.assign")]
Deleter = Annotated[CurrentUser, require("leads.delete")]

TEXT = {"max_length": 200}
ATTRIBUTION = {"campaign", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}


class IdentityIn(BaseModel):
    type: Literal["email", "phone", "linkedin"]
    value: str = Field(min_length=1, max_length=320)
    label: str | None = Field(default=None, max_length=40)
    is_primary: bool = False
    is_whatsapp: bool = False


class IdentityOut(BaseModel):
    model_config = {"from_attributes": True}
    type: str
    value: str
    value_normalized: str
    is_primary: bool
    label: str | None
    is_whatsapp: bool


class LeadFields(BaseModel):
    """Editable fields shared by create and update."""

    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    org_name: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    industry: str | None = Field(default=None, max_length=120)
    employee_range: str | None = Field(default=None, max_length=40)
    preferred_language: str | None = Field(default=None, max_length=10)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    unqualified_reason: str | None = Field(default=None, max_length=300)


class LeadIn(LeadFields):
    kind: Literal["person", "organisation"] = "person"
    identities: list[IdentityIn] = Field(min_length=1)
    source_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    assign_to_me: bool = True  # managers may untick to leave the lead unassigned
    next_follow_up_at: datetime | None = None
    custom_fields: dict = {}
    origin: Literal["inbound", "outbound_ace", "outside"] = "outside"
    campaign: str | None = Field(default=None, **TEXT)
    utm_source: str | None = Field(default=None, **TEXT)
    utm_medium: str | None = Field(default=None, **TEXT)
    utm_campaign: str | None = Field(default=None, **TEXT)
    utm_term: str | None = Field(default=None, **TEXT)
    utm_content: str | None = Field(default=None, **TEXT)


class LeadPatch(LeadFields):
    version: int  # the version you started editing from (stops silent overwrites)
    kind: Literal["person", "organisation"] | None = None
    identities: list[IdentityIn] | None = None
    source_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    next_follow_up_at: datetime | None = None
    custom_fields: dict | None = None


class LeadOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    kind: str
    display_name: str
    first_name: str | None
    last_name: str | None
    org_name: str | None
    website: str | None
    industry: str | None
    employee_range: str | None
    primary_email: str | None
    primary_phone: str | None
    identities: list[IdentityOut] = []
    owner_user_id: uuid.UUID | None
    owner_name: str | None = None
    stage_id: uuid.UUID
    stage_changed_at: datetime
    is_open: bool
    next_follow_up_at: datetime | None
    last_activity_at: datetime | None
    last_contacted_at: datetime | None
    last_disposition: str | None
    score: int
    intent: str | None
    origin: str
    source_id: uuid.UUID
    created_via: str
    campaign: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    preferred_language: str | None
    city: str | None
    region: str | None
    country_code: str | None
    custom_fields: dict
    unqualified_reason: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int


class OwnerIn(BaseModel):
    owner_user_id: uuid.UUID | None


async def _out(db, leads: list[Lead]) -> list[LeadOut]:
    for lead in leads:  # timestamps set by the database must be re-read after a save
        if inspect(lead).expired_attributes:
            await db.refresh(lead)
    ids = [lead.id for lead in leads]
    identities = await L.identities_of(db, ids)
    owner_ids = {lead.owner_user_id for lead in leads if lead.owner_user_id}
    names = {}
    if owner_ids:
        names = dict(
            (await db.execute(select(User.id, User.name).where(User.id.in_(owner_ids)))).all()
        )
    out = []
    for lead in leads:
        item = LeadOut.model_validate(lead)
        item.identities = [IdentityOut.model_validate(i) for i in identities[lead.id]]
        item.owner_name = names.get(lead.owner_user_id)
        out.append(item)
    return out


def _identities(items: list[IdentityIn]) -> list[L.IdentityInput]:
    return [L.IdentityInput(**i.model_dump()) for i in items]


def _clean(values: dict) -> dict:
    return {k: (v.strip() or None) if isinstance(v, str) else v for k, v in values.items()}


SORTS = {
    "newest": [Lead.created_at.desc()],
    "follow_up": [Lead.next_follow_up_at.asc().nulls_last(), Lead.created_at.desc()],
    "recent_activity": [Lead.last_activity_at.desc().nulls_last()],
    "name": [Lead.display_name.asc()],
}


@router.get("", response_model=LeadPage)
async def list_leads(
    db: CrmDb,
    actor: ActiveUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    stage_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    owner: Annotated[str | None, Query(description="me, unassigned or a user id")] = None,
    status_: Annotated[Literal["open", "closed"] | None, Query(alias="status")] = None,
    follow_up: Literal["overdue", "today", "none"] | None = None,
    sort: Literal["newest", "follow_up", "recent_activity", "name"] = "newest",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeadPage:
    where = [await L.visibility_filter(db, actor)]
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        digits = "".join(ch for ch in q if ch.isdigit())
        match_identity = select(LeadIdentity.lead_id).where(
            or_(
                LeadIdentity.value_normalized.like(term),
                LeadIdentity.value_normalized.like(f"%{digits}%") if len(digits) >= 4 else False,
            )
        )
        where.append(
            or_(
                func.lower(Lead.display_name).like(term),
                func.lower(Lead.org_name).like(term),
                Lead.id.in_(match_identity),
            )
        )
    if stage_id:
        where.append(Lead.stage_id == stage_id)
    if source_id:
        where.append(Lead.source_id == source_id)
    if owner == "me":
        where.append(Lead.owner_user_id == actor.user.id)
    elif owner == "unassigned":
        where.append(Lead.owner_user_id.is_(None))
    elif owner:
        try:
            where.append(Lead.owner_user_id == uuid.UUID(owner))
        except ValueError:
            raise Invalid("owner must be 'me', 'unassigned' or a user id") from None
    if status_:
        where.append(Lead.is_open.is_(status_ == "open"))
    if follow_up:
        now, end_of_day = await L.day_bounds(db, actor.user.tenant_id)
        where.append(Lead.is_open.is_(True))
        where.append(
            {
                "overdue": Lead.next_follow_up_at < now,
                "today": and_(Lead.next_follow_up_at >= now, Lead.next_follow_up_at < end_of_day),
                "none": Lead.next_follow_up_at.is_(None),
            }[follow_up]
        )
    total = await db.scalar(select(func.count()).select_from(Lead).where(*where))
    rows = await db.scalars(
        select(Lead).where(*where).order_by(*SORTS[sort]).limit(limit).offset(offset)
    )
    return LeadPage(items=await _out(db, list(rows.all())), total=total or 0)


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead(body: LeadIn, db: CrmDb, actor: Creator) -> LeadOut:
    tenant_id = actor.user.tenant_id
    if body.kind == "organisation" and not (body.org_name or "").strip():
        raise Invalid("An organisation needs a name")
    await L.check_source(db, body.source_id)
    stage = await L.get_stage(db, body.stage_id) if body.stage_id else await L.default_stage(db)

    # A rep's own new lead is theirs; people who can assign may pick an owner or none (#21).
    if L.can(actor, "leads.assign"):
        owner_id = body.owner_user_id or (actor.user.id if body.assign_to_me else None)
    else:
        if body.owner_user_id not in (None, actor.user.id):
            raise Forbidden("You can only add leads for yourself")
        owner_id = actor.user.id
    owner = await L.check_assignable(db, actor, owner_id)

    lead = Lead(
        tenant_id=tenant_id,
        kind=body.kind,
        display_name="",
        stage_id=stage.id,
        stage_changed_at=L.now(),
        is_open=stage.is_open,
        source_id=body.source_id,
        origin=body.origin,
        created_via="manual",
        owner_user_id=owner.id if owner else None,
        assigned_at=L.now() if owner else None,
        team_id=await L.owner_team(db, owner.id if owner else None),
        created_by_user_id=actor.user.id,
        custom_fields={},
        attribution={},
        **_clean(body.model_dump(include=set(LeadFields.model_fields) | ATTRIBUTION)),
    )
    db.add(lead)
    await db.flush()
    await L.set_identities(
        db, lead, _identities(body.identities), await L.tenant_country(db, tenant_id)
    )
    await L.apply_custom_fields(db, lead, body.custom_fields, creating=True)
    await L.check_stage_entry(db, lead, stage)
    if body.next_follow_up_at and stage.is_open:
        await L.set_follow_up(db, lead, body.next_follow_up_at, actor)
    await db.flush()
    await L.log(db, lead, "lead_created", f"Added by {actor.user.name}", actor)
    await L.event(db, lead, "lead.created", {"source_id": str(lead.source_id)})
    if owner:
        await L.event(db, lead, "lead.assigned", {"owner_user_id": str(owner.id)})
    return (await _out(db, [lead]))[0]


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> LeadOut:
    return (await _out(db, [await L.get_visible(db, actor, lead_id)]))[0]


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: uuid.UUID, body: LeadPatch, db: CrmDb, actor: Editor) -> LeadOut:
    lead = await L.get_visible(db, actor, lead_id)
    if body.version != lead.version:
        raise Conflict("Someone else changed this lead. Reload to see their changes")
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    changed: list[str] = []

    simple = {
        k: v for k, v in _clean(changes).items() if k in LeadFields.model_fields or k == "kind"
    }
    for key, value in simple.items():
        if getattr(lead, key) != value:
            setattr(lead, key, value)
            changed.append(key)
    if lead.kind == "organisation" and not lead.org_name:
        raise Invalid("An organisation needs a name")
    if "source_id" in changes and changes["source_id"] != lead.source_id:
        await L.check_source(db, changes["source_id"])
        lead.source_id = changes["source_id"]
        changed.append("source")
    if body.identities is not None:
        await L.set_identities(
            db, lead, _identities(body.identities), await L.tenant_country(db, lead.tenant_id)
        )
        changed.append("identities")
    else:
        lead.display_name = L.display_name(
            lead, {"email": lead.primary_email, "phone": lead.primary_phone}
        )
    if body.custom_fields is not None:
        changed += await L.apply_custom_fields(db, lead, body.custom_fields, creating=False)
    if "stage_id" in changes and changes["stage_id"]:
        await L.move_stage(db, lead, await L.get_stage(db, changes["stage_id"]), actor)
    if "next_follow_up_at" in changes:
        if changes["next_follow_up_at"] and not lead.is_open:
            raise Invalid("Closed leads have no follow-up")
        await L.set_follow_up(db, lead, changes["next_follow_up_at"], actor)
        changed.append("next follow-up")
    real_changes = [c for c in changed if c != "next follow-up"]
    if real_changes:
        await L.log(
            db,
            lead,
            "lead_updated",
            f"Changed {', '.join(real_changes)}",
            actor,
            {"fields": real_changes},
        )
        await L.event(db, lead, "lead.updated", {"fields": real_changes})
    lead.version += 1
    await db.flush()
    return (await _out(db, [lead]))[0]


@router.put("/{lead_id}/owner", response_model=LeadOut)
async def assign_lead(lead_id: uuid.UUID, body: OwnerIn, db: CrmDb, actor: Assigner) -> LeadOut:
    lead = await L.get_visible(db, actor, lead_id)
    owner = await L.check_assignable(db, actor, body.owner_user_id)
    await L.change_owner(db, lead, owner, actor)
    lead.version += 1
    await db.flush()
    return (await _out(db, [lead]))[0]


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(lead_id: uuid.UUID, db: CrmDb, actor: Deleter) -> None:
    """Permanent (Decision log #18): the lead, its timeline and tasks are gone. The audit row
    keeps only the lead's ID, no personal data."""
    lead = await L.get_visible(db, actor, lead_id)
    await db.execute(
        delete(CustomFieldUniqueValue).where(
            CustomFieldUniqueValue.entity == "lead", CustomFieldUniqueValue.record_id == lead.id
        )
    )
    await db.delete(lead)
    await db.flush()
    await audit(db, actor, "lead.deleted", "lead", lead_id)

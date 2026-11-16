"""Lead tools: duplicates and merge, consent, organisation links."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import Conflict, Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import consent as C
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm import merge as M
from app.modules.crm import orgs as O
from app.modules.crm.deps import CRM, CrmDb
from app.modules.crm.leads_router import LeadOut, _out
from app.modules.crm.models import Consent, Lead, LeadIdentity

router = APIRouter(prefix="/api/v1/leads", tags=["leads"], dependencies=CRM)
Editor = Annotated[CurrentUser, require("leads.edit")]
Merger = Annotated[CurrentUser, require("leads.merge")]


class LeadBrief(BaseModel):
    id: uuid.UUID
    display_name: str
    kind: str
    primary_email: str | None
    primary_phone: str | None
    owner_user_id: uuid.UUID | None
    stage_id: uuid.UUID
    created_at: datetime


def _brief(lead: Lead) -> LeadBrief:
    return LeadBrief(
        id=lead.id,
        display_name=lead.display_name,
        kind=lead.kind,
        primary_email=lead.primary_email,
        primary_phone=lead.primary_phone,
        owner_user_id=lead.owner_user_id,
        stage_id=lead.stage_id,
        created_at=lead.created_at,
    )


# ---------- duplicates and merge ----------
@router.get("/{lead_id}/duplicates", response_model=list[LeadBrief])
async def duplicates(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> list[LeadBrief]:
    """Other leads (that you can see) sharing a phone or email with this one."""
    lead = await L.get_visible(db, actor, lead_id)
    pairs = (
        await db.execute(
            select(LeadIdentity.type, LeadIdentity.value_normalized).where(
                LeadIdentity.lead_id == lead.id
            )
        )
    ).all()
    found = await I.find_matches(db, [tuple(p) for p in pairs], exclude=lead.id)
    if lead.possible_duplicate_of_id and all(f.id != lead.possible_duplicate_of_id for f in found):
        flagged = await db.get(Lead, lead.possible_duplicate_of_id)
        if flagged:
            found.append(flagged)
    visible = await L.visibility_filter(db, actor)
    ids = set(
        (await db.scalars(select(Lead.id).where(Lead.id.in_([f.id for f in found]), visible))).all()
    )
    return [_brief(f) for f in found if f.id in ids]


class MergeIn(BaseModel):
    survivor_id: uuid.UUID
    survivor_version: int
    other_id: uuid.UUID
    other_version: int
    # Fields where the other lead's value should win: plain field names, "source_id",
    # "owner", or "custom:<key>". Blank fields are always filled from the other lead.
    take_from_other: list[str] = Field(default=[], max_length=100)


@router.post("/merge", response_model=LeadOut)
async def merge_leads(body: MergeIn, db: CrmDb, actor: Merger) -> LeadOut:
    survivor = await L.get_visible(db, actor, body.survivor_id)
    other = await L.get_visible(db, actor, body.other_id)
    if (survivor.version, other.version) != (body.survivor_version, body.other_version):
        raise Conflict("One of these leads was changed. Reload and try again")
    lead = await M.merge(db, actor, survivor, other, body.take_from_other)
    await db.flush()
    return (await _out(db, [lead], actor))[0]


@router.get("/{lead_id}/merged-into")
async def merged_into(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> dict:
    """Old links to a merged lead: where it lives now (only if you can see it)."""
    target = await M.merged_into(db, lead_id)
    if target is None:
        raise NotFound("Lead not found")
    await L.get_visible(db, actor, target)
    return {"lead_id": str(target)}


# ---------- consent ----------
class ConsentIn(BaseModel):
    channel: Literal["email", "whatsapp", "sms"]
    status: Literal["opted_in", "opted_out"]
    wording: str | None = Field(default=None, max_length=500)


class ConsentOut(BaseModel):
    model_config = {"from_attributes": True}
    channel: str
    status: str
    source: str
    wording: str | None
    actor_user_id: uuid.UUID | None
    captured_at: datetime


@router.get("/{lead_id}/consents", response_model=list[ConsentOut])
async def consent_history(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> list[Consent]:
    lead = await L.get_visible(db, actor, lead_id)
    rows = await db.scalars(
        select(Consent)
        .where(Consent.lead_id == lead.id)
        .order_by(Consent.captured_at.desc(), Consent.id)
    )
    return list(rows.all())


@router.post("/{lead_id}/consents", response_model=LeadOut)
async def set_consent(lead_id: uuid.UUID, body: ConsentIn, db: CrmDb, actor: Editor) -> LeadOut:
    lead = await L.get_visible(db, actor, lead_id)
    await C.record(db, lead, body.channel, body.status, "manual", actor=actor, wording=body.wording)
    lead.version += 1
    await L.event(db, lead, "lead.updated", {"fields": [f"{body.channel}_consent"]})
    await db.flush()
    return (await _out(db, [lead], actor))[0]


# ---------- organisations ----------
class OrgSuggestion(BaseModel):
    id: uuid.UUID
    display_name: str
    reason: str


@router.get("/{lead_id}/organisation-suggestions", response_model=list[OrgSuggestion])
async def organisation_suggestions(
    lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser
) -> list[OrgSuggestion]:
    lead = await L.get_visible(db, actor, lead_id)
    found = await O.suggestions(db, lead, await L.visibility_filter(db, actor))
    return [
        OrgSuggestion(
            id=s.organisation.id, display_name=s.organisation.display_name, reason=s.reason
        )
        for s in found
    ]


@router.post(
    "/{lead_id}/organisation-suggestions/{org_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_suggestion(
    lead_id: uuid.UUID, org_id: uuid.UUID, db: CrmDb, actor: Editor
) -> None:
    lead = await L.get_visible(db, actor, lead_id)
    dismissed = list(lead.org_suggestions_dismissed or [])
    if str(org_id) not in dismissed:
        lead.org_suggestions_dismissed = [*dismissed, str(org_id)]


class OrganisationIn(BaseModel):
    organisation_id: uuid.UUID | None


@router.put("/{lead_id}/organisation", response_model=LeadOut)
async def set_organisation(
    lead_id: uuid.UUID, body: OrganisationIn, db: CrmDb, actor: Editor
) -> LeadOut:
    lead = await L.get_visible(db, actor, lead_id)
    org = None
    if body.organisation_id:
        if body.organisation_id == lead.id:
            raise Invalid("A lead cannot belong to itself")
        org = await L.get_visible(db, actor, body.organisation_id)
    await O.link(db, lead, org, actor)
    lead.version += 1
    await db.flush()
    return (await _out(db, [lead], actor))[0]


@router.get("/{lead_id}/people", response_model=list[LeadBrief])
async def organisation_people(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> list[LeadBrief]:
    """The people linked to an organisation (those you can see)."""
    org = await L.get_visible(db, actor, lead_id)
    rows = await db.scalars(
        select(Lead)
        .where(Lead.organisation_id == org.id, await L.visibility_filter(db, actor))
        .order_by(Lead.display_name)
        .limit(500)
    )
    return [_brief(p) for p in rows.all()]

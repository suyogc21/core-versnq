"""Leads API: list, create, view, edit, assign, delete."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, inspect, select

from app.core.errors import Conflict, Forbidden, Invalid
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import access as A
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm import tags as T
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.identities import normalize
from app.modules.crm.lead_query import LeadFilter, SortKey, ordered, where_clauses
from app.modules.crm.models import Customer, CustomFieldUniqueValue, Lead
from app.modules.settings.models import TenantSettings
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
    assign_by_rules: bool = False  # managers: let the assignment rules pick the owner
    next_follow_up_at: datetime | None = None
    custom_fields: dict = {}
    origin: Literal["inbound", "outbound_ace", "outside"] = "outside"
    campaign: str | None = Field(default=None, **TEXT)
    utm_source: str | None = Field(default=None, **TEXT)
    utm_medium: str | None = Field(default=None, **TEXT)
    utm_campaign: str | None = Field(default=None, **TEXT)
    utm_term: str | None = Field(default=None, **TEXT)
    utm_content: str | None = Field(default=None, **TEXT)
    brand_id: uuid.UUID | None = None  # several brands: None = the default brand


class LeadPatch(LeadFields):
    version: int  # the version you started editing from (stops silent overwrites)
    kind: Literal["person", "organisation"] | None = None
    identities: list[IdentityIn] | None = None
    source_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    next_follow_up_at: datetime | None = None
    custom_fields: dict | None = None
    brand_id: uuid.UUID | None = None  # move the lead (its deals and invoices follow)


class TagRef(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    colour: str | None


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
    fit_score: int = 0
    engagement_score: int = 0
    score_band: str | None = None
    tags: list[TagRef] = []
    intent: str | None
    brand_id: uuid.UUID | None = None
    ace_summary: str | None = None
    ace_next_step: str | None = None
    ace_summary_at: datetime | None = None
    erased_at: datetime | None = None  # erased on request (DPDP / GDPR)
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
    organisation_id: uuid.UUID | None
    possible_duplicate_of_id: uuid.UUID | None
    email_consent: str | None
    whatsapp_consent: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int


class OwnerIn(BaseModel):
    owner_user_id: uuid.UUID | None


async def _out(db, leads: list[Lead], actor: CurrentUser | None) -> list[LeadOut]:
    """Leads as the person may see them: hidden fields are blanked (step 8)."""
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
    tags = await T.of(db, lead_ids=ids)
    rules = await A.rules(db, actor, "lead")
    out = []
    for lead in leads:
        item = LeadOut.model_validate(lead)
        item.tags = [TagRef.model_validate(t) for t in tags.get(lead.id, [])]
        item.identities = [IdentityOut.model_validate(i) for i in identities[lead.id]]
        item.owner_name = names.get(lead.owner_user_id)
        rules.redact(item)
        out.append(item)
    return out


def _identities(items: list[IdentityIn]) -> list[L.IdentityInput]:
    return [L.IdentityInput(**i.model_dump()) for i in items]


def _clean(values: dict) -> dict:
    return {k: (v.strip() or None) if isinstance(v, str) else v for k, v in values.items()}


@router.get("", response_model=LeadPage)
async def list_leads(
    db: CrmDb,
    actor: ActiveUser,
    f: Annotated[LeadFilter, Query()],
    sort: SortKey = "created",
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeadPage:
    if sort == "city" and (await A.rules(db, actor, "lead")).hidden("city"):
        raise Invalid("You can't sort by a field you can't see")
    where = await where_clauses(db, actor, f)
    total = await db.scalar(select(func.count()).select_from(Lead).where(*where))
    query = ordered(select(Lead).where(*where), sort, direction).limit(limit).offset(offset)
    rows = await db.scalars(query)
    return LeadPage(items=await _out(db, list(rows.all()), actor), total=total or 0)


class ViewCounts(BaseModel):
    mine: int
    today: int
    overdue: int
    none: int
    unassigned: int
    all: int


@router.get("/counts", response_model=ViewCounts)
async def view_counts(db: CrmDb, actor: ActiveUser) -> ViewCounts:
    """Numbers on the view tabs (within what this person may see)."""

    async def count(**kw) -> int:
        where = await where_clauses(db, actor, LeadFilter(**kw))
        return await db.scalar(select(func.count()).select_from(Lead).where(*where)) or 0

    return ViewCounts(
        mine=await count(owner=["me"], status="open"),
        today=await count(follow_up="today"),
        overdue=await count(follow_up="overdue"),
        none=await count(follow_up="none"),
        unassigned=await count(owner=["unassigned"], status="open"),
        all=await count(),
    )


BULK_CAP = 1000
BULK_PERMISSION = {
    "assign": "leads.assign",
    "stage": "leads.edit",
    "follow_up": "leads.edit",
    "delete": "leads.delete",
    "tag": "leads.edit",
    "untag": "leads.edit",
}


class BulkIn(BaseModel):
    """Act on the ticked leads (ids) or on everything matching a filter."""

    action: Literal["assign", "stage", "follow_up", "delete", "tag", "untag"]
    ids: list[uuid.UUID] | None = Field(default=None, max_length=BULK_CAP)
    tag_ids: list[uuid.UUID] = Field(default=[], max_length=20)
    new_tags: list[str] = Field(default=[], max_length=10)  # tag: create these too
    filter: LeadFilter | None = None
    owner_user_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    unqualified_reason: str | None = Field(default=None, max_length=300)
    next_follow_up_at: datetime | None = None


class Skipped(BaseModel):
    id: uuid.UUID
    name: str
    reason: str


class BulkOut(BaseModel):
    done: int
    skipped: list[Skipped]


@router.post("/bulk", response_model=BulkOut)
async def bulk_action(body: BulkIn, db: CrmDb, actor: ActiveUser) -> BulkOut:
    """Each lead goes through the same rules as a single change; leads that fail a rule
    (e.g. a stage's required fields) are skipped and reported, the rest are done."""
    if not L.can(actor, BULK_PERMISSION[body.action]):
        raise Forbidden("permission_denied")
    if (body.ids is None) == (body.filter is None):
        raise Invalid("Send either ids or a filter")
    f = body.filter or LeadFilter()
    where = await where_clauses(db, actor, f)
    if body.ids is not None:
        where.append(Lead.id.in_(body.ids))
    leads = list((await db.scalars(select(Lead).where(*where).limit(BULK_CAP + 1))).all())
    if len(leads) > BULK_CAP:
        raise Invalid(f"That matches more than {BULK_CAP} leads; narrow the filters first")

    owner = stage = None
    if body.action == "assign":
        owner = await L.check_assignable(db, actor, body.owner_user_id)
    elif body.action == "stage":
        if body.stage_id is None:
            raise Invalid("Choose a stage")
        stage = await L.get_stage(db, body.stage_id)
        if stage.is_unqualified and not (body.unqualified_reason or "").strip():
            raise Invalid(f"Give a reason for moving to {stage.name}")
    elif body.action == "follow_up" and (
        body.next_follow_up_at is None or body.next_follow_up_at <= L.now()
    ):
        raise Invalid("Choose a follow-up time in the future")
    tags: list = []
    if body.action in ("tag", "untag"):
        tags = await T.resolve(
            db, actor.user.tenant_id, body.tag_ids, body.new_tags if body.action == "tag" else []
        )
        if not tags:
            raise Invalid("Choose a tag")

    done, skipped = 0, []
    for lead in leads:
        try:
            if body.action == "assign":
                await L.change_owner(db, lead, owner, actor)
            elif body.action == "stage":
                if stage.is_unqualified:
                    lead.unqualified_reason = body.unqualified_reason.strip()
                await L.move_stage(db, lead, stage, actor)
            elif body.action == "follow_up":
                if not lead.is_open:
                    raise Invalid("Closed leads have no follow-up")
                await L.set_follow_up(db, lead, body.next_follow_up_at, actor)
            elif body.action == "tag":
                await T.change(db, actor, lead, add=tags)
            elif body.action == "untag":
                await T.change(db, actor, lead, remove=[t.id for t in tags])
            else:
                lead_id = lead.id
                await _not_a_customer(db, lead)
                await db.execute(
                    delete(CustomFieldUniqueValue).where(
                        CustomFieldUniqueValue.entity == "lead",
                        CustomFieldUniqueValue.record_id == lead_id,
                    )
                )
                await db.delete(lead)
                await audit(db, actor, "lead.deleted", "lead", lead_id)
                done += 1
                continue
            lead.version += 1
            done += 1
        except Invalid as e:
            skipped.append(Skipped(id=lead.id, name=lead.display_name, reason=e.detail))
    await db.flush()
    return BulkOut(done=done, skipped=skipped)


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
async def create_lead(body: LeadIn, db: CrmDb, actor: Creator) -> LeadOut:
    """Quick-add. A matching phone or email is refused with the existing lead (if you can see
    it) unless the company keeps duplicates (flag / create)."""
    tenant_id = actor.user.tenant_id
    # A rep's own new lead is theirs; people who can assign may pick an owner, leave it
    # unassigned, or let the assignment rules decide (#21).
    owner: uuid.UUID | str | None
    if L.can(actor, "leads.assign"):
        if body.assign_by_rules:
            owner = I.RULES
        else:
            owner = body.owner_user_id or (actor.user.id if body.assign_to_me else None)
            await L.check_assignable(db, actor, owner)
    else:
        if body.owner_user_id not in (None, actor.user.id) or body.assign_by_rules:
            raise Forbidden("You can only add leads for yourself")
        owner = actor.user.id
        await L.check_assignable(db, actor, owner)

    setting = await db.scalar(
        select(TenantSettings.duplicate_policy).where(TenantSettings.tenant_id == tenant_id)
    )
    policy = {"flag": "flag", "create": "create"}.get(setting, "refuse")
    fields = _clean(body.model_dump(include=set(LeadFields.model_fields) | ATTRIBUTION))
    fields.pop("unqualified_reason", None)
    inc = I.Incoming(
        identities=_identities(body.identities),
        source_id=body.source_id,
        created_via="manual",
        kind=body.kind,
        fields=fields,
        custom_fields=body.custom_fields,
        stage_id=body.stage_id,
        origin=body.origin,
        owner=owner,
        next_follow_up_at=body.next_follow_up_at,
        created_summary=f"Added by {actor.user.name}",
        brand_id=body.brand_id,
    )
    if body.unqualified_reason:
        inc.fields["unqualified_reason"] = body.unqualified_reason
    outcome = await I.intake(db, tenant_id, inc, policy=policy, actor=actor)
    await db.flush()
    return (await _out(db, [outcome.lead], actor))[0]


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> LeadOut:
    return (await _out(db, [await L.get_visible(db, actor, lead_id)], actor))[0]


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: uuid.UUID, body: LeadPatch, db: CrmDb, actor: Editor) -> LeadOut:
    lead = await L.get_visible(db, actor, lead_id)
    if body.version != lead.version:
        raise Conflict("Someone else changed this lead. Reload to see their changes")
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    changed: list[str] = []
    rules = await A.rules(db, actor, "lead")
    owner_of = {a: n for n, (_, attrs) in A.builtins("lead").items() for a in attrs}

    simple = {
        k: v
        for k, v in _clean(changes).items()
        if (k in LeadFields.model_fields or k == "kind")
        # a hidden field comes back blank from a form that never saw it: not a change
        and not (k in owner_of and rules.hidden(owner_of[k]) and v is None)
    }
    for key, value in simple.items():
        if key in owner_of:
            rules.check_value(owner_of[key], getattr(lead, key), value)
        if getattr(lead, key) != value:
            setattr(lead, key, value)
            changed.append(key)
    if lead.kind == "organisation" and not lead.org_name:
        raise Invalid("An organisation needs a name")
    if changes.get("brand_id") and changes["brand_id"] != lead.brand_id:
        from app.modules.brands import service as B

        lead.brand_id = await B.pick(db, actor.user.id, changes["brand_id"])
        await B.follow_lead(db, lead)
        changed.append("brand")
    if "source_id" in changes and changes["source_id"] != lead.source_id:
        await L.check_source(db, changes["source_id"])
        lead.source_id = changes["source_id"]
        changed.append("source")
    if body.identities is not None:
        country = await L.tenant_country(db, lead.tenant_id)
        if not (rules.editable("phone") and rules.editable("email")):
            have = (await L.identities_of(db, [lead.id]))[lead.id]
            for kind in ("phone", "email"):
                old = sorted(i.value_normalized for i in have if i.type == kind)
                new = sorted(
                    normalize(i.type, i.value, country) for i in body.identities if i.type == kind
                )
                rules.check_value(kind, old, new)
        await L.set_identities(db, lead, _identities(body.identities), country)
        changed.append("identities")
    else:
        lead.display_name = L.display_name(
            lead, {"email": lead.primary_email, "phone": lead.primary_phone}
        )
    if body.custom_fields is not None:
        changed += await L.apply_custom_fields(
            db, lead, body.custom_fields, creating=False, rules=rules
        )
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
    return (await _out(db, [lead], actor))[0]


@router.put("/{lead_id}/owner", response_model=LeadOut)
async def assign_lead(lead_id: uuid.UUID, body: OwnerIn, db: CrmDb, actor: Assigner) -> LeadOut:
    lead = await L.get_visible(db, actor, lead_id)
    owner = await L.check_assignable(db, actor, body.owner_user_id)
    await L.change_owner(db, lead, owner, actor)
    lead.version += 1
    await db.flush()
    return (await _out(db, [lead], actor))[0]


async def _not_a_customer(db, lead: Lead) -> None:
    """Customers keep their documents (and, from step 6, invoices): set them Inactive instead."""
    if await db.scalar(select(Customer.id).where(Customer.lead_id == lead.id)):
        raise Invalid(
            f"{lead.display_name} is a customer and cannot be deleted. Set them Inactive."
        )


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(lead_id: uuid.UUID, db: CrmDb, actor: Deleter) -> None:
    """Permanent (Decision log #18): the lead, its timeline and tasks are gone. The audit row
    keeps only the lead's ID, no personal data."""
    lead = await L.get_visible(db, actor, lead_id)
    await _not_a_customer(db, lead)
    await db.execute(
        delete(CustomFieldUniqueValue).where(
            CustomFieldUniqueValue.entity == "lead", CustomFieldUniqueValue.record_id == lead.id
        )
    )
    await db.delete(lead)
    await db.flush()
    await audit(db, actor, "lead.deleted", "lead", lead_id)

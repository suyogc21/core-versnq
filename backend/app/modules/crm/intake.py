"""One way in for every new lead: quick-add, web form / webhook, CSV import and (later) the
API, ACE and inbound WhatsApp. Every path gets the same rules:

R1/R7 identities → duplicate check (R5) → create or update → owner (rules or chosen) →
consent → organisation grouping (#14) → SLA clocks → timeline, events and notifications.

Duplicates match on a cleaned phone or email within the company. Policies:
- update: the existing lead is updated (blank fields filled, new phones/emails added), keeps
  its owner, gets an "Enquired again" activity and is reopened if closed (DM2).
- flag:   a new lead is created and marked as a possible duplicate of the first match.
- create: a new lead is always created.
- skip:   nothing happens (CSV import option).
- refuse: the caller is told the lead already exists (quick-add by a person).
Two arrivals with the same phone or email at the same moment are serialised by an advisory
lock, so they can never both create a lead.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, DomainError, Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.crm import access as A
from app.modules.crm import consent as C
from app.modules.crm import leads as L
from app.modules.crm import orgs as O
from app.modules.crm import routing as R
from app.modules.crm.identities import normalize
from app.modules.crm.models import ExternalRef, Lead, LeadIdentity, LeadStage
from app.modules.crm.notify import notify
from app.modules.users.models import User

Policy = Literal["update", "flag", "create", "skip", "refuse"]
RULES = "rules"  # owner chosen by the assignment rules
MATCH_ON = ("email", "phone")

PLAIN_FIELDS = (
    "first_name", "last_name", "org_name", "website", "industry", "employee_range",
    "preferred_language", "city", "region", "country_code", "unqualified_reason",
)  # fmt: skip
ATTRIBUTION = ("campaign", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")


@dataclass
class Incoming:
    identities: list[L.IdentityInput]
    source_id: uuid.UUID
    created_via: str  # manual / form / csv / api
    kind: str = "person"
    fields: dict = field(default_factory=dict)  # PLAIN_FIELDS and ATTRIBUTION
    custom_fields: dict = field(default_factory=dict)
    stage_id: uuid.UUID | None = None
    origin: str = "inbound"
    owner: uuid.UUID | str | None = RULES  # a user id, RULES, or None (unassigned)
    next_follow_up_at: datetime | None = None
    consents: dict[str, str] = field(default_factory=dict)  # channel -> opted_in / opted_out
    consent_wording: str | None = None
    consent_evidence: dict = field(default_factory=dict)
    external: tuple[str, str] | None = None  # (system, id): makes retries safe
    message: str | None = None  # free text sent with a form, kept on the timeline
    attribution: dict = field(default_factory=dict)  # referrer, landing page, click ids...
    enforce_required: bool = True  # forms never lose a lead over a missing optional answer
    via_label: str = "quick-add"  # "the Contact us form", "import of leads.csv"
    created_summary: str | None = None  # default: "Added via <via_label>"


@dataclass
class Outcome:
    result: Literal["created", "updated", "flagged", "skipped"]
    lead: Lead | None
    match: Lead | None = None
    message: str | None = None


class DuplicateFound(Conflict):
    pass


def _consent_source(created_via: str) -> str:
    return {"form": "form", "csv": "import", "api": "api"}.get(created_via, "manual")


async def normalized_pairs(
    identities: list[L.IdentityInput], country: str
) -> list[tuple[str, str]]:
    if not identities:
        raise Invalid("Add at least one phone, email or LinkedIn profile")
    return [(i.type, normalize(i.type, i.value, country)) for i in identities]


async def _lock(db: AsyncSession, tenant_id: uuid.UUID, pairs: list[tuple[str, str]]) -> None:
    for kind, value in sorted(set(pairs)):
        if kind in MATCH_ON:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"lead:{tenant_id}:{kind}:{value}"},
            )


async def find_matches(
    db: AsyncSession, pairs: list[tuple[str, str]], exclude: uuid.UUID | None = None
) -> list[Lead]:
    wanted = [(k, v) for k, v in pairs if k in MATCH_ON]
    if not wanted:
        return []
    ids = select(LeadIdentity.lead_id).where(
        func.row(LeadIdentity.type, LeadIdentity.value_normalized).in_(wanted)
    )
    q = select(Lead).where(Lead.id.in_(ids))
    if exclude:
        q = q.where(Lead.id != exclude)
    return list((await db.scalars(q.order_by(Lead.created_at).limit(5))).all())


async def _visible(db: AsyncSession, actor: CurrentUser | None, lead: Lead) -> bool:
    if actor is None or actor.role.scope == "all":
        return True
    found = await db.scalar(
        select(Lead.id).where(Lead.id == lead.id, await L.visibility_filter(db, actor))
    )
    return found is not None


async def intake(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    inc: Incoming,
    *,
    policy: Policy,
    actor: CurrentUser | None = None,
) -> Outcome:
    country = await L.tenant_country(db, tenant_id)
    pairs = await normalized_pairs(inc.identities, country)
    await _lock(db, tenant_id, pairs)

    matches: list[Lead] = []
    if inc.external:
        ref = await db.scalar(
            select(ExternalRef).where(
                ExternalRef.system == inc.external[0], ExternalRef.external_id == inc.external[1]
            )
        )
        if ref:
            matches = [await db.get(Lead, ref.lead_id)]
    if not matches:
        matches = await find_matches(db, pairs)

    flagged_of = None
    if matches:
        first = matches[0]
        if policy == "refuse":
            seen = await _visible(db, actor, first)
            raise DuplicateFound(
                f"{first.display_name} already exists"
                if seen
                else "This person already exists and belongs to someone else. Ask your manager.",
                {"duplicate": {"id": str(first.id), "name": first.display_name} if seen else None},
            )
        if policy == "skip":
            return Outcome("skipped", None, first, "Already exists")
        if policy == "update":
            if not await _visible(db, actor, first):
                return Outcome("skipped", None, first, "Already exists and belongs to someone else")
            await reenquire(db, first, inc, actor)
            return Outcome("updated", first, first)
        if policy == "flag":
            flagged_of = first.id

    lead = await _create(db, tenant_id, inc, actor, country)
    if flagged_of:
        lead.possible_duplicate_of_id = flagged_of
        return Outcome("flagged", lead, matches[0])
    return Outcome("created", lead)


async def _create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    inc: Incoming,
    actor: CurrentUser | None,
    country: str,
) -> Lead:
    if inc.kind == "organisation" and not (inc.fields.get("org_name") or "").strip():
        raise Invalid("An organisation needs a name")
    rules = await A.rules(db, actor, "lead")
    for name, (_, attrs) in A.builtins("lead").items():
        for attr in attrs:  # a field the person may not edit cannot be filled in either
            if inc.fields.get(attr) not in (None, ""):
                rules.check_value(name, None, inc.fields[attr])
    await L.check_source(db, inc.source_id)
    stage = await L.get_stage(db, inc.stage_id) if inc.stage_id else await L.default_stage(db)

    lead = Lead(
        tenant_id=tenant_id,
        kind=inc.kind,
        display_name="",
        stage_id=stage.id,
        stage_changed_at=L.now(),
        is_open=stage.is_open,
        source_id=inc.source_id,
        origin=inc.origin,
        created_via=inc.created_via,
        created_by_user_id=actor.user.id if actor else None,
        custom_fields={},
        attribution=inc.attribution or {},
        org_suggestions_dismissed=[],
        **{k: v for k, v in inc.fields.items() if k in PLAIN_FIELDS + ATTRIBUTION},
    )
    db.add(lead)
    await db.flush()
    await L.set_identities(db, lead, inc.identities, country)
    await L.apply_custom_fields(
        db, lead, inc.custom_fields, creating=inc.enforce_required, rules=rules
    )
    try:
        await L.check_stage_entry(db, lead, stage, rules)
    except Invalid:
        if inc.enforce_required:
            raise
        fallback = await L.default_stage(db)  # a form never loses a lead over a stage rule
        lead.stage_id, lead.is_open = fallback.id, fallback.is_open

    owner: User | None = None
    if inc.owner == RULES:
        owner = await R.pick_owner(db, lead)
    elif inc.owner is not None:
        owner = await db.get(User, inc.owner)
    if owner is not None:
        lead.owner_user_id, lead.assigned_at = owner.id, L.now()
        lead.team_id = await L.owner_team(db, owner.id)
    if inc.next_follow_up_at and lead.is_open:
        await L.set_follow_up(db, lead, inc.next_follow_up_at, actor)
    await db.flush()

    await L.log(
        db,
        lead,
        "lead_created",
        inc.created_summary or f"Added via {inc.via_label}",
        actor,
        body=inc.message,
    )
    await L.event(
        db, lead, "lead.created", {"source_id": str(lead.source_id), "via": inc.created_via}
    )
    if owner:
        await L.event(db, lead, "lead.assigned", {"owner_user_id": str(owner.id)})
        if actor is None or owner.id != actor.user.id:
            await notify(
                db,
                tenant_id,
                [owner.id],
                "lead_assigned",
                f"New lead: {lead.display_name}",
                lead.id,
            )
    await _consents_and_refs(db, lead, inc, actor)
    await O.on_new_person(db, lead)
    await R.start_slas(db, lead, "lead_created")
    return lead


async def _consents_and_refs(
    db: AsyncSession, lead: Lead, inc: Incoming, actor: CurrentUser | None
) -> None:
    for channel, status in inc.consents.items():
        await C.record(
            db,
            lead,
            channel,
            status,
            _consent_source(inc.created_via),
            actor=actor,
            wording=inc.consent_wording,
            evidence=inc.consent_evidence,
        )
    if inc.external:
        exists = await db.scalar(
            select(ExternalRef.id).where(
                ExternalRef.system == inc.external[0], ExternalRef.external_id == inc.external[1]
            )
        )
        if not exists:
            db.add(
                ExternalRef(
                    tenant_id=lead.tenant_id,
                    system=inc.external[0],
                    external_id=inc.external[1],
                    lead_id=lead.id,
                )
            )


async def reenquire(db: AsyncSession, lead: Lead, inc: Incoming, actor: CurrentUser | None) -> None:
    """The same person came in again (DM2): fill what is blank, add new ways to reach them,
    never overwrite what the team already has, reopen if closed, tell the owner."""
    filled: list[str] = []
    existing = (
        await db.scalars(
            select(LeadIdentity)
            .where(LeadIdentity.lead_id == lead.id)
            .order_by(LeadIdentity.is_primary.desc(), LeadIdentity.created_at)
        )
    ).all()
    have = {(i.type, i.value_normalized) for i in existing}
    country = await L.tenant_country(db, lead.tenant_id)
    new = [i for i in inc.identities if (i.type, normalize(i.type, i.value, country)) not in have]
    if new:
        keep = [
            L.IdentityInput(i.type, i.value, i.label, i.is_primary, i.is_whatsapp) for i in existing
        ]
        await L.set_identities(
            db,
            lead,
            keep + [L.IdentityInput(**{**i.__dict__, "is_primary": False}) for i in new],
            country,
        )
        filled.append("identities")
    rules = await A.rules(db, actor, "lead")
    locked = {
        a for n, (_, attrs) in A.builtins("lead").items() if not rules.editable(n) for a in attrs
    }
    for key, value in inc.fields.items():
        if key in PLAIN_FIELDS and key not in locked and value and not getattr(lead, key):
            setattr(lead, key, value)
            filled.append(key)
    blank_custom = {
        k: v
        for k, v in inc.custom_fields.items()
        if (lead.custom_fields or {}).get(k) is None and k not in rules.locked_custom()
    }
    if blank_custom:
        before = dict(lead.custom_fields or {})
        try:
            async with db.begin_nested():
                filled += await L.apply_custom_fields(db, lead, blank_custom, creating=False)
        except DomainError:
            lead.custom_fields = before  # a bad optional answer never blocks the re-enquiry
    lead.display_name = L.display_name(
        lead, {"email": lead.primary_email, "phone": lead.primary_phone}
    )

    reopened = False
    if not lead.is_open:
        current = await db.get(LeadStage, lead.stage_id)
        if not (current and current.is_converted):
            target = await L.default_stage(db)
            try:
                lead.unqualified_reason = None
                await L.move_stage(db, lead, target, actor)
                reopened = True
            except Invalid:
                pass

    summary = f"Enquired again via {inc.via_label}"
    await L.log(
        db,
        lead,
        "re_enquiry",
        summary + (" (reopened)" if reopened else ""),
        actor,
        {
            "via": inc.created_via,
            "source_id": str(inc.source_id),
            "filled": filled,
            **{k: v for k, v in inc.fields.items() if k in ATTRIBUTION and v},
        },
        body=inc.message,
    )
    await _consents_and_refs(db, lead, inc, actor)
    if lead.owner_user_id is None and inc.owner == RULES:
        await R.assign_by_rules(db, lead)
    elif lead.owner_user_id and (actor is None or actor.user.id != lead.owner_user_id):
        await notify(
            db,
            lead.tenant_id,
            [lead.owner_user_id],
            "re_enquiry",
            f"{lead.display_name} enquired again",
            lead.id,
        )
    lead.version += 1
    await L.event(db, lead, "lead.updated", {"fields": filled, "re_enquiry": True})

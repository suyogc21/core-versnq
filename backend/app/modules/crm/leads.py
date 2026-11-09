"""Lead rules: visibility, identities (R1, R7), custom fields (linked, unique, required),
stage requirements, owners, follow-ups, timeline activities and events. Generic throughout."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, false, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.events import emit
from app.modules.auth.deps import CurrentUser, has_permission
from app.modules.crm import fields as F
from app.modules.crm.identities import normalize
from app.modules.crm.models import (
    Activity,
    CustomFieldDefinition,
    CustomFieldUniqueValue,
    Lead,
    LeadIdentity,
    LeadSource,
    LeadStage,
    Task,
)
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import TeamMember
from app.modules.teams.service import visible_user_ids
from app.modules.users.models import User


def now() -> datetime:
    return datetime.now(UTC)


# ---------- visibility ----------
async def visibility_filter(db: AsyncSession, actor: CurrentUser):
    """SQL condition for the leads this person may see (own / team / all, Decision log #21:
    unassigned leads are seen by team- and all-scope roles only)."""
    scope = actor.role.scope
    if scope == "all":
        return true()
    visible = await visible_user_ids(db, actor.user.id, scope)
    owned = Lead.owner_user_id.in_(visible) if visible else false()
    if scope == "team":
        return or_(owned, Lead.owner_user_id.is_(None))
    return owned


async def get_visible(db: AsyncSession, actor: CurrentUser, lead_id: uuid.UUID) -> Lead:
    lead = await db.scalar(
        select(Lead).where(Lead.id == lead_id, await visibility_filter(db, actor))
    )
    if lead is None:
        raise NotFound("Lead not found")
    return lead


async def check_assignable(
    db: AsyncSession, actor: CurrentUser, user_id: uuid.UUID | None
) -> User | None:
    """An owner must be an active user the actor can see."""
    if user_id is None:
        if actor.role.scope == "own":
            raise Forbidden("You cannot leave a lead unassigned")
        return None
    user = await db.get(User, user_id)
    visible = await visible_user_ids(db, actor.user.id, actor.role.scope)
    if user is None or user.status != "active" or (visible is not None and user.id not in visible):
        raise Invalid("Choose an active user from your team")
    return user


async def owner_team(db: AsyncSession, user_id: uuid.UUID | None) -> uuid.UUID | None:
    if user_id is None:
        return None
    return await db.scalar(
        select(TeamMember.team_id)
        .where(TeamMember.user_id == user_id)
        .order_by(TeamMember.is_manager.desc(), TeamMember.created_at)
        .limit(1)
    )


# ---------- identities ----------
@dataclass
class IdentityInput:
    type: str
    value: str
    label: str | None = None
    is_primary: bool = False
    is_whatsapp: bool = False


async def set_identities(
    db: AsyncSession, lead: Lead, items: list[IdentityInput], country: str
) -> None:
    """Replace the lead's identities. R1: at least one phone, email or LinkedIn profile."""
    if not items:
        raise Invalid("Add at least one phone, email or LinkedIn profile")
    rows: list[LeadIdentity] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        normalized = normalize(item.type, item.value, country)
        if (item.type, normalized) in seen:
            continue
        seen.add((item.type, normalized))
        rows.append(
            LeadIdentity(
                tenant_id=lead.tenant_id,
                lead_id=lead.id,
                type=item.type,
                value=item.value.strip(),
                value_normalized=normalized,
                is_primary=item.is_primary,
                label=(item.label or None),
                is_whatsapp=item.is_whatsapp and item.type == "phone",
            )
        )
    for kind in ("email", "phone", "linkedin"):  # exactly one primary per type
        of_kind = [r for r in rows if r.type == kind]
        if of_kind and not any(r.is_primary for r in of_kind):
            of_kind[0].is_primary = True
        for extra in [r for r in of_kind if r.is_primary][1:]:
            extra.is_primary = False
    await db.execute(delete(LeadIdentity).where(LeadIdentity.lead_id == lead.id))
    db.add_all(rows)
    primary = {r.type: r.value_normalized for r in rows if r.is_primary}
    lead.primary_email = primary.get("email")
    lead.primary_phone = primary.get("phone")
    lead.display_name = display_name(lead, primary)


def display_name(lead: Lead, primary: dict[str, str]) -> str:
    if lead.kind == "organisation" and lead.org_name:
        return lead.org_name
    name = " ".join(p for p in (lead.first_name, lead.last_name) if p)
    return name or primary.get("phone") or primary.get("email") or primary.get("linkedin") or "—"


async def identities_of(db: AsyncSession, lead_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    rows = await db.scalars(
        select(LeadIdentity)
        .where(LeadIdentity.lead_id.in_(lead_ids))
        .order_by(LeadIdentity.is_primary.desc(), LeadIdentity.created_at)
    )
    out: dict[uuid.UUID, list] = {i: [] for i in lead_ids}
    for r in rows.all():
        out[r.lead_id].append(r)
    return out


# ---------- custom fields (shared by leads and records) ----------
async def lead_fields(db: AsyncSession, entity: str = "lead") -> dict[str, CustomFieldDefinition]:
    """Field definitions of one kind: "lead", or "rt:<record type key>"."""
    rows = await db.scalars(
        select(CustomFieldDefinition).where(CustomFieldDefinition.entity == entity)
    )
    return {f.key: f for f in rows.all()}


async def apply_custom_fields(
    db: AsyncSession, obj, incoming: dict, *, creating: bool, entity: str = "lead"
) -> list[str]:
    """Validate and merge custom values onto a lead or record. Returns the keys that changed."""
    defs = await lead_fields(db, entity)
    unknown = [k for k in incoming if k not in defs]
    if unknown:
        raise Invalid(f"Unknown field: {unknown[0]}")
    merged = dict(obj.custom_fields or {})
    changed = []
    for key, raw in incoming.items():
        d = defs[key]
        value = F.coerce({"type": d.type, "label": d.label, "options": d.options}, raw)
        if merged.get(key) != value:
            changed.append(key)
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    for d in defs.values():
        if d.required and merged.get(d.key) is None and (creating or d.key in incoming):
            raise Invalid(f"{d.label} is required")
        if d.depends_on and merged.get(d.key) is not None:
            parent_value = merged.get(d.depends_on)
            allowed = {o["value"] for o in d.options if o.get("parent") == parent_value}
            values = merged[d.key] if isinstance(merged[d.key], list) else [merged[d.key]]
            if parent_value is None or any(v not in allowed for v in values):
                parent_label = defs[d.depends_on].label if d.depends_on in defs else d.depends_on
                raise Invalid(f"{d.label} does not match the chosen {parent_label}")
    obj.custom_fields = merged
    await _sync_unique(db, obj, defs, changed, entity)
    return changed


async def _sync_unique(db, obj, defs: dict, changed: list[str], entity: str) -> None:
    for key in changed:
        if not defs[key].is_unique:
            continue
        await db.execute(
            delete(CustomFieldUniqueValue).where(
                CustomFieldUniqueValue.entity == entity,
                CustomFieldUniqueValue.field_key == key,
                CustomFieldUniqueValue.record_id == obj.id,
            )
        )
        value = obj.custom_fields.get(key)
        if value is None:
            continue
        await db.flush()  # everything else first, so only the unique row is in the savepoint
        try:
            async with db.begin_nested():
                db.add(
                    CustomFieldUniqueValue(
                        tenant_id=obj.tenant_id,
                        entity=entity,
                        field_key=key,
                        value_normalized=F.unique_form(value),
                        record_id=obj.id,
                    )
                )
                await db.flush()
        except IntegrityError:
            what = "lead" if entity == "lead" else "record"
            raise Conflict(
                f"{defs[key].label} '{value}' is already used by another {what}"
            ) from None


# ---------- stages ----------
BUILTIN_VALUE = {
    "first_name": lambda lead: lead.first_name,
    "last_name": lambda lead: lead.last_name,
    "org_name": lambda lead: lead.org_name,
    "email": lambda lead: lead.primary_email,
    "phone": lambda lead: lead.primary_phone,
    "owner": lambda lead: lead.owner_user_id,
    "website": lambda lead: lead.website,
    "city": lambda lead: lead.city,
    "region": lambda lead: lead.region,
    "country_code": lambda lead: lead.country_code,
    "preferred_language": lambda lead: lead.preferred_language,
}


async def check_stage_entry(db: AsyncSession, lead: Lead, stage: LeadStage) -> None:
    """Required fields per stage (Decision log #21) and a reason for unqualified stages."""
    if not stage.required_fields:
        missing = []
    else:
        defs = await lead_fields(db)
        missing = []
        for key in stage.required_fields:
            if key in BUILTIN_VALUE:
                if not BUILTIN_VALUE[key](lead):
                    missing.append(key.replace("_", " "))
            elif (lead.custom_fields or {}).get(key) is None:
                missing.append(defs[key].label if key in defs else key)
    if missing:
        raise Invalid(f"To move to {stage.name}, fill in: {', '.join(missing)}")
    if stage.is_unqualified and not (lead.unqualified_reason or "").strip():
        raise Invalid(f"Give a reason for moving to {stage.name}")


async def get_stage(db: AsyncSession, stage_id: uuid.UUID) -> LeadStage:
    stage = await db.get(LeadStage, stage_id)
    if stage is None:
        raise Invalid("Stage not found")
    return stage


async def default_stage(db: AsyncSession) -> LeadStage:
    return await db.scalar(
        select(LeadStage).where(LeadStage.is_open.is_(True)).order_by(LeadStage.position).limit(1)
    )


async def check_source(db: AsyncSession, source_id: uuid.UUID) -> LeadSource:
    source = await db.get(LeadSource, source_id)
    if source is None or not source.is_active:
        raise Invalid("Choose an active source")
    return source


# ---------- timeline + events ----------
async def log(
    db: AsyncSession,
    lead: Lead,
    type_key: str,
    summary: str,
    actor: CurrentUser | None,
    data: dict | None = None,
    *,
    disposition: str | None = None,
    body: str | None = None,
    occurred_at: datetime | None = None,
) -> Activity:
    activity = Activity(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        type_key=type_key,
        actor_type="user" if actor else "system",
        actor_id=actor.user.id if actor else None,
        occurred_at=occurred_at or now(),
        summary=summary[:500],
        body=body,
        data=data or {},
        disposition=disposition,
    )
    db.add(activity)
    await db.flush()
    return activity


async def event(db: AsyncSession, lead: Lead, type_: str, extra: dict | None = None) -> None:
    await emit(db, lead.tenant_id, type_, {"lead_id": str(lead.id)} | (extra or {}))


# ---------- follow-ups ----------
async def set_follow_up(
    db: AsyncSession, lead: Lead, when: datetime | None, actor: CurrentUser | None
) -> None:
    """The lead's next follow-up is mirrored as one open task (shown on My Day)."""
    open_follow_ups = (
        await db.scalars(
            select(Task).where(
                Task.lead_id == lead.id, Task.is_follow_up.is_(True), Task.status == "open"
            )
        )
    ).all()
    for task in open_follow_ups:
        task.status, task.completed_at = "cancelled", now()
    lead.next_follow_up_at = when
    if when is None:
        return
    lead.leak_alerted_at = None  # rescheduled: the leakage guard watches the new date
    owner = lead.owner_user_id or (actor.user.id if actor else None)
    if owner is None:
        return
    task = Task(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        title=f"Follow up with {lead.display_name}"[:200],
        due_at=when,
        owner_user_id=owner,
        is_follow_up=True,
        created_from="manual",
        created_by_user_id=actor.user.id if actor else None,
    )
    db.add(task)
    await db.flush()
    await emit(
        db, lead.tenant_id, "task.created", {"task_id": str(task.id), "lead_id": str(lead.id)}
    )


async def follow_up_required(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(
            select(TenantSettings.follow_up_required).where(TenantSettings.tenant_id == tenant_id)
        )
    )


async def tenant_country(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    return (
        await db.scalar(
            select(TenantSettings.default_country).where(TenantSettings.tenant_id == tenant_id)
        )
        or "IN"
    )


async def day_bounds(db: AsyncSession, tenant_id: uuid.UUID) -> tuple[datetime, datetime]:
    """(now, start of tomorrow) in the company's own time zone."""
    tz_name = await db.scalar(
        select(TenantSettings.timezone).where(TenantSettings.tenant_id == tenant_id)
    )
    local = now().astimezone(ZoneInfo(tz_name or "UTC"))
    tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now(), tomorrow.astimezone(UTC)


def can(actor: CurrentUser, code: str) -> bool:
    return has_permission(actor.permissions, code)


async def move_stage(
    db: AsyncSession, lead: Lead, stage: LeadStage, actor: CurrentUser | None
) -> None:
    if stage.id == lead.stage_id:
        return
    await check_stage_entry(db, lead, stage)
    old = await db.get(LeadStage, lead.stage_id)
    lead.stage_id, lead.stage_changed_at, lead.is_open = stage.id, now(), stage.is_open
    if not stage.is_unqualified:
        lead.unqualified_reason = None
    if not stage.is_open:  # closed leads need no follow-up
        await set_follow_up(db, lead, None, actor)
    await log(
        db,
        lead,
        "stage_changed",
        f"{old.name if old else '—'} → {stage.name}",
        actor,
        {"from": str(old.id) if old else None, "to": str(stage.id)},
    )
    await event(
        db, lead, "lead.stage_changed", {"from": str(old.id) if old else None, "to": str(stage.id)}
    )
    from app.modules.crm.routing import start_slas  # routing builds on this module

    await start_slas(db, lead, "stage_entered", stage)


async def change_owner(
    db: AsyncSession, lead: Lead, owner: User | None, actor: CurrentUser | None
) -> None:
    new_id = owner.id if owner else None
    if new_id == lead.owner_user_id:
        return
    old_id = lead.owner_user_id
    lead.owner_user_id, lead.assigned_at = new_id, now() if new_id else None
    lead.team_id = await owner_team(db, new_id)
    if new_id:  # the open follow-up moves with the lead
        await db.execute(
            update(Task)
            .where(Task.lead_id == lead.id, Task.status == "open", Task.is_follow_up.is_(True))
            .values(owner_user_id=new_id)
        )
    await log(
        db,
        lead,
        "owner_changed",
        f"Assigned to {owner.name}" if owner else "Unassigned",
        actor,
        {"from": str(old_id) if old_id else None, "to": str(new_id) if new_id else None},
    )
    await event(db, lead, "lead.assigned", {"owner_user_id": str(new_id) if new_id else None})

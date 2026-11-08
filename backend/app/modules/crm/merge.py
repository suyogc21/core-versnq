"""Merging two leads that are the same person or organisation.

The surviving lead keeps its own values unless the person merging chooses the other lead's
value for a field; blanks are always filled from the other lead. Phones, emails, timeline,
tasks, consents, external references and linked people all move to the survivor. The other
lead is then deleted; a snapshot of it is kept with the survivor (and removed with it).
An opt-out on either lead wins.
"""

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.deps import audit
from app.modules.crm.intake import PLAIN_FIELDS
from app.modules.crm.models import (
    Activity,
    Consent,
    CustomFieldUniqueValue,
    ExternalRef,
    Lead,
    LeadIdentity,
    LeadMerge,
    Notification,
    Task,
)
from app.modules.users.models import User

CHOOSABLE = (*PLAIN_FIELDS, "source_id", "owner")


def _snapshot(lead: Lead, identities: list[LeadIdentity]) -> dict:
    data = {
        c.key: getattr(lead, c.key) for c in Lead.__table__.columns if c.key not in ("tenant_id",)
    }
    data = {k: (str(v) if v is not None and not isinstance(v, (str, int, bool, dict, list)) else v)
            for k, v in data.items()}  # fmt: skip
    data["identities"] = [
        {"type": i.type, "value": i.value, "label": i.label, "is_whatsapp": i.is_whatsapp}
        for i in identities
    ]
    return data


async def merge(
    db: AsyncSession,
    actor: CurrentUser,
    survivor: Lead,
    other: Lead,
    take_from_other: list[str],
) -> Lead:
    if survivor.id == other.id:
        raise Invalid("Choose two different leads")
    if survivor.kind != other.kind:
        raise Invalid("Merge two people or two organisations, not one of each")
    unknown = [f for f in take_from_other if f not in CHOOSABLE and not f.startswith("custom:")]
    if unknown:
        raise Invalid(f"Unknown field: {unknown[0]}")

    other_ids = (
        await db.scalars(
            select(LeadIdentity)
            .where(LeadIdentity.lead_id == other.id)
            .order_by(LeadIdentity.is_primary.desc(), LeadIdentity.created_at)
        )
    ).all()
    mine = (
        await db.scalars(
            select(LeadIdentity)
            .where(LeadIdentity.lead_id == survivor.id)
            .order_by(LeadIdentity.is_primary.desc(), LeadIdentity.created_at)
        )
    ).all()
    snapshot = _snapshot(other, list(other_ids))

    # Plain fields: chosen ones from the other lead; blanks always filled.
    for f in PLAIN_FIELDS:
        theirs = getattr(other, f)
        if theirs and (f in take_from_other or not getattr(survivor, f)):
            setattr(survivor, f, theirs)
    if "source_id" in take_from_other:
        survivor.source_id = other.source_id
    if "owner" in take_from_other and other.owner_user_id != survivor.owner_user_id:
        owner = await db.get(User, other.owner_user_id) if other.owner_user_id else None
        await L.change_owner(db, survivor, owner, actor)

    # Custom fields: free the other lead's unique values first, then apply.
    await db.execute(
        delete(CustomFieldUniqueValue).where(
            CustomFieldUniqueValue.entity == "lead", CustomFieldUniqueValue.record_id == other.id
        )
    )
    incoming = {
        k: v
        for k, v in (other.custom_fields or {}).items()
        if f"custom:{k}" in take_from_other or (survivor.custom_fields or {}).get(k) is None
    }
    if incoming:
        await L.apply_custom_fields(db, survivor, incoming, creating=False)

    # Phones and emails: everything both had, the survivor's primaries first.
    country = await L.tenant_country(db, survivor.tenant_id)
    items = [
        L.IdentityInput(i.type, i.value, i.label, i.is_primary, i.is_whatsapp) for i in mine
    ] + [L.IdentityInput(i.type, i.value, i.label, False, i.is_whatsapp) for i in other_ids]
    await L.set_identities(db, survivor, items, country)

    # History and work move over.
    for model in (Activity, Task, Consent, ExternalRef, Notification):
        await db.execute(update(model).where(model.lead_id == other.id).values(lead_id=survivor.id))
    await db.execute(
        update(Lead).where(Lead.organisation_id == other.id).values(organisation_id=survivor.id)
    )
    await db.execute(  # earlier merges into the other lead now point at the survivor
        update(LeadMerge).where(LeadMerge.survivor_id == other.id).values(survivor_id=survivor.id)
    )
    if survivor.organisation_id == other.id:
        survivor.organisation_id = None
    if survivor.possible_duplicate_of_id == other.id:
        survivor.possible_duplicate_of_id = None
    if not survivor.organisation_id and other.organisation_id != survivor.id:
        survivor.organisation_id = other.organisation_id

    # One open follow-up at most: keep the survivor's, else the other lead's.
    open_follow_ups = (
        await db.scalars(
            select(Task)
            .where(Task.lead_id == survivor.id, Task.is_follow_up.is_(True), Task.status == "open")
            .order_by(Task.due_at)
        )
    ).all()
    keep = next(
        (t for t in open_follow_ups if t.due_at == survivor.next_follow_up_at),
        open_follow_ups[0] if open_follow_ups else None,
    )
    for t in open_follow_ups:
        if t is not keep:
            t.status, t.completed_at = "cancelled", L.now()
    if not survivor.is_open:
        survivor.next_follow_up_at = None
    elif keep:
        survivor.next_follow_up_at = keep.due_at
    else:  # unassigned leads have a date but no task
        survivor.next_follow_up_at = survivor.next_follow_up_at or other.next_follow_up_at

    for channel in ("email", "whatsapp"):
        states = {getattr(survivor, f"{channel}_consent"), getattr(other, f"{channel}_consent")}
        if "opted_out" in states:
            setattr(survivor, f"{channel}_consent", "opted_out")
        elif "opted_in" in states:
            setattr(survivor, f"{channel}_consent", "opted_in")
    survivor.last_activity_at = max(
        filter(None, [survivor.last_activity_at, other.last_activity_at]), default=None
    )
    survivor.last_contacted_at = max(
        filter(None, [survivor.last_contacted_at, other.last_contacted_at]), default=None
    )
    survivor.first_response_at = min(
        filter(None, [survivor.first_response_at, other.first_response_at]), default=None
    )

    other_id, other_name = other.id, other.display_name
    db.add(
        LeadMerge(
            tenant_id=survivor.tenant_id,
            survivor_id=survivor.id,
            merged_lead_id=other_id,
            merged_by_user_id=actor.user.id,
            snapshot=snapshot,
        )
    )
    await db.flush()
    await db.delete(other)
    await db.flush()
    survivor.display_name = L.display_name(
        survivor, {"email": survivor.primary_email, "phone": survivor.primary_phone}
    )
    await L.log(
        db,
        survivor,
        "lead_merged",
        f"Merged with {other_name}",
        actor,
        {"merged_lead_id": str(other_id)},
    )
    await L.event(db, survivor, "lead.merged", {"merged_lead_id": str(other_id)})
    await audit(db, actor, "lead.merged", "lead", survivor.id, {"merged_lead_id": str(other_id)})
    survivor.version += 1
    return survivor


async def merged_into(db: AsyncSession, lead_id: uuid.UUID) -> uuid.UUID | None:
    """Where an old lead link should now go."""
    return await db.scalar(
        select(LeadMerge.survivor_id)
        .where(LeadMerge.merged_lead_id == lead_id)
        .order_by(LeadMerge.created_at.desc())
        .limit(1)
    )

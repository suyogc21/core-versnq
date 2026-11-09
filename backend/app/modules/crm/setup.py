"""A company's starting CRM setup, copied from its industry pack. Configuration only: after
seeding, every company edits its own stages, sources, fields and activity types."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import (
    ActivityType,
    CustomFieldDefinition,
    LeadSource,
    LeadStage,
    LinkType,
    RecordType,
    RecordTypeStage,
)
from app.platform.models import Tenant
from app.platform.packs import IndustryPack, load_pack

INVALID_STAGE = "Invalid"


def _call_fields(dispositions: list[str]) -> list[dict]:
    options = [{"value": d.lower().replace(" ", "_"), "label": d} for d in dispositions]
    return [
        {
            "key": "disposition",
            "label": "Outcome",
            "type": "select",
            "options": options,
            "required": True,
        }
    ]


# Added in step 1 (migration 0011 adds them for companies that already exist).
STEP1_SYSTEM_TYPES = [
    {"key": "re_enquiry", "label": "Enquired again", "icon": "repeat", "loggable": False},
    {"key": "lead_merged", "label": "Leads merged", "icon": "merge", "loggable": False},
    {
        "key": "consent_changed",
        "label": "Consent changed",
        "icon": "shield-check",
        "loggable": False,
    },
    {
        "key": "organisation_linked",
        "label": "Organisation linked",
        "icon": "building",
        "loggable": False,
    },
    {
        "key": "sla_missed",
        "label": "Response time missed",
        "icon": "alarm-clock",
        "loggable": False,
    },
]

# Added in step 2 (migration 0012 adds them for companies that already exist).
STEP2_SYSTEM_TYPES = [
    {"key": "record_created", "label": "Created", "icon": "plus", "loggable": False},
    {"key": "linked", "label": "Linked", "icon": "link", "loggable": False},
    {"key": "unlinked", "label": "Unlinked", "icon": "unlink", "loggable": False},
]


def system_activity_types(dispositions: list[str]) -> list[dict]:
    """Built-in types every company has. Keys are fixed; labels and call outcomes are editable."""
    return [
        {"key": "call", "label": "Call", "icon": "phone", "fields": _call_fields(dispositions)},
        {"key": "note", "label": "Note", "icon": "sticky-note", "fields": []},
        {"key": "lead_created", "label": "Lead created", "icon": "plus", "loggable": False},
        {"key": "lead_updated", "label": "Details changed", "icon": "pencil", "loggable": False},
        {"key": "stage_changed", "label": "Stage changed", "icon": "git-commit", "loggable": False},
        {"key": "owner_changed", "label": "Owner changed", "icon": "user-round", "loggable": False},
        {"key": "task_completed", "label": "Task completed", "icon": "check", "loggable": False},
        *STEP1_SYSTEM_TYPES,
        *STEP2_SYSTEM_TYPES,
    ]


async def seed_crm(db: AsyncSession, tenant_id: uuid.UUID, pack: IndustryPack) -> None:
    crm = pack.crm
    for i, st in enumerate(crm.stages):
        db.add(LeadStage(tenant_id=tenant_id, position=i, **st.model_dump()))
    db.add(
        LeadStage(
            tenant_id=tenant_id,
            name=INVALID_STAGE,
            position=len(crm.stages),
            is_open=False,
            is_unqualified=True,
            is_system=True,
            colour="#94a3b8",
            required_fields=[],
        )
    )
    for i, name in enumerate(crm.sources):
        db.add(LeadSource(tenant_id=tenant_id, name=name, position=i))
    for i, f in enumerate(crm.custom_fields):
        db.add(
            CustomFieldDefinition(tenant_id=tenant_id, entity="lead", position=i, **f.model_dump())
        )
    types = system_activity_types(crm.dispositions)
    for i, t in enumerate(types):
        db.add(
            ActivityType(
                tenant_id=tenant_id,
                key=t["key"],
                label=t["label"],
                icon=t["icon"],
                fields=t.get("fields", []),
                is_system=True,
                is_loggable=t.get("loggable", True),
                position=i,
            )
        )
    for i, t in enumerate(crm.activity_types, start=len(types)):
        db.add(ActivityType(tenant_id=tenant_id, position=i, **t.model_dump()))
    await db.flush()
    await seed_record_types(db, tenant_id, pack)


async def seed_record_types(db: AsyncSession, tenant_id: uuid.UUID, pack: IndustryPack) -> None:
    """The pack's starting record types, their fields, stages, default access and link types."""
    from app.modules.crm.records import seed_access  # records builds on leads/setup

    keys: dict[str, uuid.UUID] = {}
    for i, rt in enumerate(pack.crm.record_types):
        rtype = RecordType(
            tenant_id=tenant_id,
            key=rt.key,
            singular=rt.singular,
            plural=rt.plural,
            icon=rt.icon,
            has_owner=rt.has_owner,
            has_stages=bool(rt.stages),
            position=i,
        )
        db.add(rtype)
        await db.flush()
        keys[rt.key] = rtype.id
        for j, st in enumerate(rt.stages):
            db.add(
                RecordTypeStage(
                    tenant_id=tenant_id,
                    record_type_id=rtype.id,
                    position=j,
                    required_fields=[],
                    **st.model_dump(),
                )
            )
        for j, f in enumerate(rt.fields):
            db.add(
                CustomFieldDefinition(
                    tenant_id=tenant_id, entity=rtype.entity, position=j, **f.model_dump()
                )
            )
        await seed_access(db, rtype)
    for i, lt in enumerate(pack.crm.link_types):
        db.add(
            LinkType(
                tenant_id=tenant_id,
                from_type_id=keys[lt.from_type] if lt.from_type else None,
                to_type_id=keys[lt.to_type] if lt.to_type else None,
                label=lt.label,
                inverse_label=lt.inverse_label,
                many_to=lt.many_to,
                many_from=lt.many_from,
                position=i,
            )
        )
    await db.flush()


async def ensure_crm_setup(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Seed companies created before the CRM existed (first use after upgrading)."""
    if await db.scalar(select(LeadStage.id).limit(1)):
        return
    pack_key = await db.scalar(select(Tenant.industry_pack).where(Tenant.id == tenant_id))
    await seed_crm(db, tenant_id, load_pack(pack_key or "generic"))

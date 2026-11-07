"""A company's starting CRM setup, copied from its industry pack. Configuration only: after
seeding, every company edits its own stages, sources, fields and activity types."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import ActivityType, CustomFieldDefinition, LeadSource, LeadStage
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


async def ensure_crm_setup(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Seed companies created before the CRM existed (first use after upgrading)."""
    if await db.scalar(select(LeadStage.id).limit(1)):
        return
    pack_key = await db.scalar(select(Tenant.industry_pack).where(Tenant.id == tenant_id))
    await seed_crm(db, tenant_id, load_pack(pack_key or "generic"))

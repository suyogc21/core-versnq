"""Helpers for step 1 tests: run the shared intake path the way a form or import does."""

import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.core.tenancy import tenant_session
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.models import Activity, AssignmentRule, Lead, LeadSource, Notification
from app.modules.settings.models import TenantSettings


async def capture(tenant_id, *, phone=None, email=None, policy="update", **kw):
    """Returns (result, lead_id)."""
    async with tenant_session(tenant_id) as db:
        source_id = kw.pop("source_id", None) or await db.scalar(
            select(LeadSource.id).order_by(LeadSource.position).limit(1)
        )
        ids = []
        if phone:
            ids.append(L.IdentityInput("phone", phone))
        if email:
            ids.append(L.IdentityInput("email", email))
        inc = I.Incoming(
            identities=ids,
            source_id=source_id,
            created_via=kw.pop("created_via", "form"),
            enforce_required=False,
            via_label="the test form",
            **kw,
        )
        out = await I.intake(db, tenant_id, inc, policy=policy)
        return out.result, (out.lead.id if out.lead else None)


async def settings(tenant_id, **values):
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(TenantSettings).where(TenantSettings.tenant_id == tenant_id).values(**values)
        )


async def lead(tenant_id, lead_id) -> Lead:
    async with tenant_session(tenant_id) as db:
        return await db.get(Lead, lead_id)


async def activities(tenant_id, lead_id) -> list[str]:
    async with tenant_session(tenant_id) as db:
        rows = await db.scalars(
            select(Activity.type_key)
            .where(Activity.lead_id == lead_id)
            .order_by(Activity.created_at)
        )
        return list(rows.all())


async def notifications(tenant_id, user_id) -> list[tuple[str, str]]:
    async with tenant_session(tenant_id) as db:
        rows = await db.execute(
            select(Notification.kind, Notification.title)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at)
        )
        return [tuple(r) for r in rows.all()]


async def rule(tenant_id, *, strategy="round_robin", user_ids=(), conditions=(), position=0, **kw):
    async with tenant_session(tenant_id) as db:
        r = AssignmentRule(
            tenant_id=tenant_id,
            name=f"Rule {uuid.uuid4().hex[:4]}",
            position=position,
            strategy=strategy,
            user_ids=[str(u) for u in user_ids],
            conditions=list(conditions),
            **kw,
        )
        db.add(r)
    return r.id


async def backdate(tenant_id, lead_id, hours, **fields):
    async with tenant_session(tenant_id) as db:
        then = L.now() - timedelta(hours=hours)
        await db.execute(update(Lead).where(Lead.id == lead_id).values(created_at=then, **fields))

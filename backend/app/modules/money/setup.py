"""A company's starting money setup: one billing entity (its own name, country and currency)
and the pack's tax rates for that country. Runs on first use; everything is editable."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import ActivityType
from app.modules.crm.setup import STEP6_SYSTEM_TYPES
from app.modules.money.models import BillingEntity, TaxRate
from app.modules.settings.models import TenantSettings
from app.platform.models import Tenant
from app.platform.packs import load_pack


async def ensure_money_setup(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    if await db.scalar(select(BillingEntity.id).limit(1)):
        return
    tenant = await db.get(Tenant, tenant_id)
    settings = await db.get(TenantSettings, tenant_id)
    money = load_pack(tenant.industry_pack or "generic").crm.money
    country = settings.default_country
    db.add(
        BillingEntity(
            tenant_id=tenant_id,
            name=tenant.name,
            legal_name=tenant.name,
            country=country,
            currency=settings.default_currency,
            tax_label=money.tax_labels.get(country) or money.tax_labels.get("*"),
            yearly_reset=country in money.yearly_reset,
            is_default=True,
            position=0,
        )
    )
    if not await db.scalar(select(TaxRate.id).limit(1)):
        rates = money.tax_rates.get(country) or money.tax_rates.get("*") or []
        for i, r in enumerate(rates):
            db.add(TaxRate(tenant_id=tenant_id, name=r.name, parts=r.parts, position=i))
    have = set((await db.scalars(select(ActivityType.key))).all())
    top = len(have)
    for i, t in enumerate(STEP6_SYSTEM_TYPES):
        if t["key"] not in have:
            db.add(
                ActivityType(
                    tenant_id=tenant_id,
                    key=t["key"],
                    label=t["label"],
                    icon=t["icon"],
                    is_system=True,
                    is_loggable=False,
                    is_active=True,
                    fields=[],
                    position=top + i + 1,
                )
            )
    await db.flush()

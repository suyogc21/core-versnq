"""Per-tenant module switches (feature flags). Core never depends on a module."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import Invalid, NotFound


@dataclass(frozen=True)
class Module:
    name: str
    core: bool  # core modules cannot be switched off
    default: bool


MODULES: dict[str, Module] = {
    "crm": Module("Leads, deals, tasks, customers", core=True, default=True),
    "email": Module("Email channel", core=False, default=True),
    "whatsapp": Module("WhatsApp channel", core=False, default=True),
    "sequences": Module("Email and WhatsApp sequences", core=False, default=True),
    "inbox": Module("Unified inbox", core=False, default=True),
    "api": Module("Public API and webhooks", core=False, default=True),
    "money": Module("Invoices and payments", core=False, default=False),
    "key_accounts": Module("Key accounts add-on", core=False, default=False),
    "ace": Module("Versnq ACE add-on", core=False, default=False),
}


class TenantModule(Base):
    """Only overrides are stored; a missing row means the module's default."""

    __tablename__ = "tenant_modules"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), primary_key=True)
    module_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def module_states(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, bool]:
    rows = await db.execute(
        select(TenantModule.module_key, TenantModule.enabled).where(
            TenantModule.tenant_id == tenant_id
        )
    )
    overrides = dict(rows.all())
    return {key: overrides.get(key, m.default) or m.core for key, m in MODULES.items()}


async def is_enabled(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> bool:
    return (await module_states(db, tenant_id))[key]


async def set_module(db: AsyncSession, tenant_id: uuid.UUID, key: str, enabled: bool) -> None:
    module = MODULES.get(key)
    if module is None:
        raise Invalid(f"Unknown module: {key}")
    if module.core and not enabled:
        raise Invalid(f"'{key}' is part of Core and cannot be switched off")
    stmt = insert(TenantModule).values(tenant_id=tenant_id, module_key=key, enabled=enabled)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["tenant_id", "module_key"],
            set_={"enabled": enabled, "updated_at": func.now()},
        )
    )


def require_module(key: str):
    """Route dependency: answers 404 when the tenant has this module switched off."""
    from app.modules.auth.deps import TenantDb, WorkspaceDep  # avoid import cycle

    async def check(ws: WorkspaceDep, db: TenantDb) -> None:
        if not await is_enabled(db, ws.id, key):
            raise NotFound("Not found")

    return Depends(check)

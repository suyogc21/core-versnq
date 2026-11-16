"""Route plumbing shared by every CRM endpoint."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import require_module
from app.modules.audit.models import record
from app.modules.auth.deps import CurrentUser, TenantDb, WorkspaceDep
from app.modules.crm.setup import ensure_crm_setup

# Every CRM route sits behind the crm module switch (404 when off).
CRM = [require_module("crm")]
# Off on the "Calls + WhatsApp" plan: the company works in its own CRM.
SCREENS = [require_module("crm_screens")]


async def _crm_db(ws: WorkspaceDep, db: TenantDb) -> AsyncSession:
    await ensure_crm_setup(db, ws.id)
    return db


CrmDb = Annotated[AsyncSession, Depends(_crm_db)]


async def audit(
    db: AsyncSession,
    actor: CurrentUser,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    await record(
        db,
        tenant_id=actor.user.tenant_id,
        actor_id=actor.user.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
    )

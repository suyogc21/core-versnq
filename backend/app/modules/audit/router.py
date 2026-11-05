import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.auth.deps import CurrentUser, TenantDb, require

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict | None
    after: dict | None
    created_at: datetime


@router.get("", response_model=list[AuditOut])
async def list_audit(
    db: TenantDb,
    _: Annotated[CurrentUser, require("audit.read")],
    entity_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLog]:
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return list((await db.scalars(q)).all())

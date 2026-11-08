"""The signed-in person's own in-app notifications."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.modules.auth.deps import ActiveUser
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb
from app.modules.crm.models import Notification

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"], dependencies=CRM)


class NotificationOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    kind: str
    title: str
    lead_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread: int


@router.get("", response_model=NotificationPage)
async def list_notifications(
    db: CrmDb,
    actor: ActiveUser,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> NotificationPage:
    q = select(Notification).where(Notification.user_id == actor.user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = await db.scalars(q.order_by(Notification.created_at.desc()).limit(limit))
    unread = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == actor.user.id, Notification.read_at.is_(None))
    )
    return NotificationPage(items=list(rows.all()), unread=unread or 0)


class ReadIn(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, max_length=500)  # None = all of mine


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(body: ReadIn, db: CrmDb, actor: ActiveUser) -> None:
    q = update(Notification).where(
        Notification.user_id == actor.user.id, Notification.read_at.is_(None)
    )
    if body.ids is not None:
        q = q.where(Notification.id.in_(body.ids))
    await db.execute(q.values(read_at=L.now()))

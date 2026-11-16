"""Phone notifications (calls plan, step C2): turn them on or off for this browser/phone."""

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound
from app.modules.auth.deps import ActiveUser, TenantDb
from app.modules.push.models import PushSubscription

router = APIRouter(prefix="/api/v1/push", tags=["push"])


class PushKeyOut(BaseModel):
    public_key: str | None  # null: phone notifications aren't set up on this server


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://\S+$")
    keys: PushKeys


class PushOffIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


class PushStatusOut(BaseModel):
    devices: int  # how many of your phones/browsers get notifications


@router.get("/key", response_model=PushKeyOut)
async def push_key(actor: ActiveUser) -> PushKeyOut:
    return PushKeyOut(public_key=get_settings().vapid_public_key)


@router.get("/subscriptions", response_model=PushStatusOut)
async def my_devices(actor: ActiveUser, db: TenantDb) -> PushStatusOut:
    rows = await db.scalars(select(PushSubscription.id).where(
        PushSubscription.user_id == actor.user.id))  # fmt: skip
    return PushStatusOut(devices=len(rows.all()))


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def turn_on(body: PushSubscriptionIn, actor: ActiveUser, db: TenantDb) -> None:
    """This browser/phone gets the person's notifications. The same browser again replaces its
    keys (and moves to this person, e.g. a shared tablet)."""
    if actor.user.status != "active":
        raise Forbidden("Only people get phone notifications")
    if not get_settings().vapid_public_key:
        raise NotFound("Phone notifications aren't set up yet", code="push_not_configured")
    await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    db.add(PushSubscription(
        id=uuid.uuid4(), tenant_id=actor.user.tenant_id, user_id=actor.user.id,
        endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth,
    ))  # fmt: skip


@router.post("/subscriptions/off", status_code=status.HTTP_204_NO_CONTENT)
async def turn_off(body: PushOffIn, actor: ActiveUser, db: TenantDb) -> None:
    mine = PushSubscription.user_id == actor.user.id
    await db.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint, mine)
    )

"""Settings → Developers: API keys, webhooks, and their logs (milestone 4, Decision log #37).
Needs integrations.manage. An API key can never manage keys or webhooks itself."""

import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.events import CATALOGUE
from app.core.secrets import decrypt, encrypt
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm.automation import check_url
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.integrations import keys as K
from app.modules.integrations import logs as LG
from app.modules.integrations import webhooks as W
from app.modules.integrations.models import ApiKey, ApiRequestLog, WebhookDelivery, WebhookEndpoint
from app.modules.roles.models import Role
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"], dependencies=CRM)


async def _manager(actor: Annotated[CurrentUser, require("integrations.manage")]) -> CurrentUser:
    if actor.user.status == "integration":
        raise Forbidden("An API key cannot manage keys or webhooks")
    return actor


Manager = Annotated[CurrentUser, Depends(_manager)]


# ---------- API keys ----------
class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role_id: uuid.UUID


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    role_id: uuid.UUID
    role_name: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyWithSecret(ApiKeyOut):
    key: str  # shown once


async def _key_out(db, k: ApiKey) -> ApiKeyOut:
    user = await db.get(User, k.user_id)
    role = await db.get(Role, user.role_id)
    return ApiKeyOut(
        id=k.id, name=k.name, prefix=k.prefix, role_id=role.id, role_name=role.name,
        created_at=k.created_at, last_used_at=k.last_used_at, revoked_at=k.revoked_at,
    )  # fmt: skip


@router.get("/keys", response_model=list[ApiKeyOut])
async def list_keys(db: CrmDb, actor: Manager) -> list[ApiKeyOut]:
    rows = (await db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc()))).all()
    return [await _key_out(db, k) for k in rows]


@router.post("/keys", response_model=ApiKeyWithSecret, status_code=status.HTTP_201_CREATED)
async def create_key(body: ApiKeyIn, db: CrmDb, actor: Manager) -> ApiKeyWithSecret:
    clash = await db.scalar(
        select(ApiKey.id).where(
            func.lower(ApiKey.name) == " ".join(body.name.split()).lower(),
            ApiKey.revoked_at.is_(None),
        )
    )
    if clash:
        raise Conflict("A key with this name already exists")
    key, secret = await K.create(db, actor.user.tenant_id, body.name, body.role_id, actor.user.id)
    await db.refresh(key)
    out = await _key_out(db, key)
    await audit(
        db, actor, "api_key.created", "api_key", key.id, None,
        {"name": key.name, "role": out.role_name},
    )  # fmt: skip
    return ApiKeyWithSecret(**out.model_dump(), key=secret)


@router.post("/keys/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_key(key_id: uuid.UUID, db: CrmDb, actor: Manager) -> ApiKeyOut:
    """Stops working at once. Revoked keys stay listed, so the logs still name them."""
    key = await db.get(ApiKey, key_id)
    if key is None:
        raise NotFound("Key not found")
    if key.revoked_at is None:
        key.revoked_at = W.now()
        await audit(db, actor, "api_key.revoked", "api_key", key.id, None, {"name": key.name})
        await db.flush()
    return await _key_out(db, key)


# ---------- webhooks ----------
class EventTypeOut(BaseModel):
    type: str
    module: str


@router.get("/event-types", response_model=list[EventTypeOut])
async def event_types(actor: Manager) -> list[EventTypeOut]:
    return [EventTypeOut(type=t, module=m) for t, m in CATALOGUE.items()]


class EndpointIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(min_length=1, max_length=len(CATALOGUE) + 1)
    is_active: bool = True


class EndpointPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, min_length=8, max_length=500)
    events: list[str] | None = Field(default=None, min_length=1, max_length=len(CATALOGUE) + 1)
    is_active: bool | None = None


class EndpointOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    url: str
    events: list[str]
    is_active: bool
    failing_since: datetime | None
    switched_off_reason: str | None
    created_at: datetime


class EndpointWithSecret(EndpointOut):
    secret: str


def _clean_events(events: list[str]) -> list[str]:
    if "*" in events:
        return ["*"]
    unknown = [e for e in events if e not in CATALOGUE]
    if unknown:
        raise Invalid(f"Unknown event: {unknown[0]}")
    return sorted(set(events))


async def _endpoint(db, ep_id: uuid.UUID) -> WebhookEndpoint:
    ep = await db.get(WebhookEndpoint, ep_id)
    if ep is None:
        raise NotFound("Webhook not found")
    return ep


@router.get("/webhooks", response_model=list[EndpointOut])
async def list_webhooks(db: CrmDb, actor: Manager) -> list[WebhookEndpoint]:
    return list(
        (await db.scalars(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at))).all()
    )


@router.post("/webhooks", response_model=EndpointWithSecret, status_code=status.HTTP_201_CREATED)
async def create_webhook(body: EndpointIn, db: CrmDb, actor: Manager) -> EndpointWithSecret:
    secret = "whsec_" + secrets.token_urlsafe(32)
    ep = WebhookEndpoint(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        name=" ".join(body.name.split()),
        url=check_url(body.url.strip()),
        events=_clean_events(body.events),
        secret_enc=encrypt(secret),
        is_active=body.is_active,
        created_by_user_id=actor.user.id,
    )
    db.add(ep)
    await db.flush()
    await db.refresh(ep)
    await audit(
        db, actor, "webhook.created", "webhook", ep.id, None, {"name": ep.name, "url": ep.url}
    )
    return EndpointWithSecret(**EndpointOut.model_validate(ep).model_dump(), secret=secret)


@router.patch("/webhooks/{ep_id}", response_model=EndpointOut)
async def update_webhook(
    ep_id: uuid.UUID, body: EndpointPatch, db: CrmDb, actor: Manager
) -> WebhookEndpoint:
    ep = await _endpoint(db, ep_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes:
        ep.name = " ".join(changes["name"].split())
    if "url" in changes:
        ep.url = check_url(changes["url"].strip())
    if "events" in changes:
        ep.events = _clean_events(changes["events"])
    if "is_active" in changes:
        ep.is_active = changes["is_active"]
        if ep.is_active:  # switched back on: start counting failures afresh
            ep.failing_since, ep.switched_off_reason = None, None
    await audit(db, actor, "webhook.updated", "webhook", ep.id, None, changes)
    await db.flush()
    await db.refresh(ep)
    return ep


@router.delete("/webhooks/{ep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(ep_id: uuid.UUID, db: CrmDb, actor: Manager) -> None:
    ep = await _endpoint(db, ep_id)
    await audit(db, actor, "webhook.deleted", "webhook", ep.id, {"name": ep.name, "url": ep.url})
    await db.delete(ep)


class SecretOut(BaseModel):
    secret: str


@router.get("/webhooks/{ep_id}/secret", response_model=SecretOut)
async def reveal_secret(ep_id: uuid.UUID, db: CrmDb, actor: Manager) -> SecretOut:
    ep = await _endpoint(db, ep_id)
    await audit(db, actor, "webhook.secret_viewed", "webhook", ep.id)
    return SecretOut(secret=decrypt(ep.secret_enc))


# ---------- the webhook log ----------
class DeliveryOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_id: uuid.UUID | None
    event_type: str
    status: str
    attempts: int
    next_try_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    last_duration_ms: int | None
    delivered_at: datetime | None
    created_at: datetime


class DeliveryDetail(DeliveryOut):
    body: str
    response_snippet: str | None


@router.post("/webhooks/{ep_id}/test", response_model=DeliveryDetail)
async def test_webhook(ep_id: uuid.UUID, db: CrmDb, actor: Manager) -> WebhookDelivery:
    """Sends a `ping` now and answers with what happened."""
    d = await W.test_send(db, await _endpoint(db, ep_id))
    await db.refresh(d)
    return d


@router.get("/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
    db: CrmDb,
    actor: Manager,
    endpoint_id: uuid.UUID | None = None,
    status_: Annotated[Literal["pending", "ok", "failed"] | None, Query(alias="status")] = None,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WebhookDelivery]:
    q = select(WebhookDelivery)
    if endpoint_id:
        q = q.where(WebhookDelivery.endpoint_id == endpoint_id)
    if status_:
        q = q.where(WebhookDelivery.status == status_)
    if before:
        q = q.where(WebhookDelivery.created_at < before)
    q = q.order_by(WebhookDelivery.created_at.desc()).limit(limit)
    return list((await db.scalars(q)).all())


async def _delivery(db, d_id: uuid.UUID) -> WebhookDelivery:
    d = await db.get(WebhookDelivery, d_id)
    if d is None:
        raise NotFound("Delivery not found")
    return d


@router.get("/deliveries/{d_id}", response_model=DeliveryDetail)
async def get_delivery(d_id: uuid.UUID, db: CrmDb, actor: Manager) -> WebhookDelivery:
    return await _delivery(db, d_id)


@router.post("/deliveries/{d_id}/resend", response_model=DeliveryOut)
async def resend_delivery(d_id: uuid.UUID, db: CrmDb, actor: Manager) -> WebhookDelivery:
    old = await _delivery(db, d_id)
    if old.event_type == "ping":
        raise Invalid("Use “Send test” to send another test")
    ep = await _endpoint(db, old.endpoint_id)
    if not ep.is_active:
        raise Invalid("Switch the webhook on first")
    d = await W.resend(db, old)
    await audit(db, actor, "webhook.resent", "webhook", ep.id, None, {"delivery": str(old.id)})
    await db.refresh(d)
    return d


# ---------- the API log ----------
class ApiLogOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    key_id: uuid.UUID
    method: str
    path: str
    status: int
    duration_ms: int
    ip: str | None
    at: datetime


@router.get("/api-log", response_model=list[ApiLogOut])
async def api_log(
    db: CrmDb,
    actor: Manager,
    key_id: uuid.UUID | None = None,
    errors_only: bool = False,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ApiRequestLog]:
    q = select(ApiRequestLog)
    if key_id:
        q = q.where(ApiRequestLog.key_id == key_id)
    if errors_only:
        q = q.where(ApiRequestLog.status >= 400)
    if before:
        q = q.where(ApiRequestLog.at < before)
    return list((await db.scalars(q.order_by(ApiRequestLog.at.desc()).limit(limit))).all())


# ---------- archives (older than 30 days) ----------
class ArchiveOut(BaseModel):
    name: str
    kind: str  # api / webhooks
    month: str  # YYYY-MM
    size: int


@router.get("/archives", response_model=list[ArchiveOut])
async def list_archives(actor: Manager) -> list[dict]:
    return LG.archives(actor.user.tenant_id)


@router.get(
    "/archives/{name}",
    response_class=FileResponse,
    responses={200: {"content": {"application/gzip": {}}}},
)
async def download_archive(name: str, db: CrmDb, actor: Manager):
    path = LG.archive_path(actor.user.tenant_id, name)
    if path is None:
        raise NotFound("Archive not found")
    await audit(db, actor, "logs.archive_downloaded", "logs", None, None, {"name": name})
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )

"""Lead ads endpoints (finishing plan, batch 5d).

Settings → Lead ads (crm.configure): connect a Facebook/Instagram Page (its id and a Page access
token, pasted for now; "Log in with Facebook" needs Versnq's Meta app and comes later), or a
Google Ads lead form (Core makes the webhook key once). Public, on the company's address:
- `GET /api/v1/lead-ads/facebook/webhook`: Meta's one-time check (hub.verify_token must be one
  of this company's Pages' verify tokens).
- `POST /api/v1/lead-ads/facebook/webhook`: "a lead arrived", refused unless signed with the
  app secret (X-Hub-Signature-256).
- `POST /api/v1/lead-ads/google/webhook`: Google's lead, refused unless its google_key is one
  of this company's keys.
"""

import json
import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core import secrets as SEC
from app.core.config import get_settings
from app.core.errors import Invalid, NotFound
from app.core.ratelimit import hit
from app.modules.auth.deps import CurrentUser, WorkspaceDep, require
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import LeadSource, LeadStage
from app.modules.leadads import service as S
from app.modules.leadads.models import LeadAdLead, LeadAdSource

router = APIRouter(prefix="/api/v1/lead-ads", tags=["lead-ads"], dependencies=CRM)
public = APIRouter(prefix="/api/v1/lead-ads", tags=["lead-ads"], dependencies=CRM)
Config = Annotated[CurrentUser, require("crm.configure")]
MAX_BODY = 1024 * 1024


class LeadAdSourceIn(BaseModel):
    provider: Literal["facebook", "google"]
    name: str = Field(min_length=1, max_length=120)
    page_id: str | None = Field(default=None, pattern=r"^[0-9]{5,30}$")  # facebook
    page_token: str | None = Field(default=None, min_length=20, max_length=1000)  # keep if empty
    app_secret: str | None = Field(default=None, min_length=16, max_length=200)  # optional
    source_id: uuid.UUID | None = None  # default: a source called "Facebook ads" / "Google ads"
    stage_id: uuid.UUID | None = None
    is_active: bool = True


class LeadAdSourceOut(BaseModel):
    id: uuid.UUID
    provider: str
    name: str
    page_id: str | None
    source_id: uuid.UUID
    stage_id: uuid.UUID | None
    is_active: bool
    own_app_secret: bool
    last_lead_at: datetime | None
    webhook_url: str
    verify_token: str | None  # facebook: paste in Meta's webhook settings
    leads: int = 0
    failed: int = 0


class LeadAdSourceCreated(LeadAdSourceOut):
    google_key: str | None = None  # google: shown once; paste as the webhook key in Google Ads


def _webhook(provider: str, slug: str) -> str:
    return f"https://{slug}.{get_settings().base_domain}/api/v1/lead-ads/{provider}/webhook"


async def _out(db, src: LeadAdSource, slug: str) -> LeadAdSourceOut:
    counts = dict(
        (
            await db.execute(
                select(LeadAdLead.status, func.count())
                .where(LeadAdLead.ad_source_id == src.id)
                .group_by(LeadAdLead.status)
            )
        ).all()
    )
    return LeadAdSourceOut(
        id=src.id,
        provider=src.provider,
        name=src.name,
        page_id=src.page_id,
        source_id=src.source_id,
        stage_id=src.stage_id,
        is_active=src.is_active,
        own_app_secret=bool(src.app_secret_enc),
        last_lead_at=src.last_lead_at,
        webhook_url=_webhook(src.provider, slug),
        verify_token=src.verify_token,
        leads=counts.get("done", 0),
        failed=counts.get("failed", 0),
    )


async def _source_for(
    db, tenant_id: uuid.UUID, provider: str, wanted: uuid.UUID | None
) -> uuid.UUID:
    if wanted:
        src = await db.get(LeadSource, wanted)
        if src is None or not src.is_active:
            raise Invalid("Choose an active source")
        return src.id
    name = "Facebook ads" if provider == "facebook" else "Google ads"
    found = await db.scalar(select(LeadSource).where(func.lower(LeadSource.name) == name.lower()))
    if found:
        return found.id
    position = (await db.scalar(select(func.max(LeadSource.position)))) or 0
    src = LeadSource(
        id=uuid.uuid4(), tenant_id=tenant_id, name=name, position=position + 1, is_active=True
    )
    db.add(src)
    await db.flush()
    return src.id


# ---------- Settings → Lead ads ----------
@router.get("/sources", response_model=list[LeadAdSourceOut])
async def list_sources(db: CrmDb, actor: Config, ws: WorkspaceDep) -> list[LeadAdSourceOut]:
    rows = (await db.scalars(select(LeadAdSource).order_by(LeadAdSource.created_at))).all()
    return [await _out(db, r, ws.slug) for r in rows]


@router.post("/sources", response_model=LeadAdSourceCreated, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: LeadAdSourceIn, db: CrmDb, actor: Config, ws: WorkspaceDep
) -> LeadAdSourceCreated:
    src = LeadAdSource(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        provider=body.provider,
        name=body.name.strip(),
        is_active=body.is_active,
        stage_id=body.stage_id,
    )
    if body.stage_id and await db.get(LeadStage, body.stage_id) is None:
        raise Invalid("Choose a stage")
    src.source_id = await _source_for(db, actor.user.tenant_id, body.provider, body.source_id)
    google_key = None
    if body.provider == "facebook":
        if not body.page_id or not body.page_token:
            raise Invalid("Enter the Page id and a Page access token")
        if await db.scalar(select(LeadAdSource.id).where(LeadAdSource.page_id == body.page_id)):
            raise Invalid("This Page is already connected")
        src.page_id, src.page_token_enc = body.page_id, SEC.encrypt(body.page_token)
        src.app_secret_enc = SEC.encrypt(body.app_secret) if body.app_secret else None
        src.verify_token = secrets.token_urlsafe(24)
        try:
            await S.graph(src).check_page(body.page_id)
        except RuntimeError as e:
            raise Invalid(str(e), code="lead_ads_failed") from None
    else:
        google_key = secrets.token_urlsafe(24)
        src.key_hash = S.key_hash(google_key)
    db.add(src)
    await db.flush()
    await audit(
        db,
        actor,
        "lead_ads.connected",
        "lead_ad_source",
        src.id,
        after={"provider": src.provider, "name": src.name},
    )
    out = await _out(db, src, ws.slug)
    return LeadAdSourceCreated(**out.model_dump(), google_key=google_key)


@router.patch("/sources/{source_id}", response_model=LeadAdSourceOut)
async def update_source(
    source_id: uuid.UUID, body: LeadAdSourceIn, db: CrmDb, actor: Config, ws: WorkspaceDep
) -> LeadAdSourceOut:
    src = await db.get(LeadAdSource, source_id)
    if src is None or src.provider != body.provider:
        raise NotFound("Not found")
    src.name, src.is_active, src.stage_id = body.name.strip(), body.is_active, body.stage_id
    src.source_id = await _source_for(db, actor.user.tenant_id, body.provider, body.source_id)
    if body.page_token:
        src.page_token_enc = SEC.encrypt(body.page_token)
    if body.app_secret:
        src.app_secret_enc = SEC.encrypt(body.app_secret)
    await db.flush()
    await audit(db, actor, "lead_ads.updated", "lead_ad_source", src.id)
    return await _out(db, src, ws.slug)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: uuid.UUID, db: CrmDb, actor: Config) -> None:
    src = await db.get(LeadAdSource, source_id)
    if src is None:
        raise NotFound("Not found")
    await audit(db, actor, "lead_ads.removed", "lead_ad_source", src.id)
    await db.delete(src)


# ---------- from Meta ----------
@public.get("/facebook/webhook", response_class=PlainTextResponse)
async def facebook_verify(
    db: CrmDb,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> str:
    """Meta's one-time check when the webhook is set up: echo the challenge for our token."""
    if mode != "subscribe" or not token or not challenge:
        raise NotFound("Not found")
    tokens = (
        await db.scalars(
            select(LeadAdSource.verify_token).where(
                LeadAdSource.provider == "facebook", LeadAdSource.verify_token.is_not(None)
            )
        )
    ).all()
    if not any(secrets.compare_digest(token, t) for t in tokens):
        raise NotFound("Not found")
    return challenge[:200]


@public.post("/facebook/webhook", status_code=status.HTTP_200_OK)
async def facebook_webhook(request: Request, db: CrmDb) -> dict:
    """UNVERIFIED shape (Meta "page" object, "leadgen" field):
    {"object": "page", "entry": [{"id": <page id>, "changes": [{"field": "leadgen",
    "value": {"leadgen_id", "page_id", "form_id", "ad_id", "adgroup_id", "created_time"}}]}]}"""
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise NotFound("Not found")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise NotFound("Not found") from None
    signature = request.headers.get("x-hub-signature-256")
    accepted = 0
    for entry in body.get("entry") or [] if isinstance(body, dict) else []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if change.get("field") != "leadgen" or not value.get("leadgen_id"):
                continue
            page_id = str(value.get("page_id") or entry.get("id") or "")
            src = await db.scalar(
                select(LeadAdSource).where(
                    LeadAdSource.provider == "facebook", LeadAdSource.page_id == page_id
                )
            )
            # The signature covers the whole body, made with the app's secret: checked before
            # anything in it is used.
            if src is None or not S.meta_signature_ok(S.app_secret(src), raw, signature):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Bad signature")
            if not src.is_active:
                continue
            row = await S.remember(
                db,
                src,
                str(value["leadgen_id"]),
                {
                    k: str(value[k])[:200]
                    for k in ("form_id", "ad_id", "adgroup_id")
                    if value.get(k)
                },
            )
            if row is not None:
                await S.process(db, src, row)
                accepted += 1
    return {"accepted": accepted}


# ---------- from Google ----------
@public.post("/google/webhook", status_code=status.HTTP_200_OK)
async def google_webhook(request: Request, db: CrmDb, ws: WorkspaceDep) -> dict:
    """UNVERIFIED shape (Google Ads lead form webhook): {"lead_id", "user_column_data":
    [{"column_id", "column_name", "string_value"}], "google_key", "campaign_id", "form_id",
    "is_test", …}. Google expects a 200 answer."""
    if not await hit(f"rl:leadads:google:{ws.id}", 600, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise NotFound("Not found")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise NotFound("Not found") from None
    key = str(body.get("google_key") or "") if isinstance(body, dict) else ""
    src = await db.scalar(
        select(LeadAdSource).where(
            LeadAdSource.provider == "google", LeadAdSource.key_hash == S.key_hash(key)
        )
    )
    if not key or src is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unknown key")
    if not src.is_active or not body.get("lead_id"):
        return {"accepted": 0}
    payload = {
        k: body[k]
        for k in (
            "user_column_data",
            "campaign_id",
            "adgroup_id",
            "creative_id",
            "form_id",
            "gcl_id",
            "is_test",
        )
        if k in body
    }
    row = await S.remember(db, src, str(body["lead_id"]), payload)
    if row is None:
        return {"accepted": 0}
    await S.process(db, src, row)
    return {"accepted": 1}

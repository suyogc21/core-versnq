"""Web forms and webhooks (capture sources).

Admins create a capture source and get a secret key once. A website posts JSON or a normal
form to `POST /api/v1/capture/<key>` on the company's own web address. The post goes through
the same intake rules as every other lead. Protection: the secret key (stored hashed), a rate
limit per key and per visitor, a size limit, and a hidden spam-trap field (`_gotcha`): if a
bot fills it, the post is accepted and silently dropped. The answer never reveals whether the
person already exists.
"""

import hashlib
import json
import secrets
import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import Conflict, DomainError, Invalid, NotFound
from app.core.ratelimit import hit
from app.modules.auth.deps import CurrentUser, WorkspaceDep, require
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm import mapping as MP
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.leads import lead_fields
from app.modules.crm.models import CaptureSource, LeadSource, LeadStage
from app.modules.settings.models import TenantSettings

router = APIRouter(prefix="/api/v1", tags=["capture"], dependencies=CRM)
public = APIRouter(prefix="/api/v1/capture", tags=["capture"], dependencies=CRM)
Configurer = Annotated[CurrentUser, require("crm.configure")]

MAX_BODY = 64 * 1024
HONEYPOT = "_gotcha"
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _new_key() -> str:
    return "vqf_" + secrets.token_urlsafe(24)


# ---------- settings ----------
class CaptureSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    source_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    # extra incoming names → target ("cf.<key>" or a built-in name such as "phone")
    field_map: dict[str, str] = Field(default={}, max_length=100)
    consent_text: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class CaptureSourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    source_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    field_map: dict[str, str] | None = Field(default=None, max_length=100)
    consent_text: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class CaptureSourceOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    source_id: uuid.UUID
    stage_id: uuid.UUID | None
    key_hint: str
    field_map: dict
    consent_text: str | None
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime


class CaptureSourceWithKey(CaptureSourceOut):
    key: str  # shown once


async def _check(db, src: CaptureSource) -> None:
    src.name = " ".join(src.name.split())
    with db.no_autoflush:  # check before the new name reaches the database
        clash = await db.scalar(
            select(CaptureSource.id).where(
                func.lower(CaptureSource.name) == src.name.lower(), CaptureSource.id != src.id
            )
        )
    if clash:
        raise Conflict(f"A form called '{src.name}' already exists")
    source = await db.get(LeadSource, src.source_id)
    if source is None or not source.is_active:
        raise Invalid("Choose an active source")
    if src.stage_id:
        stage = await db.get(LeadStage, src.stage_id)
        if stage is None or not stage.is_open:
            raise Invalid("New leads must start in an open stage")
    defs = await lead_fields(db)
    for incoming, target in src.field_map.items():
        if not incoming.strip() or len(incoming) > 100:
            raise Invalid("Field names must be 1–100 characters")
        ok = target in MP.BUILTIN_TARGETS or (target.startswith("cf.") and target[3:] in defs)
        if not ok:
            raise Invalid(f"'{target}' is not a field you can fill from a form")


@router.get("/capture-sources", response_model=list[CaptureSourceOut])
async def list_capture_sources(db: CrmDb, actor: Configurer) -> list[CaptureSource]:
    rows = await db.scalars(select(CaptureSource).order_by(CaptureSource.created_at))
    return list(rows.all())


@router.post(
    "/capture-sources", response_model=CaptureSourceWithKey, status_code=status.HTTP_201_CREATED
)
async def create_capture_source(
    body: CaptureSourceIn, db: CrmDb, actor: Configurer
) -> CaptureSourceWithKey:
    key = _new_key()
    src = CaptureSource(
        tenant_id=actor.user.tenant_id,
        key_hash=_hash(key),
        key_hint=key[:8],
        created_by_user_id=actor.user.id,
        **body.model_dump(),
    )
    src.id = uuid.uuid4()
    await _check(db, src)
    db.add(src)
    await db.flush()
    await db.refresh(src)
    await audit(
        db, actor, "capture_source.created", "capture_source", src.id, None, {"name": src.name}
    )
    return CaptureSourceWithKey(**CaptureSourceOut.model_validate(src).model_dump(), key=key)


async def _get(db, src_id: uuid.UUID) -> CaptureSource:
    src = await db.get(CaptureSource, src_id)
    if src is None:
        raise NotFound("Form not found")
    return src


@router.patch("/capture-sources/{src_id}", response_model=CaptureSourceOut)
async def update_capture_source(
    src_id: uuid.UUID, body: CaptureSourcePatch, db: CrmDb, actor: Configurer
) -> CaptureSource:
    src = await _get(db, src_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is not None or key in ("stage_id", "consent_text"):
            setattr(src, key, value)
    await _check(db, src)
    await audit(db, actor, "capture_source.updated", "capture_source", src.id, None, changes)
    await db.flush()
    await db.refresh(src)
    return src


@router.post("/capture-sources/{src_id}/new-key", response_model=CaptureSourceWithKey)
async def rotate_capture_key(
    src_id: uuid.UUID, db: CrmDb, actor: Configurer
) -> CaptureSourceWithKey:
    """The old key stops working at once."""
    src = await _get(db, src_id)
    key = _new_key()
    src.key_hash, src.key_hint = _hash(key), key[:8]
    await audit(db, actor, "capture_source.key_rotated", "capture_source", src.id)
    await db.flush()
    await db.refresh(src)
    return CaptureSourceWithKey(**CaptureSourceOut.model_validate(src).model_dump(), key=key)


@router.delete("/capture-sources/{src_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capture_source(src_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    src = await _get(db, src_id)
    await db.delete(src)
    await audit(db, actor, "capture_source.deleted", "capture_source", src_id, {"name": src.name})


# ---------- the public endpoint ----------
def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _read(request: Request) -> dict[str, list[str]]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise Invalid("The form is too large")
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind == "application/json":
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise Invalid("Send valid JSON") from None
        if not isinstance(data, dict):
            raise Invalid("Send a JSON object")
        out: dict[str, list[str]] = {}
        for k, v in data.items():
            items = v if isinstance(v, list) else [v]
            out[str(k)] = ["" if i is None else str(i) for i in items if not isinstance(i, dict)]
        return out
    if kind in ("application/x-www-form-urlencoded", "text/plain", ""):
        return {k: v for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
    raise Invalid("Send JSON or a normal form post")


@public.options("/{key}")
async def capture_preflight(key: str) -> Response:
    """Lets browsers on any website post to the form (CORS preflight)."""
    return Response(status_code=204, headers=CORS)


@public.post("/{key}", status_code=status.HTTP_202_ACCEPTED)
async def capture(key: str, request: Request, ws: WorkspaceDep, db: CrmDb) -> JSONResponse:
    """Public: a website sends a lead. Answers 202 when accepted (new or existing person)."""
    ip = _client_ip(request)
    if not await hit(f"rl:capture:{key[:40]}:{ip}", 20, 60) or not await hit(
        f"rl:capture:{key[:40]}", 1000, 3600
    ):
        return JSONResponse({"detail": "Too many submissions. Try again later."}, 429, headers=CORS)
    try:
        data = await _read(request)
        if any(v.strip() for v in data.get(HONEYPOT, [])):
            return JSONResponse({"ok": True}, 202, headers=CORS)  # a bot: accept and drop
        src = await db.scalar(select(CaptureSource).where(CaptureSource.key_hash == _hash(key)))
        if src is None or not src.is_active:
            raise NotFound("Unknown or switched-off form key")
        await _capture(db, ws.id, src, data, request, ip)
    except DomainError as e:
        return JSONResponse({"detail": e.detail}, e.status_code, headers=CORS)
    return JSONResponse({"ok": True}, 202, headers=CORS)


async def _capture(db, tenant_id, src: CaptureSource, data, request: Request, ip: str) -> None:
    defs = await lead_fields(db)
    targets: dict[str, list[str]] = {}
    extras: list[str] = []
    attribution: dict[str, str] = {}
    for name, values in data.items():
        if name == HONEYPOT:
            continue
        target = src.field_map.get(name)
        if target is None:
            normal = MP._norm(name)
            target = next(
                (t for t in MP.BUILTIN_TARGETS if MP._norm(t) == normal),
                MP._ALIASES.get(normal) if MP._ALIASES.get(normal) in MP.BUILTIN_TARGETS else None,
            )
            if target is None and normal.replace(" ", "_") in defs:
                target = f"cf.{normal.replace(' ', '_')}"
        if target:
            targets.setdefault(target, []).extend(values)
        elif normal_key := MP._norm(name).replace(" ", "_"):
            if normal_key in MP.ATTRIBUTION_KEYS:
                attribution[normal_key] = (values[0] if values else "")[:500]
            elif any(v.strip() for v in values):
                extras.append(f"{name[:60]}: {', '.join(values)[:500]}")
    p = MP.parse(targets, defs)
    message = "\n".join(p.message_parts + extras) or None
    settings = await db.get(TenantSettings, tenant_id)
    policy = settings.duplicate_policy if settings else "update"

    def incoming(with_custom: bool) -> I.Incoming:
        return I.Incoming(
            identities=p.identities,
            source_id=src.source_id,
            created_via="form",
            fields=p.fields,
            custom_fields=p.custom_fields if with_custom else {},
            stage_id=src.stage_id,
            origin="inbound",
            owner=I.RULES,
            consents=p.consents,
            consent_wording=src.consent_text,
            consent_evidence={
                "ip": ip,
                "user_agent": request.headers.get("user-agent", "")[:300],
                "page_url": attribution.get("page_url") or request.headers.get("referer", "")[:500],
            },
            external=(f"capture:{src.id}", p.external_id) if p.external_id else None,
            message=message
            if with_custom
            else "\n".join(
                filter(None, [message, *(f"{k}: {v}" for k, v in p.custom_fields.items())])
            ),
            attribution=attribution,
            enforce_required=False,
            via_label=f"the {src.name} form",
        )

    try:
        async with db.begin_nested():
            await I.intake(db, tenant_id, incoming(True), policy=policy)
    except DomainError:
        if not p.custom_fields:
            raise
        # A custom answer broke a rule (linked dropdown, unique value): keep the lead and put
        # the answers in the message so nothing is lost. A bad phone/email fails again here.
        async with db.begin_nested():
            await I.intake(db, tenant_id, incoming(False), policy=policy)
    src.last_used_at = L.now()

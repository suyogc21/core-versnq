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
import re
import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.client_ip import client_ip
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


# ---------- the form builder (real forms, 0034) ----------
IDENTITY = ("email", "phone", "whatsapp")
NOT_ON_FORMS = {"external_id", "campaign", "consent_email", "consent_whatsapp",
                *(k for k in MP.BUILTIN_TARGETS if k.startswith("utm_"))}  # fmt: skip
INPUT = {"email": "email", "phone": "tel", "whatsapp": "tel", "website": "url",
         "linkedin": "url", "message": "textarea"}  # fmt: skip
CUSTOM_INPUT = {"text": "text", "number": "number", "date": "date", "email": "email",
                "phone": "tel", "url": "url", "select": "select",
                "multi_select": "multi_select"}  # fmt: skip


class FormField(BaseModel):
    target: str = Field(min_length=1, max_length=63)  # a built-in name, or "cf.<key>"
    label: str = Field(min_length=1, max_length=120)
    required: bool = False


class FormSpec(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    intro: str | None = Field(default=None, max_length=1000)
    button: str = Field(default="Send", min_length=1, max_length=40)
    fields: list[FormField] = Field(min_length=1, max_length=30)
    ask_consent: list[Literal["email", "whatsapp"]] = Field(default=[], max_length=2)
    thank_you: str = Field(default="Thank you. We'll be in touch soon.", min_length=1,
                           max_length=500)  # fmt: skip
    redirect_url: str | None = Field(default=None, max_length=500, pattern=r"^https://\S+$")


# ---------- settings ----------
class CaptureSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    source_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    # extra incoming names → target ("cf.<key>" or a built-in name such as "phone")
    field_map: dict[str, str] = Field(default={}, max_length=100)
    consent_text: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    form: FormSpec | None = None
    hosted: bool = False
    brand_id: uuid.UUID | None = None  # several brands: its leads get this brand, its page its look


class CaptureSourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    source_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    field_map: dict[str, str] | None = Field(default=None, max_length=100)
    consent_text: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    form: FormSpec | None = None
    hosted: bool | None = None
    brand_id: uuid.UUID | None = None


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
    form: FormSpec | None = None
    hosted: bool = False
    public_id: str | None = None  # the hosted page is /f/<public_id>
    brand_id: uuid.UUID | None = None
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
    if src.form:
        _check_form(src.form, defs)
    if src.brand_id:
        from app.modules.brands.models import Brand

        brand = await db.get(Brand, src.brand_id)
        if brand is None or not brand.is_active:
            raise Invalid("Choose an active brand", code="brand_invalid")
    if src.hosted:
        if not src.form:
            raise Invalid("Build the form before switching its page on")
        if not src.public_id:
            src.public_id = secrets.token_urlsafe(9)


def _check_form(form: dict, defs: dict) -> None:
    targets = [f["target"] for f in form["fields"]]
    if len(set(targets)) != len(targets):
        raise Invalid("A field is on the form twice")
    for t in targets:
        builtin = t in MP.BUILTIN_TARGETS and t not in NOT_ON_FORMS
        custom = t.startswith("cf.") and t[3:] in defs and defs[t[3:]].type in CUSTOM_INPUT
        if not (builtin or custom):
            raise Invalid(f"'{t}' can't be a question on a form")
    if not any(t in IDENTITY for t in targets):
        raise Invalid("Add an email, phone or WhatsApp field, so the lead can be reached")


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
        if value is not None or key in ("stage_id", "consent_text", "form", "brand_id"):
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
    return client_ip(request)


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
            brand_id=src.brand_id,
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


# ---------- the hosted page (real forms, 0034) ----------
forms_public = APIRouter(prefix="/api/v1/forms", tags=["capture"], dependencies=CRM)
EMAILISH = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PageField(BaseModel):
    name: str  # what the page sends back
    label: str
    input: str  # text, email, tel, url, number, date, textarea, select, multi_select
    required: bool
    options: list[str] = []


class PageCompany(BaseModel):
    name: str
    logo_url: str | None = None
    primary_color: str | None = None


class FormPageOut(BaseModel):
    closed: bool = False
    company: PageCompany
    title: str = ""
    intro: str | None = None
    button: str = "Send"
    fields: list[PageField] = []
    consent_text: str | None = None
    ask_consent: list[str] = []


class FormSentOut(BaseModel):
    ok: bool = True
    thank_you: str
    redirect_url: str | None = None


async def _hosted(db, public_id: str) -> CaptureSource:
    src = await db.scalar(select(CaptureSource).where(CaptureSource.public_id == public_id))
    if src is None or not src.hosted or not src.form:
        raise NotFound("Form not found")
    return src


def _page_fields(form: dict, defs: dict) -> list[PageField]:
    out = []
    for f in form["fields"]:
        t = f["target"]
        if t.startswith("cf."):
            d = defs.get(t[3:])
            if d is None:
                continue  # the custom field was removed since: leave the question out
            opts = [o.get("label") or o["value"] for o in d.options or [] if not o.get("parent")]
            kind = CUSTOM_INPUT.get(d.type, "text")
            out.append(PageField(name=d.key, label=f["label"], input=kind,
                                 required=f["required"], options=opts))  # fmt: skip
        else:
            out.append(PageField(name=t, label=f["label"], input=INPUT.get(t, "text"),
                                 required=f["required"]))  # fmt: skip
    return out


@forms_public.get("/{public_id}", response_model=FormPageOut)
async def form_page(public_id: str, ws: WorkspaceDep, db: CrmDb) -> FormPageOut:
    """Public: what the hosted page shows."""
    src = await _hosted(db, public_id)
    settings = await db.get(TenantSettings, ws.id)
    brand = (settings.branding if settings else None) or {}
    company = PageCompany(name=ws.name, logo_url=brand.get("logo_url"),
                          primary_color=brand.get("primary_color"))  # fmt: skip
    if src.brand_id:  # the form's brand: its name, logo and colour (batch 4)
        from app.modules.brands.models import Brand

        own = await db.get(Brand, src.brand_id)
        if own is not None and own.is_active:
            company = PageCompany(name=own.name, logo_url=own.logo_url or company.logo_url,
                                  primary_color=own.colour or company.primary_color)  # fmt: skip
    if not src.is_active:
        return FormPageOut(closed=True, company=company)
    form = src.form
    return FormPageOut(
        company=company, title=form["title"], intro=form.get("intro"), button=form["button"],
        fields=_page_fields(form, await lead_fields(db)), consent_text=src.consent_text,
        ask_consent=form.get("ask_consent", []),
    )  # fmt: skip


@forms_public.post("/{public_id}", response_model=FormSentOut, status_code=status.HTTP_201_CREATED)
async def send_form(public_id: str, request: Request, ws: WorkspaceDep, db: CrmDb) -> FormSentOut:
    """Public: someone sends the hosted form. Required answers are checked here too; the lead
    then goes through the same path as every other form (duplicates, routing, timeline)."""
    ip = _client_ip(request)
    if not await hit(f"rl:form:{public_id[:20]}:{ip}", 20, 60) or not await hit(
        f"rl:form:{public_id[:20]}", 1000, 3600
    ):
        raise Invalid("Too many submissions. Try again later.", code="rate_limited")
    src = await _hosted(db, public_id)
    if not src.is_active:
        raise Invalid("This form is closed", code="form_closed")
    data = await _read(request)
    form = src.form
    if any(v.strip() for v in data.get(HONEYPOT, [])):
        return FormSentOut(thank_you=form["thank_you"], redirect_url=form.get("redirect_url"))
    fields = _page_fields(form, await lead_fields(db))
    errors: dict[str, str] = {}
    for f in fields:
        values = [v.strip() for v in data.get(f.name, []) if v.strip()]
        if f.required and not values:
            errors[f.name] = "Please fill this in"
        elif values and f.input == "email" and not EMAILISH.match(values[0]):
            errors[f.name] = "Enter a valid email"
        elif values and f.options and any(v not in f.options for v in values):
            errors[f.name] = "Choose one of the options"
    if not errors and not any(
        v.strip() for f in fields if f.name in IDENTITY for v in data.get(f.name, [])
    ):
        errors["_form"] = "Give an email or phone number so we can reach you"
    if errors:
        raise Invalid("Please check the form", {"fields": errors}, code="form_invalid")
    allowed = (
        {f.name for f in fields}
        | {*MP.ATTRIBUTION_KEYS}
        | {k for k in MP.BUILTIN_TARGETS if k.startswith("utm_")}
    )
    kept = {k: v for k, v in data.items() if k in allowed}
    for channel in form.get("ask_consent", []):
        kept[f"consent_{channel}"] = ["yes" if MP.yes_no(
            (data.get(f"consent_{channel}") or [""])[0]) else "no"]  # fmt: skip
    await _capture(db, ws.id, src, kept, request, ip)
    return FormSentOut(thank_you=form["thank_you"], redirect_url=form.get("redirect_url"))

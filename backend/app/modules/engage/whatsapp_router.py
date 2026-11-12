"""The official WhatsApp number (step 10b, Decision log #41): connect it, its templates, its
settings (unknown number → lead, STOP words, the autoresponder), sending from a lead or the
inbox, and Meta's webhook (signed) plus a test entry point outside production."""

import json
import re
import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import secrets as SEC
from app.core.config import get_settings
from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import CurrentUser, TenantDb, WorkspaceDep, require
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import CustomFieldDefinition, LeadSource
from app.modules.engage import render as R
from app.modules.engage import whatsapp as WA
from app.modules.engage.models import WhatsAppAccount, WhatsAppTemplate
from app.modules.settings.models import TenantSettings

router = APIRouter(prefix="/api/v1", tags=["whatsapp"], dependencies=CRM)
public = APIRouter(prefix="/api/v1", tags=["whatsapp"])
Manager = Annotated[CurrentUser, require("whatsapp.manage")]
Replier = Annotated[CurrentUser, require("inbox.reply")]


# ---------- shapes ----------
class WaAccountIn(BaseModel):
    phone_number_id: str = Field(pattern=r"^\d{5,30}$")
    waba_id: str = Field(pattern=r"^\d{5,30}$")
    access_token: str | None = Field(default=None, max_length=1000)  # needed to connect
    app_secret: str | None = Field(default=None, max_length=200)


class WaAccountOut(BaseModel):
    connected: bool
    test_mode: bool
    phone_number_id: str | None = None
    waba_id: str | None = None
    display_number: str | None = None
    verified_name: str | None = None
    status: str | None = None
    last_error: str | None = None
    quality_rating: str | None = None
    messaging_limit: str | None = None
    health_checked_at: datetime | None = None
    webhook_url: str | None = None
    verify_token: str | None = None


class WaToggle(BaseModel):
    on: bool = False
    text: str = Field(default="", max_length=1000)


class WaSettingsIO(BaseModel):
    create_leads: bool = True
    source_id: uuid.UUID | None = None
    stop_words: list[str] = Field(default_factory=list, max_length=30)
    welcome: WaToggle = WaToggle()
    away: WaToggle = WaToggle()
    reminder_template_id: uuid.UUID | None = None  # payment reminders on WhatsApp (utility)


class WaTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}(_[A-Z]{2})?$")
    category: Literal["marketing", "utility"]
    body: str = Field(min_length=1, max_length=1024)
    footer: str | None = Field(default=None, max_length=60)


class WaTemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    language: str
    category: str
    body: str
    footer: str | None
    status: str
    reason: str | None
    created_at: datetime


class WaSendIn(BaseModel):
    template_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=4096)


class WaSentOut(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    status: str


class WaWebhookResult(BaseModel):
    kept: int


def _base(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


def _account_out(acct: WhatsAppAccount | None, request: Request) -> WaAccountOut:
    if acct is None:
        return WaAccountOut(connected=False, test_mode=WA.test_mode())
    return WaAccountOut(
        connected=True,
        test_mode=WA.test_mode(),
        phone_number_id=acct.phone_number_id,
        waba_id=acct.waba_id,
        display_number=acct.display_number,
        verified_name=acct.verified_name,
        status=acct.status,
        last_error=acct.last_error,
        quality_rating=acct.quality_rating,
        messaging_limit=acct.messaging_limit,
        health_checked_at=acct.health_checked_at,
        webhook_url=f"{_base(request)}/api/v1/whatsapp/webhook",
        verify_token=acct.verify_token,
    )


def _tpl_out(t: WhatsAppTemplate) -> WaTemplateOut:
    return WaTemplateOut(
        id=t.id,
        name=t.name,
        language=t.language,
        category=t.category,
        body=t.body,
        footer=t.footer,
        status=t.status,
        reason=t.reason,
        created_at=t.created_at,
    )


# ---------- the number ----------
@router.get("/whatsapp/account", response_model=WaAccountOut)
async def get_account(request: Request, db: CrmDb, actor: Manager) -> WaAccountOut:
    return _account_out(await WA.account(db), request)


@router.put("/whatsapp/account", response_model=WaAccountOut)
async def connect(request: Request, body: WaAccountIn, db: CrmDb, actor: Manager) -> WaAccountOut:
    """Connect (or update) the company's number with its Meta keys. Checked with Meta first."""
    acct = await WA.account(db)
    if acct is None and not (body.access_token and body.app_secret):
        raise Invalid("Enter the access token and the app secret")
    fresh = acct is None
    if fresh:
        acct = WhatsAppAccount(
            id=uuid.uuid4(),
            tenant_id=actor.user.tenant_id,
            verify_token=secrets.token_urlsafe(24),
        )
    acct.phone_number_id, acct.waba_id = body.phone_number_id, body.waba_id
    if body.access_token:
        acct.access_token_enc = SEC.encrypt(body.access_token.strip())
    if body.app_secret:
        acct.app_secret_enc = SEC.encrypt(body.app_secret.strip())
    await WA.refresh_health(db, acct)
    if acct.status == "error":
        raise Invalid(acct.last_error or "WhatsApp refused these keys")
    if fresh:
        db.add(acct)
    await db.flush()
    await audit(
        db, actor, "whatsapp.connected", "whatsapp", acct.id, None, {"number": acct.display_number}
    )
    return _account_out(acct, request)


@router.post("/whatsapp/account/check", response_model=WaAccountOut)
async def check(request: Request, db: CrmDb, actor: Manager) -> WaAccountOut:
    """Quality rating and daily limit, fresh from Meta."""
    acct = await WA.require_account(db)
    await WA.refresh_health(db, acct)
    return _account_out(acct, request)


# ---------- settings ----------
@router.get("/whatsapp/settings", response_model=WaSettingsIO)
async def get_settings_(db: CrmDb, actor: Manager) -> WaSettingsIO:
    return WaSettingsIO(**WA.settings_of(await db.get(TenantSettings, actor.user.tenant_id)))


@router.put("/whatsapp/settings", response_model=WaSettingsIO)
async def put_settings(body: WaSettingsIO, db: CrmDb, actor: Manager) -> WaSettingsIO:
    if body.source_id:
        src = await db.get(LeadSource, body.source_id)
        if src is None or not src.is_active:
            raise Invalid("Choose an active source")
    words = []
    for w in body.stop_words:
        w = re.sub(r"\s+", " ", w).strip()
        if w and w.casefold() not in {x.casefold() for x in words}:
            words.append(w[:30])
    if not words:
        raise Invalid("Keep at least one STOP word")
    if body.reminder_template_id:
        tpl = await db.get(WhatsAppTemplate, body.reminder_template_id)
        if tpl is None or tpl.category != "utility":
            raise Invalid("Payment reminders need a utility template")
    keys = set(
        (
            await db.scalars(
                select(CustomFieldDefinition.key).where(CustomFieldDefinition.entity == "lead")
            )
        ).all()
    )
    for t in (body.welcome, body.away):
        R.check(t.text, keys)
        if t.on and not t.text.strip():
            raise Invalid("Write the automatic reply, or switch it off")
    ts = await db.get(TenantSettings, actor.user.tenant_id)
    before = dict(ts.whatsapp or {})
    ts.whatsapp = json.loads(body.model_copy(update={"stop_words": words}).model_dump_json())
    await db.flush()
    await audit(db, actor, "whatsapp.settings", "settings", None, before, ts.whatsapp)
    return WaSettingsIO(**WA.settings_of(ts))


# ---------- templates ----------
@router.get("/whatsapp/templates", response_model=list[WaTemplateOut])
async def list_templates(db: CrmDb, actor: Replier) -> list[WaTemplateOut]:
    rows = (await db.scalars(select(WhatsAppTemplate).order_by(WhatsAppTemplate.name))).all()
    return [_tpl_out(t) for t in rows]


@router.post(
    "/whatsapp/templates", response_model=WaTemplateOut, status_code=status.HTTP_201_CREATED
)
async def create_template(body: WaTemplateIn, db: CrmDb, actor: Manager) -> WaTemplateOut:
    """Written with our variables; sent to Meta for approval straight away."""
    acct = await WA.require_account(db)
    name = re.sub(r"[^a-z0-9]+", "_", body.name.strip().lower()).strip("_")
    if not WA.NAME.fullmatch(name):
        raise Invalid("Use letters and numbers for the template name")
    keys = set(
        (
            await db.scalars(
                select(CustomFieldDefinition.key).where(CustomFieldDefinition.entity == "lead")
            )
        ).all()
    )
    R.check(body.body, keys, WA.INVOICE_VARS)
    text, _ = WA.meta_body(body.body)
    if text.strip().startswith("{{") or text.strip().endswith("}}"):
        raise Invalid("WhatsApp doesn't allow a template to start or end with a variable")
    if await db.scalar(
        select(WhatsAppTemplate.id).where(
            WhatsAppTemplate.name == name, WhatsAppTemplate.language == body.language
        )
    ):
        raise Invalid(f"There is already a template called {name} in this language")
    tpl = WhatsAppTemplate(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        name=name,
        language=body.language,
        category=body.category,
        body=body.body.strip(),
        footer=(body.footer or "").strip() or None,
        created_by_user_id=actor.user.id,
    )
    await WA.submit(db, acct, tpl)
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    await audit(
        db, actor, "whatsapp.template_created", "whatsapp_template", tpl.id, None, {"name": name}
    )
    return _tpl_out(tpl)


@router.post("/whatsapp/templates/{tpl_id}/refresh", response_model=WaTemplateOut)
async def refresh_template(tpl_id: uuid.UUID, db: CrmDb, actor: Manager) -> WaTemplateOut:
    tpl = await db.get(WhatsAppTemplate, tpl_id)
    if tpl is None:
        raise NotFound("Template not found")
    await WA.refresh_template(db, await WA.require_account(db), tpl)
    return _tpl_out(tpl)


@router.delete("/whatsapp/templates/{tpl_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(tpl_id: uuid.UUID, db: CrmDb, actor: Manager) -> None:
    """Removed from Core (messages already sent keep their text). Remove it in Meta's
    WhatsApp Manager too if it should go there."""
    tpl = await db.get(WhatsAppTemplate, tpl_id)
    if tpl is None:
        raise NotFound("Template not found")
    await db.delete(tpl)
    await audit(
        db, actor, "whatsapp.template_deleted", "whatsapp_template", tpl_id, {"name": tpl.name}
    )


# ---------- sending ----------
@router.post(
    "/leads/{lead_id}/whatsapp", response_model=WaSentOut, status_code=status.HTTP_201_CREATED
)
async def send_to_lead(lead_id: uuid.UUID, body: WaSendIn, db: CrmDb, actor: Replier) -> WaSentOut:
    """From the company number: a template (always allowed if approved and the person may get
    it) or free text (only inside the 24-hour window)."""
    lead = await L.get_visible(db, actor, lead_id)
    tpl = None
    if body.template_id:
        tpl = await db.get(WhatsAppTemplate, body.template_id)
        if tpl is None:
            raise NotFound("Template not found")
    elif not (body.text or "").strip():
        raise Invalid("Choose a template or write a message")
    msg = await WA.send(db, lead, text=body.text, template=tpl, actor=actor)
    return WaSentOut(conversation_id=msg.conversation_id, message_id=msg.id, status=msg.status)


# ---------- Meta's webhook ----------
async def _acct_for(db) -> WhatsAppAccount:
    acct = await WA.account(db)
    if acct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return acct


@public.get("/whatsapp/webhook", response_class=PlainTextResponse)
async def verify(
    db: TenantDb,
    ws: WorkspaceDep,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge", max_length=200)] = None,
) -> str:
    """Meta checks the callback address once, when the company sets it up."""
    acct = await _acct_for(db)
    if mode != "subscribe" or not token or not secrets.compare_digest(token, acct.verify_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wrong verify token")
    return challenge or ""


@public.post("/whatsapp/webhook", response_model=WaWebhookResult)
async def webhook(request: Request, db: TenantDb, ws: WorkspaceDep) -> WaWebhookResult:
    """Messages, delivery receipts and template decisions from Meta, signed with the company's
    app secret. Anything unsigned or wrongly signed is refused."""
    acct = await _acct_for(db)
    raw = await request.body()
    if len(raw) > 2 * 1024 * 1024 or not WA.signature_ok(
        acct, raw, request.headers.get("x-hub-signature-256")
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise Invalid("Not JSON") from None
    return WaWebhookResult(kept=await WA.handle(db, acct, payload))


@router.post("/whatsapp/test-webhook", response_model=WaWebhookResult)
async def test_webhook(
    request: Request, db: CrmDb, actor: Annotated[CurrentUser, require("settings.manage")]
) -> WaWebhookResult:
    """Outside production only: deliver a webhook body as if Meta had sent it (no signature),
    so incoming WhatsApp can be tried before the number is live."""
    if get_settings().environment == "prod":
        raise NotFound("Not found")
    acct = await WA.require_account(db)
    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise Invalid("Send Meta's webhook JSON") from None
    return WaWebhookResult(kept=await WA.handle(db, acct, payload))

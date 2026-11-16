"""SMS endpoints (finishing plan, batch 5d).

- Settings → SMS (settings.manage): connect MSG91 / Twilio (keys encrypted, never shown again),
  the company's SMS texts (with the DLT template id for India).
- On the lead (leads.edit, only leads the person can see): send an SMS, see the SMS history.
- Public, on the company's address: `/api/v1/sms/{token}/status` (delivery reports) and
  `/api/v1/sms/{token}/inbound` (replies, STOP). The random token in the address is the
  company's own; Twilio's requests must also carry Twilio's signature. Anything else is a 404.
"""

import json
import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import secrets as SEC
from app.core.errors import Invalid, NotFound
from app.core.ratelimit import hit
from app.modules.auth.deps import CurrentUser, WorkspaceDep, require
from app.modules.calls import twilio as T
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.engage import render as R
from app.modules.sms import providers as P
from app.modules.sms import service as S
from app.modules.sms.models import SmsAccount, SmsMessage, SmsTemplate

router = APIRouter(prefix="/api/v1", tags=["sms"], dependencies=CRM)
public = APIRouter(prefix="/api/v1/sms", tags=["sms"], dependencies=CRM)
Admin = Annotated[CurrentUser, require("settings.manage")]
Worker = Annotated[CurrentUser, require("leads.edit")]
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


# ---------- shapes ----------
class SmsAccountIn(BaseModel):
    provider: Literal["msg91", "twilio", "test"]
    sender: str = Field(min_length=3, max_length=40)  # DLT header (6 letters) or a +number
    account_sid: str | None = Field(default=None, pattern=r"^AC[0-9a-f]{32}$")  # twilio
    auth: str | None = Field(default=None, min_length=4, max_length=200)  # keep if empty


class SmsAccountOut(BaseModel):
    connected: bool
    provider: str | None = None
    sender: str | None = None
    account_sid: str | None = None
    status_url: str | None = None  # Twilio sets it on each SMS; MSG91: paste as the DLR webhook
    inbound_url: str | None = None  # Twilio: the number's "A message comes in" webhook
    test_mode: bool


class SmsTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1000)
    dlt_template_id: str | None = Field(default=None, max_length=40)
    provider_template_id: str | None = Field(default=None, max_length=60)
    is_active: bool = True


class SmsTemplateOut(SmsTemplateIn):
    model_config = {"from_attributes": True}
    id: uuid.UUID


class SmsSendIn(BaseModel):
    body: str | None = Field(default=None, max_length=S.MAX_BODY)
    template_id: uuid.UUID | None = None


class SmsOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    direction: str
    number: str
    body: str
    status: str
    error: str | None
    created_at: datetime
    delivered_at: datetime | None


def _urls(acct: SmsAccount, slug: str) -> tuple[str, str]:
    base = S.status_url(acct, slug).rsplit("/", 1)[0]
    return f"{base}/status", f"{base}/inbound"


async def _out(db, ws_slug: str) -> SmsAccountOut:
    from app.core.config import get_settings

    acct = await S.account(db)
    test = get_settings().sms_mode == "test"
    if acct is None:
        return SmsAccountOut(connected=False, test_mode=test)
    status_url, inbound_url = _urls(acct, ws_slug)
    return SmsAccountOut(
        connected=True,
        provider=acct.provider,
        sender=acct.sender,
        account_sid=acct.account_sid,
        status_url=status_url,
        inbound_url=inbound_url,
        test_mode=test or acct.provider == "test",
    )


# ---------- Settings → SMS ----------
@router.get("/sms/account", response_model=SmsAccountOut)
async def get_account(db: CrmDb, actor: Admin, ws: WorkspaceDep) -> SmsAccountOut:
    return await _out(db, ws.slug)


@router.put("/sms/account", response_model=SmsAccountOut)
async def put_account(
    body: SmsAccountIn, db: CrmDb, actor: Admin, ws: WorkspaceDep
) -> SmsAccountOut:
    acct = await S.account(db)
    if body.provider == "twilio" and not body.account_sid:
        raise Invalid("Enter the Twilio Account SID")
    if body.provider == "twilio" and not body.sender.startswith("+"):
        raise Invalid("Twilio sends from your Twilio number, like +14155550100")
    if body.provider == "msg91" and not (body.sender.isalpha() and len(body.sender) == 6):
        raise Invalid("MSG91 sends with your DLT sender id: 6 letters, like VERSNQ")
    if acct is None:
        if body.provider != "test" and not body.auth:
            raise Invalid("Enter the key from your SMS provider")
        acct = SmsAccount(
            id=uuid.uuid4(), tenant_id=actor.user.tenant_id, webhook_token=secrets.token_urlsafe(24)
        )
        db.add(acct)
    acct.provider, acct.sender = (
        body.provider,
        body.sender.strip().upper() if body.provider == "msg91" else body.sender.strip(),
    )
    acct.account_sid = body.account_sid if body.provider == "twilio" else None
    if body.auth:
        acct.auth_enc = SEC.encrypt(body.auth)
    await P.client(acct).verify()
    await db.flush()
    await audit(
        db,
        actor,
        "sms.connected",
        "sms_account",
        acct.id,
        after={"provider": acct.provider, "sender": acct.sender},
    )
    return await _out(db, ws.slug)


@router.delete("/sms/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(db: CrmDb, actor: Admin) -> None:
    acct = await S.account(db)
    if acct:
        await audit(db, actor, "sms.disconnected", "sms_account", acct.id)
        await db.delete(acct)


@router.get("/sms/templates", response_model=list[SmsTemplateOut])
async def list_templates(db: CrmDb, actor: Worker) -> list[SmsTemplate]:
    return list((await db.scalars(select(SmsTemplate).order_by(SmsTemplate.name))).all())


async def _check_template(db, body: SmsTemplateIn) -> None:
    R.check(body.body, set((await L.lead_fields(db)).keys()))
    acct = await S.account(db)
    if (
        acct
        and acct.provider == "msg91"
        and (not body.dlt_template_id or not body.provider_template_id)
    ):
        raise Invalid("In India each SMS text needs its DLT template id and its MSG91 template id")


@router.post("/sms/templates", response_model=SmsTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(body: SmsTemplateIn, db: CrmDb, actor: Admin) -> SmsTemplate:
    await _check_template(db, body)
    t = SmsTemplate(id=uuid.uuid4(), tenant_id=actor.user.tenant_id, **body.model_dump())
    db.add(t)
    await db.flush()
    return t


@router.put("/sms/templates/{template_id}", response_model=SmsTemplateOut)
async def update_template(template_id: uuid.UUID, body: SmsTemplateIn, db: CrmDb, actor: Admin):
    t = await db.get(SmsTemplate, template_id)
    if t is None:
        raise NotFound("Not found")
    await _check_template(db, body)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await db.flush()
    return t


# ---------- on the lead ----------
@router.post("/leads/{lead_id}/sms", response_model=SmsOut)
async def send_sms(lead_id: uuid.UUID, body: SmsSendIn, db: CrmDb, actor: Worker) -> SmsMessage:
    lead = await L.get_visible(db, actor, lead_id)
    template = None
    if body.template_id:
        template = await db.get(SmsTemplate, body.template_id)
        if template is None or not template.is_active:
            raise Invalid("Choose an active SMS text")
    elif not (body.body or "").strip():
        raise Invalid("Write the SMS or choose a text", code="sms_empty")
    if not await hit(f"rl:sms:{actor.user.id}", 60, 3600):
        raise Invalid("Too many SMS in the last hour", code="rate_limited")
    return await S.send(db, lead, body=body.body, template=template, actor_user_id=actor.user.id)


@router.get("/leads/{lead_id}/sms", response_model=list[SmsOut])
async def lead_sms(lead_id: uuid.UUID, db: CrmDb, actor: Worker) -> list[SmsMessage]:
    lead = await L.get_visible(db, actor, lead_id)
    rows = await db.scalars(
        select(SmsMessage)
        .where(SmsMessage.lead_id == lead.id)
        .order_by(SmsMessage.created_at.desc())
        .limit(100)
    )
    return list(rows.all())


# ---------- from the provider ----------
async def _checked(token: str, request: Request, db) -> tuple[SmsAccount, dict[str, str]]:
    """The company's account and the provider's fields: the token in the address must be the
    company's, and Twilio's own signature must be right. Anything else: 404."""
    acct = await S.account(db)
    if acct is None or not secrets.compare_digest(token, acct.webhook_token):
        raise NotFound("Not found")
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise NotFound("Not found")
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind == "application/json":
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise NotFound("Not found") from None
        if isinstance(data, list):  # UNVERIFIED: MSG91 may send a list of reports
            data = data[0] if data and isinstance(data[0], dict) else {}
        fields = {str(k): str(v) for k, v in (data if isinstance(data, dict) else {}).items()}
    else:
        fields = dict(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))
    if acct.provider == "twilio" and not P.twilio_signature_ok(
        acct, T.external_url(request), fields, request.headers.get("x-twilio-signature")
    ):
        raise NotFound("Not found")
    return acct, fields


def _first(fields: dict[str, str], *names: str) -> str:
    return next((fields[n] for n in names if fields.get(n)), "")


@public.post("/{token}/status", status_code=status.HTTP_204_NO_CONTENT)
async def delivery_status(token: str, request: Request, db: CrmDb) -> Response:
    acct, f = await _checked(token, request, db)
    # Twilio: MessageSid + MessageStatus (+ ErrorCode). MSG91 (UNVERIFIED field names):
    # requestId / request_id + status / report_status (+ desc).
    provider_id = _first(f, "MessageSid", "requestId", "request_id", "provider_id")
    state = _first(f, "MessageStatus", "status", "report_status")
    if provider_id and state:
        await S.status_update(db, acct.provider, provider_id, state, _first(f, "ErrorCode", "desc"))
    return Response(status_code=204)


@public.post("/{token}/inbound")
async def inbound(token: str, request: Request, ws: WorkspaceDep, db: CrmDb) -> Response:
    acct, f = await _checked(token, request, db)
    # Twilio: From, Body, MessageSid. MSG91 inbound (UNVERIFIED): sender / mobile, message / text.
    number = _first(f, "From", "sender", "mobile", "from")
    text = _first(f, "Body", "message", "text", "content")
    if number:
        await S.incoming(
            db,
            ws.id,
            number=number,
            body=text,
            provider=acct.provider,
            provider_id=_first(f, "MessageSid", "requestId", "id") or None,
        )
    if acct.provider == "twilio":  # Twilio waits for TwiML; an empty answer sends nothing back
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?><Response/>', media_type="application/xml"
        )
    return Response(status_code=204)

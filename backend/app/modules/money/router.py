"""Money endpoints (step 6, Decision log #34): settings (entities, tax rates, gateways, mailbox,
reminders), invoices and their schedule, payments, payment links, balances and aging, and the
public gateway webhooks. Every amount is an integer in minor units (rule 7)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets, storage
from app.core.client_ip import client_ip
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.modules import require_module
from app.core.money import currency as check_currency
from app.core.ratelimit import hit
from app.modules.auth.deps import ActiveUser, CurrentUser, TenantDb, WorkspaceDep, require
from app.modules.crm import customers as C
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, audit
from app.modules.crm.models import Customer, Deal, Lead, StoredFile
from app.modules.crm.setup import ensure_crm_setup
from app.modules.money import calc, docs, gateways, links, mailbox, messages
from app.modules.money import service as S
from app.modules.money.models import (
    BillingEntity,
    GatewayAccount,
    Installment,
    Invoice,
    InvoiceLine,
    MailAccount,
    MoneyMessage,
    Payment,
    PaymentLink,
    TaxRate,
)
from app.modules.money.setup import ensure_money_setup
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User

MONEY = [*CRM, require_module("money")]
router = APIRouter(prefix="/api/v1", tags=["money"], dependencies=MONEY)
public = APIRouter(prefix="/api/v1/webhooks", tags=["money"], dependencies=MONEY)


async def _money_db(ws: WorkspaceDep, db: TenantDb) -> AsyncSession:
    await ensure_crm_setup(db, ws.id)
    await ensure_money_setup(db, ws.id)
    return db


MoneyDb = Annotated[AsyncSession, Depends(_money_db)]
Settings = Annotated[CurrentUser, require("money.settings")]
C_SP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
PDF_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}


# ---------- settings: billing entities ----------
class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    legal_name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2)
    currency: str = Field(min_length=3, max_length=3)
    tax_label: str | None = Field(default=None, max_length=20)
    tax_id: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=1000)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    bank_details: str | None = Field(default=None, max_length=1000)
    upi_id: str | None = Field(default=None, max_length=100, pattern=r"^[\w.\-]{2,}@[\w.\-]{2,}$")
    terms: str | None = Field(default=None, max_length=2000)
    due_days: int = Field(default=7, ge=0, le=365)
    invoice_prefix: str = Field(default="INV-", min_length=1, max_length=20)
    receipt_prefix: str = Field(default="RCT-", min_length=1, max_length=20)
    yearly_reset: bool = False
    year_start_month: int = Field(default=4, ge=1, le=12)
    is_default: bool = False
    is_active: bool = True


class EntityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    tax_label: str | None = Field(default=None, max_length=20)
    tax_id: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=1000)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    bank_details: str | None = Field(default=None, max_length=1000)
    upi_id: str | None = Field(default=None, max_length=100)
    terms: str | None = Field(default=None, max_length=2000)
    due_days: int | None = Field(default=None, ge=0, le=365)
    invoice_prefix: str | None = Field(default=None, min_length=1, max_length=20)
    receipt_prefix: str | None = Field(default=None, min_length=1, max_length=20)
    next_invoice_number: int | None = Field(default=None, ge=1)
    next_receipt_number: int | None = Field(default=None, ge=1)
    yearly_reset: bool | None = None
    year_start_month: int | None = Field(default=None, ge=1, le=12)
    is_default: bool | None = None
    is_active: bool | None = None


class EntityOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    legal_name: str
    country: str
    currency: str
    tax_label: str | None
    tax_id: str | None
    address: str | None
    email: str | None
    phone: str | None
    bank_details: str | None
    upi_id: str | None
    terms: str | None
    due_days: int
    invoice_prefix: str
    receipt_prefix: str
    next_invoice_number: int
    next_receipt_number: int
    yearly_reset: bool
    year_start_month: int
    number_period: str | None
    is_default: bool
    is_active: bool
    next_number: str = ""


def _entity_out(e: BillingEntity, day: date) -> EntityOut:
    period = calc.period(day, e.year_start_month) if e.yearly_reset else None
    n = e.next_invoice_number if period == e.number_period else 1
    return EntityOut.model_validate(e).model_copy(
        update={"next_number": S._number(e.invoice_prefix, period, n)}
    )


async def _only_default(db, keep: BillingEntity) -> None:
    for e in (await db.scalars(select(BillingEntity).where(BillingEntity.id != keep.id))).all():
        e.is_default = False
    await db.flush()


@router.get("/money/entities", response_model=list[EntityOut])
async def list_entities(db: MoneyDb, actor: ActiveUser):
    S.need(actor, "invoices.read")
    day = await S.company_today(db)
    rows = (await db.scalars(select(BillingEntity).order_by(BillingEntity.position))).all()
    return [_entity_out(e, day) for e in rows]


@router.post("/money/entities", response_model=EntityOut, status_code=status.HTTP_201_CREATED)
async def create_entity(body: EntityIn, db: MoneyDb, actor: Settings):
    data = body.model_dump()
    data["currency"] = check_currency(data["currency"])
    data["country"] = data["country"].upper()
    top = await db.scalar(select(func.coalesce(func.max(BillingEntity.position), -1)))
    e = BillingEntity(tenant_id=actor.user.tenant_id, position=top + 1, **data)
    db.add(e)
    await db.flush()
    if e.is_default:
        await _only_default(db, e)
    await audit(db, actor, "billing_entity.created", "billing_entity", e.id, after={"name": e.name})
    return _entity_out(e, await S.company_today(db))


@router.patch("/money/entities/{entity_id}", response_model=EntityOut)
async def update_entity(entity_id: uuid.UUID, body: EntityPatch, db: MoneyDb, actor: Settings):
    e = await db.get(BillingEntity, entity_id)
    if e is None:
        raise NotFound("Billing entity not found")
    data = body.model_dump(exclude_unset=True)
    if "currency" in data and data["currency"] != e.currency:
        data["currency"] = check_currency(data["currency"])
        used = await db.scalar(select(func.count()).where(Invoice.entity_id == e.id))
        if used:
            raise Conflict("This entity has invoices; its currency cannot change. Add a new one.")
    for n in ("next_invoice_number", "next_receipt_number"):
        if n in data and data[n] < getattr(e, n):
            raise Invalid("Numbers can only move forward, so no number is used twice")
    if data.get("is_default") is False and e.is_default:
        raise Invalid("Make another entity the default instead")
    if data.get("is_active") is False and e.is_default:
        raise Invalid("The default entity cannot be switched off")
    before = {"name": e.name, "currency": e.currency}
    for k, v in data.items():
        setattr(e, k, v.upper() if k == "country" and v else v)
    await db.flush()
    if e.is_default:
        await _only_default(db, e)
    await audit(
        db,
        actor,
        "billing_entity.updated",
        "billing_entity",
        e.id,
        before=before,
        after={k: str(v) for k, v in data.items()},
    )
    return _entity_out(e, await S.company_today(db))


# ---------- settings: tax rates ----------
class TaxPart(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    rate_bp: int = Field(ge=0, le=10_000)


class TaxIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    parts: list[TaxPart] = Field(default_factory=list, max_length=5)


class TaxPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    parts: list[TaxPart] | None = Field(default=None, max_length=5)
    is_active: bool | None = None


class TaxOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    parts: list[TaxPart]
    is_active: bool
    position: int


@router.get("/money/tax-rates", response_model=list[TaxOut])
async def list_tax_rates(db: MoneyDb, actor: ActiveUser):
    S.need(actor, "invoices.read")
    return (await db.scalars(select(TaxRate).order_by(TaxRate.position))).all()


@router.post("/money/tax-rates", response_model=TaxOut, status_code=status.HTTP_201_CREATED)
async def create_tax_rate(body: TaxIn, db: MoneyDb, actor: Settings):
    if await db.scalar(select(TaxRate.id).where(func.lower(TaxRate.name) == body.name.lower())):
        raise Conflict("A tax rate with this name already exists")
    top = await db.scalar(select(func.coalesce(func.max(TaxRate.position), -1)))
    rate = TaxRate(
        tenant_id=actor.user.tenant_id,
        name=body.name.strip(),
        parts=calc.check_parts([p.model_dump() for p in body.parts]),
        position=top + 1,
    )
    db.add(rate)
    await db.flush()
    await audit(db, actor, "tax_rate.created", "tax_rate", rate.id, after={"name": rate.name})
    return rate


@router.patch("/money/tax-rates/{rate_id}", response_model=TaxOut)
async def update_tax_rate(rate_id: uuid.UUID, body: TaxPatch, db: MoneyDb, actor: Settings):
    rate = await db.get(TaxRate, rate_id)
    if rate is None:
        raise NotFound("Tax rate not found")
    before = {"name": rate.name, "parts": rate.parts}
    if body.name is not None:
        rate.name = body.name.strip()
    if body.parts is not None:
        # Issued invoices keep the parts they were made with (copied on each line).
        rate.parts = calc.check_parts([p.model_dump() for p in body.parts])
    if body.is_active is not None:
        rate.is_active = body.is_active
    await db.flush()
    await audit(
        db,
        actor,
        "tax_rate.updated",
        "tax_rate",
        rate.id,
        before=before,
        after={"name": rate.name, "parts": rate.parts},
    )
    return rate


# ---------- settings: gateways ----------
class GatewayIn(BaseModel):
    entity_id: uuid.UUID
    gateway: Literal["razorpay", "stripe"]
    key_id: str | None = Field(default=None, max_length=200)
    secret: str = Field(min_length=8, max_length=300)
    webhook_secret: str = Field(min_length=8, max_length=300)
    mode: Literal["test", "live"] = "test"


class GatewayOut(BaseModel):
    id: uuid.UUID
    entity_id: uuid.UUID
    gateway: str
    key_id: str | None
    secret_hint: str
    mode: str
    is_active: bool
    last_checked_at: datetime | None
    last_error: str | None
    webhook_url: str


def _webhook_url(request: Request, a: GatewayAccount) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    scheme = "http" if host.split(":")[0].endswith("localhost") else "https"
    return f"{scheme}://{host}/api/v1/webhooks/{a.gateway}/{a.id}"


def _gateway_out(request: Request, a: GatewayAccount) -> GatewayOut:
    try:
        hint = secrets.hint(secrets.decrypt(a.secret_enc))
    except ValueError:
        hint = "••••"
    return GatewayOut(
        id=a.id,
        entity_id=a.entity_id,
        gateway=a.gateway,
        key_id=a.key_id,
        secret_hint=hint,
        mode=a.mode,
        is_active=a.is_active,
        last_checked_at=a.last_checked_at,
        last_error=a.last_error,
        webhook_url=_webhook_url(request, a),
    )


@router.get("/money/gateways", response_model=list[GatewayOut])
async def list_gateways(request: Request, db: MoneyDb, actor: Settings):
    rows = (await db.scalars(select(GatewayAccount).order_by(GatewayAccount.created_at))).all()
    return [_gateway_out(request, a) for a in rows]


@router.post("/money/gateways", response_model=GatewayOut, status_code=status.HTTP_201_CREATED)
async def connect_gateway(body: GatewayIn, request: Request, db: MoneyDb, actor: Settings):
    if await db.get(BillingEntity, body.entity_id) is None:
        raise NotFound("Billing entity not found")
    if body.gateway == "razorpay" and not body.key_id:
        raise Invalid("Razorpay needs its Key ID too")
    keys = gateways.Keys(
        body.gateway, body.key_id, body.secret.strip(), body.webhook_secret.strip()
    )
    await gateways.gateway(keys).check()  # refuses keys the gateway does not accept
    old = await db.scalar(
        select(GatewayAccount).where(
            GatewayAccount.entity_id == body.entity_id, GatewayAccount.gateway == body.gateway
        )
    )
    a = old or GatewayAccount(
        tenant_id=actor.user.tenant_id,
        entity_id=body.entity_id,
        gateway=body.gateway,
        created_by_user_id=actor.user.id,
    )
    a.key_id = body.key_id
    a.secret_enc = secrets.encrypt(keys.secret)
    a.webhook_secret_enc = secrets.encrypt(keys.webhook_secret)
    a.mode, a.is_active, a.last_checked_at, a.last_error = body.mode, True, L.now(), None
    if old is None:
        db.add(a)
    await db.flush()
    await audit(
        db,
        actor,
        "gateway.connected",
        "gateway_account",
        a.id,
        after={"gateway": a.gateway, "mode": a.mode},
    )
    return _gateway_out(request, a)


@router.post("/money/gateways/{account_id}/check", response_model=GatewayOut)
async def check_gateway(account_id: uuid.UUID, request: Request, db: MoneyDb, actor: Settings):
    a = await db.get(GatewayAccount, account_id)
    if a is None:
        raise NotFound("Gateway not found")
    try:
        await gateways.gateway(links.keys(a)).check()
        a.last_error = None
    except (gateways.GatewayError, ValueError) as e:
        a.last_error = str(getattr(e, "detail", e))[:500]
    a.last_checked_at = L.now()
    await db.flush()
    return _gateway_out(request, a)


@router.delete("/money/gateways/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_gateway(account_id: uuid.UUID, db: MoneyDb, actor: Settings):
    a = await db.get(GatewayAccount, account_id)
    if a is None:
        raise NotFound("Gateway not found")
    a.is_active = False  # kept: old links and payments point at it
    await db.flush()
    await audit(db, actor, "gateway.disconnected", "gateway_account", a.id)


# ---------- settings: mailbox ----------
def normalize_email(value: str) -> str:
    from email_validator import EmailNotValidError, validate_email

    try:
        return validate_email(value.strip(), check_deliverability=False).normalized
    except EmailNotValidError:
        raise Invalid(f"Not a valid email address: {value}") from None


class MailIn(BaseModel):
    host: str = Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9.\-]+$")
    port: Literal[25, 465, 587, 2525] = 587
    security: Literal["ssl", "starttls"] = "starttls"
    username: str = Field(min_length=1, max_length=254)
    password: str | None = Field(default=None, max_length=300)  # None: keep the saved one
    from_name: str = Field(min_length=1, max_length=120)
    from_email: str = Field(min_length=3, max_length=254)
    reply_to: str | None = Field(default=None, max_length=254)


class MailOut(BaseModel):
    host: str
    port: int
    security: str
    username: str
    password_hint: str
    from_name: str
    from_email: str
    reply_to: str | None
    is_active: bool
    last_checked_at: datetime | None
    last_error: str | None


def _mail_out(m: MailAccount) -> MailOut:
    return MailOut(
        host=m.host,
        port=m.port,
        security=m.security,
        username=m.username,
        password_hint="••••••••",
        from_name=m.from_name,
        from_email=m.from_email,
        reply_to=m.reply_to,
        is_active=m.is_active,
        last_checked_at=m.last_checked_at,
        last_error=m.last_error,
    )


@router.get("/money/mailbox", response_model=MailOut | None)
async def get_mailbox(db: MoneyDb, actor: Settings):
    m = await db.scalar(select(MailAccount))
    return _mail_out(m) if m else None


@router.put("/money/mailbox", response_model=MailOut)
async def save_mailbox(body: MailIn, db: MoneyDb, actor: Settings):
    m = await db.scalar(select(MailAccount))
    if m is None and not body.password:
        raise Invalid("Enter the mailbox password (for Gmail, an app password)")
    from_email = normalize_email(body.from_email)
    reply_to = normalize_email(body.reply_to) if body.reply_to else None
    password = body.password or secrets.decrypt(m.password_enc)
    box = mailbox.Box(
        body.host,
        body.port,
        body.security,
        body.username,
        password,
        body.from_name,
        from_email,
        reply_to,
    )
    await mailbox.check(box)  # signs in once; nothing is saved if the mailbox refuses
    m = m or MailAccount(tenant_id=actor.user.tenant_id)
    m.host, m.port, m.security, m.username = body.host, body.port, body.security, body.username
    m.password_enc = secrets.encrypt(password)
    m.from_name, m.from_email, m.reply_to = body.from_name, from_email, reply_to
    m.is_active, m.last_checked_at, m.last_error = True, L.now(), None
    db.add(m)
    await db.flush()
    await audit(db, actor, "mailbox.connected", "mail_account", m.id, after={"from": from_email})
    return _mail_out(m)


@router.delete("/money/mailbox", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mailbox(db: MoneyDb, actor: Settings):
    m = await db.scalar(select(MailAccount))
    if m is not None:
        await audit(db, actor, "mailbox.removed", "mail_account", m.id)
        await db.delete(m)
        await db.flush()


# ---------- settings: reminders and defaults ----------
class MoneySettings(BaseModel):
    money_reminder_before_days: int = Field(ge=0, le=30)
    money_overdue_every_days: int = Field(ge=1, le=60)
    money_default_pay: Literal["link", "direct", "both"]
    money_emails: dict[Literal["invoice", "receipt", "reminder", "void"], bool]


@router.get("/money/settings", response_model=MoneySettings)
async def get_money_settings(db: MoneyDb, actor: ActiveUser):
    S.need(actor, "invoices.read")
    s = await db.get(TenantSettings, actor.user.tenant_id)
    return MoneySettings(
        money_reminder_before_days=s.money_reminder_before_days,
        money_overdue_every_days=s.money_overdue_every_days,
        money_default_pay=s.money_default_pay,
        money_emails={k: bool((s.money_emails or {}).get(k, True)) for k in messages.KINDS},
    )


@router.put("/money/settings", response_model=MoneySettings)
async def save_money_settings(body: MoneySettings, db: MoneyDb, actor: Settings):
    s = await db.get(TenantSettings, actor.user.tenant_id)
    before = {"before": s.money_reminder_before_days, "every": s.money_overdue_every_days}
    s.money_reminder_before_days = body.money_reminder_before_days
    s.money_overdue_every_days = body.money_overdue_every_days
    s.money_default_pay = body.money_default_pay
    s.money_emails = {k: body.money_emails.get(k, True) for k in messages.KINDS}
    await db.flush()
    await audit(
        db,
        actor,
        "money_settings.updated",
        "tenant_settings",
        None,
        before=before,
        after=body.model_dump(),
    )
    return body


# ---------- invoices: schemas ----------
class LineBody(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    quantity: int = Field(ge=1, le=100_000)
    unit_price_minor: int = Field(ge=0)
    discount_minor: int = Field(default=0, ge=0)
    tax_rate_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None


class InvoiceLineOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    position: int
    product_id: uuid.UUID | None
    description: str
    quantity: int
    unit_price_minor: int
    discount_minor: int
    net_minor: int
    tax_rate_id: uuid.UUID | None
    tax_name: str | None
    tax_minor: int
    total_minor: int


class InstallmentOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    position: int
    amount_minor: int
    due_date: date
    paid_minor: int
    state: str = "due"


class PaymentOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    invoice_id: uuid.UUID
    amount_minor: int
    currency: str
    method: str
    paid_on: date
    reference: str | None
    receipt_number: str
    status: str
    reverse_reason: str | None
    has_proof: bool = False
    recorded_by_name: str | None = None
    invoice_number: str | None = None
    customer_name: str | None = None
    created_at: datetime


class PaymentLinkOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    installment_id: uuid.UUID | None
    gateway: str
    amount_minor: int
    currency: str
    url: str
    status: str
    created_at: datetime


class MessageOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    kind: str
    to_address: str
    status: str
    error: str | None
    created_at: datetime
    sent_at: datetime | None


class InvoiceRow(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    number: str | None
    status: str
    customer_id: uuid.UUID
    lead_id: uuid.UUID
    deal_id: uuid.UUID | None
    entity_id: uuid.UUID
    currency: str
    issue_date: date | None
    due_date: date | None
    total_minor: int
    paid_minor: int
    customer_name: str | None = None
    customer_number: str | None = None
    owner_name: str | None = None
    overdue_minor: int = 0
    next_due_date: date | None = None
    created_at: datetime


class InvoiceDetail(InvoiceRow):
    pay_link: bool
    pay_direct: bool
    notes: str | None
    subtotal_minor: int
    discount_minor: int
    tax_minor: int
    tax_breakdown: list[dict]
    repeat_months: int | None
    repeat_next_date: date | None
    void_reason: str | None
    version: int
    lines: list[InvoiceLineOut] = []
    installments: list[InstallmentOut] = []
    payments: list[PaymentOut] = []
    links: list[PaymentLinkOut] = []
    messages: list[MessageOut] = []
    customer_email: str | None = None
    customer_phone: str | None = None
    entity_name: str | None = None
    gateway: str | None = None


class InvoicePage(BaseModel):
    items: list[InvoiceRow]
    total: int


class NewInvoice(BaseModel):
    customer_id: uuid.UUID
    deal_id: uuid.UUID | None = None
    entity_id: uuid.UUID | None = None


class InvoicePatch(BaseModel):
    version: int
    entity_id: uuid.UUID | None = None
    lines: list[LineBody] | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None
    pay_link: bool | None = None
    pay_direct: bool | None = None
    repeat_months: Literal[1, 3, 6, 12] | None = None
    no_repeat: bool = False


class ScheduleItem(BaseModel):
    amount_minor: int = Field(gt=0)
    due_date: date


class ScheduleIn(BaseModel):
    """Either equal parts (count, first due date, months between) or custom items."""

    count: int | None = Field(default=None, ge=1, le=calc.MAX_INSTALLMENTS)
    first_due_date: date | None = None
    months_between: int = Field(default=1, ge=0, le=12)
    days_between: int = Field(default=0, ge=0, le=365)
    items: list[ScheduleItem] | None = Field(default=None, max_length=calc.MAX_INSTALLMENTS)


class IssueIn(BaseModel):
    issue_date: date | None = None
    due_date: date | None = None


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RepeatIn(BaseModel):
    months: Literal[1, 3, 6, 12] | None


class PaymentLinkIn(BaseModel):
    installment_id: uuid.UUID | None = None


class SharedIn(BaseModel):
    channel: Literal["whatsapp", "copy"]


# ---------- invoices: helpers ----------
async def _rows(db, invs: list[Invoice]) -> list[InvoiceRow]:
    if not invs:
        return []
    day = await S.company_today(db)
    ids = [i.id for i in invs]
    people = {
        c.id: (c, ld)
        for c, ld in (
            await db.execute(
                select(Customer, Lead)
                .join(Lead, Lead.id == Customer.lead_id)
                .where(Customer.id.in_({i.customer_id for i in invs}))
            )
        ).all()
    }
    owners = {
        u.id: u.name
        for u in (
            await db.scalars(
                select(User).where(
                    User.id.in_({ld.owner_user_id for _, ld in people.values()} - {None})
                )
            )
        ).all()
    }
    overdue = dict(
        (
            await db.execute(
                select(
                    Installment.invoice_id,
                    func.sum(Installment.amount_minor - Installment.paid_minor),
                )
                .where(Installment.invoice_id.in_(ids), Installment.due_date < day)
                .group_by(Installment.invoice_id)
            )
        ).all()
    )
    nxt = dict(
        (
            await db.execute(
                select(Installment.invoice_id, func.min(Installment.due_date))
                .where(
                    Installment.invoice_id.in_(ids),
                    Installment.paid_minor < Installment.amount_minor,
                )
                .group_by(Installment.invoice_id)
            )
        ).all()
    )
    out = []
    for i in invs:
        c, ld = people.get(i.customer_id, (None, None))
        live = i.status in S.OPEN
        out.append(
            InvoiceRow.model_validate(i).model_copy(
                update={
                    "customer_name": ld.display_name if ld else None,
                    "customer_number": c.number if c else None,
                    "owner_name": owners.get(ld.owner_user_id) if ld else None,
                    "overdue_minor": int(overdue.get(i.id) or 0) if live else 0,
                    "next_due_date": nxt.get(i.id) if live else None,
                }
            )
        )
    return out


async def _payments_out(db, pays: list[Payment]) -> list[PaymentOut]:
    names = {
        u.id: u.name
        for u in (
            await db.scalars(
                select(User).where(User.id.in_({p.recorded_by_user_id for p in pays} - {None}))
            )
        ).all()
    }
    invs = {
        i.id: i
        for i in (
            await db.scalars(select(Invoice).where(Invoice.id.in_({p.invoice_id for p in pays})))
        ).all()
    }
    leads = {
        ld.id: ld.display_name
        for ld in (
            await db.scalars(select(Lead).where(Lead.id.in_({p.lead_id for p in pays})))
        ).all()
    }
    return [
        PaymentOut.model_validate(p).model_copy(
            update={
                "has_proof": p.proof_file_id is not None,
                "recorded_by_name": names.get(p.recorded_by_user_id),
                "invoice_number": invs[p.invoice_id].number if p.invoice_id in invs else None,
                "customer_name": leads.get(p.lead_id),
            }
        )
        for p in pays
    ]


async def _detail(db, inv: Invoice) -> InvoiceDetail:
    day = await S.company_today(db)
    row = (await _rows(db, [inv]))[0]
    lead = await db.get(Lead, inv.lead_id)
    entity = await db.get(BillingEntity, inv.entity_id)
    account = await links.account_for(db, inv.entity_id)
    lines = (
        await db.scalars(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == inv.id)
            .order_by(InvoiceLine.position)
        )
    ).all()
    plan = await S.installments(db, inv.id)
    pays = (
        await db.scalars(
            select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.created_at)
        )
    ).all()
    lks = (
        await db.scalars(
            select(PaymentLink)
            .where(PaymentLink.invoice_id == inv.id)
            .order_by(PaymentLink.created_at)
        )
    ).all()
    msgs = (
        await db.scalars(
            select(MoneyMessage)
            .where(MoneyMessage.invoice_id == inv.id)
            .order_by(MoneyMessage.created_at.desc())
        )
    ).all()
    return InvoiceDetail(
        **row.model_dump(),
        pay_link=inv.pay_link,
        pay_direct=inv.pay_direct,
        notes=inv.notes,
        subtotal_minor=inv.subtotal_minor,
        discount_minor=inv.discount_minor,
        tax_minor=inv.tax_minor,
        tax_breakdown=inv.tax_breakdown,
        repeat_months=inv.repeat_months,
        repeat_next_date=inv.repeat_next_date,
        void_reason=inv.void_reason,
        version=inv.version,
        lines=[InvoiceLineOut.model_validate(x) for x in lines],
        installments=[
            InstallmentOut.model_validate(i).model_copy(
                update={"state": S.installment_state(i, day)}
            )
            for i in plan
        ],
        payments=await _payments_out(db, list(pays)),
        links=[PaymentLinkOut.model_validate(x) for x in lks],
        messages=[MessageOut.model_validate(m) for m in msgs],
        customer_email=lead.primary_email,
        customer_phone=lead.primary_phone,
        entity_name=entity.name if entity else None,
        gateway=account.gateway if account else None,
    )


def _version(inv: Invoice, version: int) -> None:
    if inv.version != version:
        raise Conflict("Someone else changed this invoice. Reload and try again.")


async def _customer(db, actor: CurrentUser, customer_id: uuid.UUID) -> tuple[Customer, Lead]:
    S.need(actor, "invoices.read")
    return await C.get_visible(db, actor, customer_id)


# ---------- invoices: list, create, change ----------
@router.get("/invoices", response_model=InvoicePage)
async def list_invoices(
    db: MoneyDb,
    actor: ActiveUser,
    q: str | None = None,
    status_: Annotated[
        list[Literal["draft", "issued", "partly_paid", "paid", "void"]], Query(alias="status")
    ] = [],  # noqa: B006
    entity_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
    overdue: bool = False,
    sort: Literal["-created", "due", "-total", "number"] = "-created",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    S.need(actor, "invoices.read")
    where = [await S.visible(db, actor)]
    if q and q.strip():
        like = f"%{q.strip()}%"
        where.append(or_(Invoice.number.ilike(like), Lead.display_name.ilike(like)))
    if status_:
        where.append(Invoice.status.in_(status_))
    if entity_id:
        where.append(Invoice.entity_id == entity_id)
    if customer_id:
        where.append(Invoice.customer_id == customer_id)
    if owner:
        ids = [uuid.UUID(o) for o in owner if o not in ("me", "none")]
        conds = [Lead.owner_user_id.in_(ids)] if ids else []
        if "me" in owner:
            conds.append(Lead.owner_user_id == actor.user.id)
        if "none" in owner:
            conds.append(Lead.owner_user_id.is_(None))
        where.append(or_(*conds))
    if overdue:
        late = select(Installment.invoice_id).where(
            Installment.due_date < await S.company_today(db),
            Installment.paid_minor < Installment.amount_minor,
        )
        where += [Invoice.status.in_(S.OPEN), Invoice.id.in_(late)]
    base = select(Invoice).join(Lead, Lead.id == Invoice.lead_id).where(*where)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    order = {
        "-created": Invoice.created_at.desc(),
        "due": Invoice.due_date.asc().nulls_last(),
        "-total": Invoice.total_minor.desc(),
        "number": Invoice.number.asc().nulls_last(),
    }[sort]
    rows = (
        await db.scalars(
            base.order_by(order, Invoice.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return InvoicePage(items=await _rows(db, list(rows)), total=total or 0)


@router.post("/invoices", response_model=InvoiceDetail, status_code=status.HTTP_201_CREATED)
async def create_invoice(body: NewInvoice, db: MoneyDb, actor: ActiveUser):
    customer, lead = await _customer(db, actor, body.customer_id)
    deal = None
    if body.deal_id:
        deal = await db.scalar(select(Deal).where(Deal.id == body.deal_id, Deal.lead_id == lead.id))
        if deal is None or deal.status != "won":
            raise Invalid("Choose a won deal of this customer")
    inv = await S.create_draft(db, actor, customer, lead, deal=deal, entity_id=body.entity_id)
    await audit(
        db, actor, "invoice.created", "invoice", inv.id, after={"customer": str(customer.id)}
    )
    return await _detail(db, inv)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetail)
async def get_invoice(invoice_id: uuid.UUID, db: MoneyDb, actor: ActiveUser):
    return await _detail(db, await S.get_invoice(db, actor, invoice_id))


@router.patch("/invoices/{invoice_id}", response_model=InvoiceDetail)
async def update_invoice(invoice_id: uuid.UUID, body: InvoicePatch, db: MoneyDb, actor: ActiveUser):
    S.need(actor, "invoices.create")
    inv = await S.get_invoice(db, actor, invoice_id)
    _version(inv, body.version)
    S.editable(inv)
    data = body.model_dump(exclude_unset=True)
    if body.entity_id and body.entity_id != inv.entity_id:
        await S.change_entity(db, inv, body.entity_id)
    if "notes" in data:
        inv.notes = (body.notes or "").strip() or None
    if "due_date" in data:
        inv.due_date = body.due_date
    if body.pay_link is not None:
        inv.pay_link = body.pay_link
    if body.pay_direct is not None:
        inv.pay_direct = body.pay_direct
    if not (inv.pay_link or inv.pay_direct):
        raise Invalid("Choose at least one way to pay: a payment link, paying directly, or both")
    if body.no_repeat:
        inv.repeat_months = None
    elif body.repeat_months:
        inv.repeat_months = body.repeat_months
    if body.lines is not None:
        await S.set_lines(db, inv, [S.LineIn(**ln.model_dump()) for ln in body.lines])
    inv.version += 1
    await db.flush()
    return await _detail(db, inv)


@router.put("/invoices/{invoice_id}/installments", response_model=InvoiceDetail)
async def set_installments(invoice_id: uuid.UUID, body: ScheduleIn, db: MoneyDb, actor: ActiveUser):
    S.need(actor, "invoices.create")
    inv = await S.get_invoice(db, actor, invoice_id)
    if body.items is not None:
        plan = [(i.amount_minor, i.due_date) for i in body.items]
    elif body.count and body.first_due_date:
        amounts = calc.split_equal(inv.total_minor, body.count)
        plan = []
        for n, amount in enumerate(amounts):
            due = calc.add_months(body.first_due_date, body.months_between * n)
            if body.days_between:
                from datetime import timedelta

                due = due + timedelta(days=body.days_between * n)
            plan.append((amount, due))
    else:
        raise Invalid("Give the number of installments and the first due date, or each one")
    await S.set_schedule(db, inv, plan)
    inv.version += 1
    await db.flush()
    return await _detail(db, inv)


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(invoice_id: uuid.UUID, db: MoneyDb, actor: ActiveUser):
    inv = await S.get_invoice(db, actor, invoice_id)
    await S.delete_draft(db, actor, inv)
    await audit(db, actor, "invoice.deleted", "invoice", invoice_id)


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceDetail)
async def issue_invoice(invoice_id: uuid.UUID, body: IssueIn, db: MoneyDb, actor: ActiveUser):
    inv = await S.get_invoice(db, actor, invoice_id)
    if body.issue_date and body.issue_date > await S.company_today(db):
        raise Invalid("The invoice date cannot be in the future")
    inv = await S.issue(db, actor, inv, issue_date=body.issue_date, due_date=body.due_date)
    await audit(
        db,
        actor,
        "invoice.issued",
        "invoice",
        inv.id,
        after={"number": inv.number, "total_minor": inv.total_minor, "currency": inv.currency},
    )
    await messages.auto(db, inv, "invoice")
    return await _detail(db, inv)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceDetail)
async def void_invoice(invoice_id: uuid.UUID, body: ReasonIn, db: MoneyDb, actor: ActiveUser):
    inv = await S.get_invoice(db, actor, invoice_id)
    to_cancel = (
        await db.scalars(
            select(PaymentLink).where(
                PaymentLink.invoice_id == inv.id, PaymentLink.status == "active"
            )
        )
    ).all()
    gateway_ids = [(x.gateway_account_id, x.gateway_link_id) for x in to_cancel]
    inv = await S.void(db, actor, inv, body.reason)
    await audit(db, actor, "invoice.voided", "invoice", inv.id, after={"reason": body.reason})
    await messages.auto(db, inv, "void")
    for account_id, link_id in gateway_ids:  # best effort: the link is already off in Core
        try:
            await gateways.gateway(links.keys(await db.get(GatewayAccount, account_id))).cancel(
                link_id
            )
        except (gateways.GatewayError, ValueError, OSError):
            pass
    return await _detail(db, inv)


@router.post("/invoices/{invoice_id}/repeat", response_model=InvoiceDetail)
async def repeat_invoice(invoice_id: uuid.UUID, body: RepeatIn, db: MoneyDb, actor: ActiveUser):
    inv = await S.get_invoice(db, actor, invoice_id)
    await S.set_repeat(db, actor, inv, body.months)
    await audit(db, actor, "invoice.repeat", "invoice", inv.id, after={"months": body.months})
    return await _detail(db, inv)


@router.get(
    "/invoices/{invoice_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def invoice_pdf(
    invoice_id: uuid.UUID, db: MoneyDb, actor: ActiveUser, download: bool = False
):
    inv = await S.get_invoice(db, actor, invoice_id)
    name = f"{inv.number or 'draft'}.pdf".replace("/", "-")
    kind = "attachment" if download else "inline"
    return Response(
        await docs.invoice_pdf(db, inv),
        media_type="application/pdf",
        headers={**PDF_HEADERS, "Content-Disposition": f'{kind}; filename="{name}"'},
    )


@router.post("/invoices/{invoice_id}/email", response_model=InvoiceDetail)
async def email_invoice(invoice_id: uuid.UUID, db: MoneyDb, actor: ActiveUser):
    S.need(actor, "invoices.create")
    inv = await S.get_invoice(db, actor, invoice_id)
    if inv.status == "draft":
        raise Invalid("Issue the invoice before emailing it")
    kind = "void" if inv.status == "void" else "invoice"
    await messages.queue(db, inv, kind, actor=actor, strict=True)
    return await _detail(db, inv)


@router.post("/invoices/{invoice_id}/shared", status_code=status.HTTP_204_NO_CONTENT)
async def invoice_shared(invoice_id: uuid.UUID, body: SharedIn, db: MoneyDb, actor: ActiveUser):
    """The rep sent the invoice or its link themselves (WhatsApp on their phone, or copied)."""
    S.need(actor, "invoices.create")
    inv = await S.get_invoice(db, actor, invoice_id)
    lead = await db.get(Lead, inv.lead_id)
    how = "on WhatsApp" if body.channel == "whatsapp" else "(link copied)"
    await L.log(
        db,
        lead,
        "payment_link_sent",
        f"Invoice {inv.number} sent {how}",
        actor,
        {"invoice_id": str(inv.id), "channel": body.channel},
    )


# ---------- payments ----------
@router.post(
    "/invoices/{invoice_id}/payments",
    response_model=InvoiceDetail,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def record_payment(
    invoice_id: uuid.UUID,
    request: Request,
    db: MoneyDb,
    actor: ActiveUser,
    amount_minor: Annotated[int, Query(gt=0)],
    method: Literal["bank", "upi", "cash", "cheque", "card", "other"],
    paid_on: date,
    name: Annotated[str, Query(min_length=1, max_length=255)],
    reference: Annotated[str | None, Query(max_length=120)] = None,
):
    """The request body is the proof (a photo or PDF of the transfer, up to 10 MB)."""
    S.need(actor, "payments.record")
    inv = await S.get_invoice(db, actor, invoice_id)
    if inv.status not in S.OPEN:
        raise Conflict("Only issued invoices with money due take payments")
    data = await storage.read_upload(request)
    proof = await S.save_proof(db, actor, inv, data, name)
    try:
        async with db.begin_nested():
            payment = await S.record_manual(
                db,
                actor,
                inv,
                amount=amount_minor,
                method=method,
                paid_on=paid_on,
                reference=reference,
                proof=proof,
            )
    except Exception:
        storage.remove(proof.path)
        raise
    await audit(
        db,
        actor,
        "payment.recorded",
        "payment",
        payment.id,
        after={"amount_minor": amount_minor, "currency": payment.currency, "method": method},
    )
    await messages.auto(db, inv, "receipt", payment=payment)
    return await _detail(db, await db.get(Invoice, inv.id))


@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(
    db: MoneyDb,
    actor: ActiveUser,
    entity_id: uuid.UUID | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    S.need(actor, "invoices.read")
    where = [await S.visible(db, actor)]
    if entity_id:
        where.append(Payment.entity_id == entity_id)
    if since:
        where.append(Payment.paid_on >= since)
    if until:
        where.append(Payment.paid_on <= until)
    rows = (
        await db.scalars(
            select(Payment)
            .join(Lead, Lead.id == Payment.lead_id)
            .where(*where)
            .order_by(Payment.paid_on.desc(), Payment.created_at.desc())
            .limit(limit)
        )
    ).all()
    return await _payments_out(db, list(rows))


async def _payment(db, actor: CurrentUser, payment_id: uuid.UUID) -> Payment:
    S.need(actor, "invoices.read")
    p = await db.scalar(
        select(Payment)
        .join(Lead, Lead.id == Payment.lead_id)
        .where(Payment.id == payment_id, await S.visible(db, actor))
    )
    if p is None:
        raise NotFound("Payment not found")
    return p


@router.post("/payments/{payment_id}/reverse", response_model=InvoiceDetail)
async def reverse_payment(payment_id: uuid.UUID, body: ReasonIn, db: MoneyDb, actor: ActiveUser):
    p = await _payment(db, actor, payment_id)
    await S.reverse(db, actor, p, body.reason)
    await audit(db, actor, "payment.reversed", "payment", p.id, after={"reason": body.reason})
    return await _detail(db, await db.get(Invoice, p.invoice_id))


@router.get(
    "/payments/{payment_id}/receipt",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def receipt_pdf(
    payment_id: uuid.UUID, db: MoneyDb, actor: ActiveUser, download: bool = False
):
    p = await _payment(db, actor, payment_id)
    kind = "attachment" if download else "inline"
    return Response(
        await docs.receipt_pdf(db, p),
        media_type="application/pdf",
        headers={
            **PDF_HEADERS,
            "Content-Disposition": f'{kind}; filename="{p.receipt_number.replace("/", "-")}.pdf"',
        },
    )


@router.get(
    "/payments/{payment_id}/proof",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def payment_proof(
    payment_id: uuid.UUID, db: MoneyDb, actor: ActiveUser, download: bool = False
):
    p = await _payment(db, actor, payment_id)
    stored = await db.get(StoredFile, p.proof_file_id) if p.proof_file_id else None
    if stored is None:
        raise NotFound("No proof for this payment")
    path = storage.full_path(stored.path)
    if not path.exists():
        raise NotFound("This file is missing on the server")
    inline = not download and stored.content_type in storage.PREVIEWABLE
    return FileResponse(
        path,
        media_type=stored.content_type,
        filename=stored.original_name,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            **PDF_HEADERS,
            "Content-Security-Policy": C_SP,
        },
    )


# ---------- payment links ----------
@router.post(
    "/invoices/{invoice_id}/links",
    response_model=PaymentLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_link(
    invoice_id: uuid.UUID, body: PaymentLinkIn, db: MoneyDb, actor: ActiveUser
):
    inv = await S.get_invoice(db, actor, invoice_id)
    link = await links.create_link(db, actor, inv, body.installment_id)
    return link


@router.delete("/payment-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_payment_link(link_id: uuid.UUID, db: MoneyDb, actor: ActiveUser):
    link = await db.get(PaymentLink, link_id)
    if link is None:
        raise NotFound("Link not found")
    await S.get_invoice(db, actor, link.invoice_id)  # visibility
    await links.cancel_link(db, actor, link)


# ---------- balances and aging ----------
class Balance(BaseModel):
    currency: str
    billed_minor: int
    paid_minor: int
    due_minor: int
    overdue_minor: int


class CustomerMoney(BaseModel):
    balances: list[Balance]
    invoices: list[InvoiceRow]


@router.get("/customers/{customer_id}/money", response_model=CustomerMoney)
async def customer_money(customer_id: uuid.UUID, db: MoneyDb, actor: ActiveUser):
    customer, _ = await _customer(db, actor, customer_id)
    invs = (
        await db.scalars(
            select(Invoice)
            .where(Invoice.customer_id == customer.id)
            .order_by(Invoice.created_at.desc())
        )
    ).all()
    return CustomerMoney(
        balances=await S.balances(db, customer.id, await S.company_today(db)),
        invoices=await _rows(db, list(invs)),
    )


class AgingRow(BaseModel):
    entity_id: uuid.UUID
    entity_name: str
    currency: str
    buckets: dict[str, int]
    total_minor: int
    due_later_minor: int


@router.get("/money/aging", response_model=list[AgingRow])
async def aging(db: MoneyDb, actor: ActiveUser):
    """Overdue money by how late it is (0–30 / 31–60 / 61–90 / 90+ days), per entity and
    currency, plus what is due but not yet late."""
    S.need(actor, "invoices.read")
    day = await S.company_today(db)
    rows = (
        await db.execute(
            select(
                Invoice.entity_id,
                Invoice.currency,
                Installment.due_date,
                Installment.amount_minor - Installment.paid_minor,
            )
            .join(Installment, Installment.invoice_id == Invoice.id)
            .join(Lead, Lead.id == Invoice.lead_id)
            .where(
                await S.visible(db, actor),
                Invoice.status.in_(S.OPEN),
                Installment.paid_minor < Installment.amount_minor,
            )
        )
    ).all()
    names = dict((await db.execute(select(BillingEntity.id, BillingEntity.name))).all())
    out: dict[tuple, AgingRow] = {}
    for entity_id, cur, due, left in rows:
        r = out.setdefault(
            (entity_id, cur),
            AgingRow(
                entity_id=entity_id,
                entity_name=names.get(entity_id, ""),
                currency=cur,
                buckets=dict.fromkeys(calc.AGING, 0),
                total_minor=0,
                due_later_minor=0,
            ),
        )
        if due < day:
            r.buckets[calc.aging_bucket((day - due).days)] += int(left)
            r.total_minor += int(left)
        else:
            r.due_later_minor += int(left)
    return sorted(out.values(), key=lambda r: (r.entity_name, r.currency))


# ---------- public: gateway webhooks ----------
@public.post("/{gateway_name}/{account_id}")
async def gateway_webhook(
    gateway_name: Literal["razorpay", "stripe"],
    account_id: uuid.UUID,
    request: Request,
    ws: WorkspaceDep,
    db: TenantDb,
):
    """Public, signature-checked: the gateway tells Core a link was paid. Answers 200 for
    anything handled (including repeats), so the gateway stops retrying."""
    if not await hit(f"rl:gw:{account_id}:{client_ip(request)}", 300, 60):
        return Response(status_code=429)
    body = await request.body()
    if len(body) > 256 * 1024:
        raise Invalid("Too large")
    account = await db.get(GatewayAccount, account_id)
    if account is None or account.gateway != gateway_name:
        raise NotFound("Unknown gateway")
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        result = await links.handle_webhook(db, account, headers, body)
    except gateways.GatewayError:
        raise Forbidden("bad_signature") from None
    except (ValueError, KeyError, TypeError):
        raise Invalid("Could not read this webhook") from None
    return {"ok": True, "result": result}

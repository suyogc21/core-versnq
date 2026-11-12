"""Invoices, installments, payments and balances (step 6, Decision log #34).

Life of an invoice: draft (editable, no number) → issued (numbered, locked) → partly paid →
paid; an issued invoice is never edited or deleted, only voided with a reason. A payment is
applied to the oldest unpaid installment first and a wrong one is reversed, never deleted.

Who sees what: invoices follow their customer (Finance sees every customer's money).
Every change writes an activity on the customer's timeline and fires an event.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.money import check_amount, display
from app.modules.auth.deps import CurrentUser
from app.modules.crm import customers as C
from app.modules.crm import leads as L
from app.modules.crm.models import Customer, Deal, DealProduct, Lead, Product, StoredFile
from app.modules.money import calc
from app.modules.money.models import (
    BillingEntity,
    Installment,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    PaymentLink,
    TaxRate,
)
from app.modules.settings.models import TenantSettings

OPEN = ("issued", "partly_paid")
BILLED = ("issued", "partly_paid", "paid")
METHODS = ("bank", "upi", "cash", "cheque", "card", "other")


def today(tz: str | None) -> date:
    return L.now().astimezone(ZoneInfo(tz or "UTC")).date()


async def company_today(db: AsyncSession) -> date:
    settings = await db.scalar(select(TenantSettings))
    return today(settings.timezone if settings else None)


# ---------- who may see and change ----------
def need(actor: CurrentUser, code: str) -> None:
    if not L.can(actor, code):
        raise Forbidden("permission_denied")


async def visible(db: AsyncSession, actor: CurrentUser):
    """SQL condition (on Lead) for whose money this person may see."""
    if not L.can(actor, "invoices.read"):
        from sqlalchemy import false

        return false()
    return await C.visibility(db, actor)


async def get_invoice(db: AsyncSession, actor: CurrentUser, invoice_id: uuid.UUID) -> Invoice:
    inv = await db.scalar(
        select(Invoice)
        .join(Lead, Lead.id == Invoice.lead_id)
        .where(Invoice.id == invoice_id, await visible(db, actor))
    )
    if inv is None:
        raise NotFound("Invoice not found")
    return inv


async def lock(db: AsyncSession, inv: Invoice) -> Invoice:
    """The invoice row, locked until the end of the transaction (payments, issue, void)."""
    return await db.scalar(
        select(Invoice)
        .where(Invoice.id == inv.id)
        .with_for_update()
        .execution_options(populate_existing=True)  # read the row again, not a cached copy
    )


# ---------- entities and numbering ----------
async def default_entity(db: AsyncSession, currency: str | None = None) -> BillingEntity:
    rows = (
        await db.scalars(
            select(BillingEntity)
            .where(BillingEntity.is_active.is_(True))
            .order_by(BillingEntity.is_default.desc(), BillingEntity.position)
        )
    ).all()
    if currency:
        rows = [e for e in rows if e.currency == currency]
    if not rows:
        if currency:
            raise Invalid(
                f"No billing entity bills in {currency}. Add one in Settings → Money first."
            )
        raise Invalid("Add a billing entity in Settings → Money first")
    return rows[0]


async def _entity(db: AsyncSession, entity_id: uuid.UUID) -> BillingEntity:
    entity = await db.get(BillingEntity, entity_id)
    if entity is None or not entity.is_active:
        raise Invalid("Choose an active billing entity")
    return entity


def _number(prefix: str, period: str | None, n: int) -> str:
    return f"{prefix}{period + '/' if period else ''}{n:04d}"


async def next_numbers(db: AsyncSession, entity_id: uuid.UUID, day: date, *, invoice: bool) -> str:
    """The next invoice or receipt number of an entity: the row is locked, so two people
    issuing at the same moment never get the same number and no number is skipped."""
    e = await db.scalar(
        select(BillingEntity)
        .where(BillingEntity.id == entity_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    period = calc.period(day, e.year_start_month) if e.yearly_reset else None
    if period != e.number_period:
        e.number_period, e.next_invoice_number, e.next_receipt_number = period, 1, 1
    if invoice:
        n, e.next_invoice_number = e.next_invoice_number, e.next_invoice_number + 1
        return _number(e.invoice_prefix, period, n)
    n, e.next_receipt_number = e.next_receipt_number, e.next_receipt_number + 1
    return _number(e.receipt_prefix, period, n)


# ---------- drafts ----------
@dataclass
class LineIn:
    description: str
    quantity: int
    unit_price_minor: int
    discount_minor: int = 0
    tax_rate_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None


async def _rates(db: AsyncSession, ids: set) -> dict[uuid.UUID, TaxRate]:
    if not ids:
        return {}
    rates = {r.id: r for r in (await db.scalars(select(TaxRate).where(TaxRate.id.in_(ids)))).all()}
    if set(rates) != ids:
        raise Invalid("Choose tax rates from your list")
    return rates


async def default_rate(db: AsyncSession) -> TaxRate | None:
    return await db.scalar(
        select(TaxRate).where(TaxRate.is_active.is_(True)).order_by(TaxRate.position).limit(1)
    )


async def set_lines(db: AsyncSession, inv: Invoice, lines: list[LineIn]) -> None:
    """Replace a draft's lines and work out every total again (tax copied from each rate)."""
    if len(lines) > 200:
        raise Invalid("An invoice can have at most 200 lines")
    rates = await _rates(db, {ln.tax_rate_id for ln in lines if ln.tax_rate_id})
    products = {ln.product_id for ln in lines if ln.product_id}
    if products:
        found = set((await db.scalars(select(Product.id).where(Product.id.in_(products)))).all())
        if found != products:
            raise Invalid("Choose products from your catalogue")
    for old in (
        await db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id))
    ).all():
        await db.delete(old)
    await db.flush()
    computed = []
    for i, ln in enumerate(lines):
        desc = ln.description.strip()
        if not desc:
            raise Invalid(f"Line {i + 1} needs a description")
        rate = rates.get(ln.tax_rate_id) if ln.tax_rate_id else None
        parts = calc.check_parts(rate.parts) if rate else []
        c = calc.line(ln.quantity, ln.unit_price_minor, ln.discount_minor, parts)
        computed.append((c, ln.discount_minor))
        db.add(
            InvoiceLine(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                position=i,
                product_id=ln.product_id,
                description=desc[:300],
                quantity=ln.quantity,
                unit_price_minor=ln.unit_price_minor,
                discount_minor=ln.discount_minor,
                net_minor=c.net,
                tax_rate_id=rate.id if rate else None,
                tax_name=rate.name if rate else None,
                tax_parts=c.parts,
                tax_minor=c.tax,
                total_minor=c.total,
            )
        )
    t = calc.totals(computed)
    inv.subtotal_minor, inv.discount_minor = t.subtotal, t.discount
    inv.tax_minor, inv.total_minor, inv.tax_breakdown = t.tax, t.total, t.breakdown
    await db.flush()
    # A schedule that no longer adds up to the new total is dropped (one payment again).
    inst = await installments(db, inv.id)
    if inst and sum(i.amount_minor for i in inst) != inv.total_minor:
        for i in inst:
            await db.delete(i)
        await db.flush()


async def lines_from_deal(db: AsyncSession, deal: Deal) -> list[LineIn]:
    rate = await default_rate(db)
    rows = (
        await db.scalars(
            select(DealProduct).where(DealProduct.deal_id == deal.id).order_by(DealProduct.position)
        )
    ).all()
    if not rows and deal.amount_minor:
        return [LineIn(deal.name, 1, deal.amount_minor, 0, rate.id if rate else None)]
    return [
        LineIn(
            description=r.name,
            quantity=r.quantity,
            unit_price_minor=r.unit_price_minor,
            discount_minor=r.discount_minor,
            tax_rate_id=rate.id if rate else None,
            product_id=r.product_id,
        )
        for r in rows
    ]


async def create_draft(
    db: AsyncSession,
    actor: CurrentUser,
    customer: Customer,
    lead: Lead,
    *,
    deal: Deal | None = None,
    entity_id: uuid.UUID | None = None,
    lines: list[LineIn] | None = None,
) -> Invoice:
    need(actor, "invoices.create")
    if customer.status != "active":
        raise Invalid("This customer is inactive. Set them active to bill them.")
    if entity_id:
        entity = await _entity(db, entity_id)
        if deal and deal.currency != entity.currency:
            raise Invalid(f"This deal is in {deal.currency}; choose an entity that bills in it")
    else:
        entity = await default_entity(db, deal.currency if deal else None)
    settings = await db.get(TenantSettings, customer.tenant_id)
    pay = settings.money_default_pay if settings else "both"
    inv = Invoice(
        tenant_id=customer.tenant_id,
        customer_id=customer.id,
        lead_id=lead.id,
        deal_id=deal.id if deal else None,
        entity_id=entity.id,
        currency=entity.currency,
        status="draft",
        pay_link=pay in ("link", "both"),
        pay_direct=pay in ("direct", "both"),
        notes=None,
        tax_breakdown=[],
        created_by_user_id=actor.user.id,
    )
    db.add(inv)
    await db.flush()
    await set_lines(
        db, inv, lines if lines is not None else (await lines_from_deal(db, deal) if deal else [])
    )
    return inv


def editable(inv: Invoice) -> None:
    if inv.status != "draft":
        raise Conflict("An issued invoice cannot be changed. Void it and issue a new one.")


async def change_entity(db: AsyncSession, inv: Invoice, entity_id: uuid.UUID) -> None:
    entity = await _entity(db, entity_id)
    if entity.currency != inv.currency:
        lines = (
            await db.scalars(select(InvoiceLine.id).where(InvoiceLine.invoice_id == inv.id))
        ).all()
        if lines:
            raise Invalid(
                f"This invoice is in {inv.currency}; that entity bills in {entity.currency}. "
                "Remove the lines first, or choose an entity in the same currency."
            )
        inv.currency = entity.currency
    inv.entity_id = entity.id


async def installments(db: AsyncSession, invoice_id: uuid.UUID) -> list[Installment]:
    return list(
        (
            await db.scalars(
                select(Installment)
                .where(Installment.invoice_id == invoice_id)
                .order_by(Installment.position)
            )
        ).all()
    )


async def set_schedule(db: AsyncSession, inv: Invoice, plan: list[tuple[int, date]]) -> None:
    """A draft's installment plan (amount, due date); must add up to the total exactly."""
    editable(inv)
    if inv.total_minor <= 0:
        raise Invalid("Add the invoice lines before splitting it into installments")
    calc.check_schedule(inv.total_minor, plan, inv.issue_date)
    for old in await installments(db, inv.id):
        await db.delete(old)
    await db.flush()
    for i, (amount, due) in enumerate(plan):
        db.add(
            Installment(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                position=i,
                amount_minor=amount,
                due_date=due,
                paid_minor=0,
            )
        )
    await db.flush()


async def delete_draft(db: AsyncSession, actor: CurrentUser, inv: Invoice) -> None:
    need(actor, "invoices.create")
    editable(inv)
    await db.delete(inv)
    await db.flush()


# ---------- issuing and voiding ----------
async def issue(
    db: AsyncSession,
    actor: CurrentUser | None,
    inv: Invoice,
    *,
    issue_date: date | None = None,
    due_date: date | None = None,
) -> Invoice:
    if actor:
        need(actor, "invoices.create")
    inv = await lock(db, inv)
    editable(inv)
    if inv.total_minor <= 0:
        raise Invalid("Add at least one line with an amount before issuing")
    if not (inv.pay_link or inv.pay_direct):
        raise Invalid("Choose how the customer can pay")
    entity = await _entity(db, inv.entity_id)
    day = issue_date or await company_today(db)
    plan = await installments(db, inv.id)
    if plan:
        if plan[0].due_date < day:
            raise Invalid("An installment is due before the invoice date. Fix the schedule.")
        due = plan[-1].due_date
    else:
        due = due_date or inv.due_date or day + timedelta(days=entity.due_days)
        if due < day:
            raise Invalid("The due date cannot be before the invoice date")
        db.add(
            Installment(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                position=0,
                amount_minor=inv.total_minor,
                due_date=due,
                paid_minor=0,
            )
        )
    inv.number = await next_numbers(db, entity.id, day, invoice=True)
    inv.status, inv.issue_date, inv.due_date = "issued", day, due
    inv.issued_at, inv.issued_by_user_id = L.now(), actor.user.id if actor else None
    if inv.repeat_months:
        inv.repeat_next_date = calc.add_months(day, inv.repeat_months)
    inv.version += 1
    await db.flush()
    lead = await db.get(Lead, inv.lead_id)
    await L.log(
        db,
        lead,
        "invoice_issued",
        f"Invoice {inv.number} issued: {display(inv.total_minor, inv.currency)}",
        actor,
        {"invoice_id": str(inv.id)},
    )
    await L.event(db, lead, "invoice.created", _payload(inv))
    return inv


def _payload(inv: Invoice, **extra) -> dict:
    return {
        "invoice_id": str(inv.id),
        "customer_id": str(inv.customer_id),
        "number": inv.number,
        "currency": inv.currency,
        "total_minor": inv.total_minor,
        "paid_minor": inv.paid_minor,
        **extra,
    }


async def void(db: AsyncSession, actor: CurrentUser, inv: Invoice, reason: str) -> Invoice:
    need(actor, "invoices.void")
    inv = await lock(db, inv)
    if inv.status == "draft":
        raise Invalid("A draft has no number: delete it instead")
    if inv.status == "void":
        raise Conflict("This invoice is already void")
    reason = reason.strip()
    if not reason:
        raise Invalid("Say why the invoice is voided")
    live = await db.scalar(
        select(func.count()).where(Payment.invoice_id == inv.id, Payment.status == "ok")
    )
    if live:
        raise Conflict("This invoice has payments. Reverse them first, then void it.")
    for link in (
        await db.scalars(
            select(PaymentLink).where(
                PaymentLink.invoice_id == inv.id, PaymentLink.status == "active"
            )
        )
    ).all():
        link.status = "cancelled"
    inv.status, inv.voided_at, inv.voided_by_user_id = "void", L.now(), actor.user.id
    inv.void_reason, inv.repeat_next_date = reason[:500], None
    inv.version += 1
    await db.flush()
    lead = await db.get(Lead, inv.lead_id)
    await L.log(
        db,
        lead,
        "invoice_voided",
        f"Invoice {inv.number} voided: {reason}",
        actor,
        {"invoice_id": str(inv.id)},
    )
    await L.event(db, lead, "invoice.voided", _payload(inv, reason=reason))
    return inv


async def set_repeat(
    db: AsyncSession, actor: CurrentUser, inv: Invoice, months: int | None
) -> None:
    need(actor, "invoices.create")
    if months not in (None, 1, 3, 6, 12):
        raise Invalid("Repeat every 1, 3, 6 or 12 months")
    if inv.status == "void":
        raise Conflict("A void invoice does not repeat")
    inv.repeat_months = months
    if inv.status != "draft":
        inv.repeat_next_date = calc.add_months(inv.issue_date, months) if months else None
        if inv.repeat_next_date and inv.repeat_next_date <= await company_today(db):
            inv.repeat_next_date = calc.add_months(await company_today(db), months)
    inv.version += 1
    await db.flush()


# ---------- payments ----------
def _status(inv: Invoice) -> str:
    if inv.paid_minor == 0:
        return "issued"
    return "paid" if inv.paid_minor == inv.total_minor else "partly_paid"


async def apply_payment(
    db: AsyncSession,
    inv: Invoice,
    *,
    amount: int,
    method: str,
    paid_on: date,
    actor: CurrentUser | None,
    reference: str | None = None,
    proof_file_id: uuid.UUID | None = None,
    gateway_account_id: uuid.UUID | None = None,
    gateway_payment_id: str | None = None,
) -> Payment:
    inv = await lock(db, inv)
    if inv.status not in OPEN:
        raise Conflict(
            "This invoice is fully paid"
            if inv.status == "paid"
            else "Only issued invoices take payments"
        )
    plan = await installments(db, inv.id)
    parts = calc.allocate(amount, [(i, i.amount_minor, i.paid_minor) for i in plan])
    payment = Payment(
        tenant_id=inv.tenant_id,
        invoice_id=inv.id,
        lead_id=inv.lead_id,
        entity_id=inv.entity_id,
        amount_minor=amount,
        currency=inv.currency,
        method=method,
        paid_on=paid_on,
        reference=(reference or "").strip()[:120] or None,
        gateway_account_id=gateway_account_id,
        gateway_payment_id=gateway_payment_id,
        proof_file_id=proof_file_id,
        receipt_number=await next_numbers(db, inv.entity_id, paid_on, invoice=False),
        recorded_by_user_id=actor.user.id if actor else None,
        status="ok",
    )
    db.add(payment)
    await db.flush()
    for inst, part in parts:
        inst.paid_minor += part
        db.add(
            PaymentAllocation(
                tenant_id=inv.tenant_id,
                payment_id=payment.id,
                installment_id=inst.id,
                amount_minor=part,
            )
        )
    inv.paid_minor += amount
    inv.status = _status(inv)
    inv.version += 1
    # Links for installments that are now paid (by any route) are no longer needed.
    done = {i.id for i in plan if i.paid_minor >= i.amount_minor}
    for link in (
        await db.scalars(
            select(PaymentLink).where(
                PaymentLink.invoice_id == inv.id, PaymentLink.status == "active"
            )
        )
    ).all():
        if inv.status == "paid" or link.installment_id in done:
            link.status = "cancelled"
    await db.flush()
    lead = await db.get(Lead, inv.lead_id)
    how = "online" if method == "gateway" else f"by {method}"
    await L.log(
        db,
        lead,
        "payment_received",
        f"{display(amount, inv.currency)} received {how} for {inv.number} "
        f"(receipt {payment.receipt_number})",
        actor,
        {"invoice_id": str(inv.id), "payment_id": str(payment.id)},
    )
    await L.event(
        db,
        lead,
        "payment.received",
        _payload(inv, payment_id=str(payment.id), amount_minor=amount, method=method),
    )
    return payment


async def save_proof(
    db: AsyncSession, actor: CurrentUser, inv: Invoice, data: bytes, name: str
) -> StoredFile:
    """The proof of a manual payment, kept like any other file (counts toward storage)."""
    content_type, ext = storage.check_type(data, name, allow_office=False)
    settings = await db.get(TenantSettings, inv.tenant_id)
    if await C.storage_used(db) + len(data) > settings.storage_quota_bytes:
        raise Invalid("Your company has used all of its file storage. Ask your admin to add more.")
    saved = storage.save(inv.tenant_id, data, ext, content_type)
    try:
        async with db.begin_nested():
            stored = StoredFile(
                tenant_id=inv.tenant_id,
                lead_id=inv.lead_id,
                document_id=None,
                path=saved.path,
                original_name=storage.clean_name(name),
                content_type=content_type,
                size_bytes=saved.size_bytes,
                sha256=saved.sha256,
                uploaded_by_user_id=actor.user.id,
            )
            db.add(stored)
            await db.flush()
    except Exception:
        storage.remove(saved.path)
        raise
    return stored


async def record_manual(
    db: AsyncSession,
    actor: CurrentUser,
    inv: Invoice,
    *,
    amount: int,
    method: str,
    paid_on: date,
    reference: str | None,
    proof: StoredFile,
) -> Payment:
    need(actor, "payments.record")
    if method not in METHODS:
        raise Invalid("Choose how it was paid")
    check_amount(amount, "Amount")
    if paid_on > await company_today(db):
        raise Invalid("The payment date cannot be in the future")
    return await apply_payment(
        db,
        inv,
        amount=amount,
        method=method,
        paid_on=paid_on,
        actor=actor,
        reference=reference,
        proof_file_id=proof.id,
    )


async def reverse(db: AsyncSession, actor: CurrentUser, payment: Payment, reason: str) -> Payment:
    need(actor, "payments.reverse")
    reason = reason.strip()
    if not reason:
        raise Invalid("Say why the payment is reversed")
    inv = await lock(db, await db.get(Invoice, payment.invoice_id))
    payment = await db.scalar(
        select(Payment)
        .where(Payment.id == payment.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if payment.status == "reversed":
        raise Conflict("This payment is already reversed")
    for alloc in (
        await db.scalars(
            select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
        )
    ).all():
        inst = await db.get(Installment, alloc.installment_id)
        inst.paid_minor -= alloc.amount_minor
    inv.paid_minor -= payment.amount_minor
    inv.status = _status(inv) if inv.status != "void" else "void"
    inv.version += 1
    payment.status, payment.reversed_at = "reversed", L.now()
    payment.reversed_by_user_id, payment.reverse_reason = actor.user.id, reason[:500]
    await db.flush()
    lead = await db.get(Lead, inv.lead_id)
    await L.log(
        db,
        lead,
        "payment_reversed",
        f"Payment {payment.receipt_number} of {display(payment.amount_minor, payment.currency)} "
        f"reversed: {reason}",
        actor,
        {"invoice_id": str(inv.id), "payment_id": str(payment.id)},
    )
    await L.event(
        db,
        lead,
        "payment.reversed",
        _payload(inv, payment_id=str(payment.id), amount_minor=payment.amount_minor, reason=reason),
    )
    return payment


# ---------- balances ----------
async def balances(db: AsyncSession, customer_id: uuid.UUID, day: date) -> list[dict]:
    """Per currency (never added together): billed, paid, due and overdue."""
    rows = (
        await db.execute(
            select(Invoice.currency, func.sum(Invoice.total_minor), func.sum(Invoice.paid_minor))
            .where(Invoice.customer_id == customer_id, Invoice.status.in_(BILLED))
            .group_by(Invoice.currency)
        )
    ).all()
    overdue = dict(
        (
            await db.execute(
                select(
                    Invoice.currency, func.sum(Installment.amount_minor - Installment.paid_minor)
                )
                .join(Installment, Installment.invoice_id == Invoice.id)
                .where(
                    Invoice.customer_id == customer_id,
                    Invoice.status.in_(OPEN),
                    Installment.due_date < day,
                )
                .group_by(Invoice.currency)
            )
        ).all()
    )
    return [
        {
            "currency": cur,
            "billed_minor": int(billed),
            "paid_minor": int(paid),
            "due_minor": int(billed - paid),
            "overdue_minor": int(overdue.get(cur) or 0),
        }
        for cur, billed, paid in sorted(rows)
    ]


def installment_state(inst: Installment, day: date) -> str:
    if inst.paid_minor >= inst.amount_minor:
        return "paid"
    if inst.due_date < day:
        return "overdue"
    return "partly_paid" if inst.paid_minor else "due"

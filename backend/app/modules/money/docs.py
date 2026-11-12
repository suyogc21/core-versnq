"""Turns an invoice or payment in the database into its PDF."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import Customer, Lead
from app.modules.money import pdf
from app.modules.money import service as S
from app.modules.money.models import BillingEntity, Invoice, InvoiceLine, Payment, PaymentLink

METHOD_WORDS = {
    "gateway": "Online payment",
    "bank": "Bank transfer",
    "upi": "UPI",
    "cash": "Cash",
    "cheque": "Cheque",
    "card": "Card",
    "other": "Other",
}


def _seller(e: BillingEntity) -> pdf.Party:
    tax = f"{e.tax_label or 'Tax ID'}: {e.tax_id}" if e.tax_id else None
    return pdf.Party(e.legal_name, [e.address or "", tax or "", e.email or "", e.phone or ""])


async def _buyer(db: AsyncSession, inv: Invoice) -> pdf.Party:
    lead = await db.get(Lead, inv.lead_id)
    customer = await db.get(Customer, inv.customer_id)
    return pdf.Party(
        lead.display_name or "Customer",
        [f"Customer {customer.number}", lead.primary_email or "", lead.primary_phone or ""],
    )


async def invoice_pdf(db: AsyncSession, inv: Invoice) -> bytes:
    e = await db.get(BillingEntity, inv.entity_id)
    lines = (
        await db.scalars(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == inv.id)
            .order_by(InvoiceLine.position)
        )
    ).all()
    plan = await S.installments(db, inv.id)
    day = await S.company_today(db)
    links = []
    if inv.pay_link:
        links = [
            (ln.url, ln.amount_minor)
            for ln in (
                await db.scalars(
                    select(PaymentLink)
                    .where(PaymentLink.invoice_id == inv.id, PaymentLink.status == "active")
                    .order_by(PaymentLink.created_at)
                )
            ).all()
        ]
    upi = None
    if inv.pay_direct and e.upi_id and inv.currency == "INR":
        nxt = next((i for i in plan if i.paid_minor < i.amount_minor), None)
        if nxt is not None:
            upi = (e.upi_id, e.legal_name, nxt.amount_minor - nxt.paid_minor)
    doc = pdf.InvoiceDoc(
        title="Tax invoice" if inv.tax_minor else "Invoice",
        number=inv.number or "DRAFT",
        issue_date=inv.issue_date or day,
        due_date=inv.due_date,
        currency=inv.currency,
        seller=_seller(e),
        buyer=await _buyer(db, inv),
        lines=[
            {
                "description": ln.description,
                "quantity": ln.quantity,
                "unit": ln.unit_price_minor,
                "discount": ln.discount_minor,
                "tax_name": ln.tax_name,
                "total": ln.total_minor,
            }
            for ln in lines
        ],
        subtotal=inv.subtotal_minor,
        breakdown=inv.tax_breakdown,
        total=inv.total_minor,
        paid=inv.paid_minor,
        installments=[
            {"due_date": i.due_date, "amount": i.amount_minor, "paid": i.paid_minor} for i in plan
        ],
        bank_details=e.bank_details if inv.pay_direct else None,
        upi=upi,
        links=links,
        notes=inv.notes,
        terms=e.terms,
        void_reason=inv.void_reason,
    )
    return pdf.invoice(doc)


async def receipt_pdf(db: AsyncSession, payment: Payment) -> bytes:
    inv = await db.get(Invoice, payment.invoice_id)
    e = await db.get(BillingEntity, payment.entity_id)
    later = (
        await db.scalars(
            select(Payment.amount_minor).where(
                Payment.invoice_id == inv.id,
                Payment.status == "ok",
                Payment.created_at > payment.created_at,
            )
        )
    ).all()
    doc = pdf.ReceiptDoc(
        number=payment.receipt_number,
        paid_on=payment.paid_on,
        currency=payment.currency,
        amount=payment.amount_minor,
        method=METHOD_WORDS.get(payment.method, payment.method),
        reference=payment.reference,
        invoice_number=inv.number or "",
        balance_after=inv.total_minor - inv.paid_minor + sum(later),
        seller=_seller(e),
        buyer=await _buyer(db, inv),
        reversed_reason=payment.reverse_reason,
    )
    return pdf.receipt(doc)

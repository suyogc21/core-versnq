"""Emails to the customer about their invoices (Decision log #34): the invoice when issued,
a receipt for every payment, reminders, and a note when an invoice is voided.

They go from the company's own mailbox. A message is queued in the same transaction as the
change and sent by the worker (retried on failure), so a slow mail server never slows Core.
Customers who unsubscribed (suppression list) are never emailed.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets
from app.core.errors import Invalid
from app.core.money import display
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.consent import is_suppressed
from app.modules.crm.models import Lead
from app.modules.money import docs, mailbox
from app.modules.money.models import (
    BillingEntity,
    Installment,
    Invoice,
    MailAccount,
    MoneyMessage,
    Payment,
    PaymentLink,
)
from app.modules.money.service import company_today
from app.modules.settings.models import TenantSettings
from app.workers.queue import enqueue

KINDS = ("invoice", "receipt", "reminder", "void")


def box(account: MailAccount) -> mailbox.Box:
    return mailbox.Box(
        host=account.host,
        port=account.port,
        security=account.security,
        username=account.username,
        password=secrets.decrypt(account.password_enc),
        from_name=account.from_name,
        from_email=account.from_email,
        reply_to=account.reply_to,
    )


async def _account(db: AsyncSession) -> MailAccount | None:
    return await db.scalar(select(MailAccount).where(MailAccount.is_active.is_(True)))


def _subject(kind: str, inv: Invoice, entity: BillingEntity, payment: Payment | None) -> str:
    who = entity.legal_name
    if kind == "invoice":
        return f"Invoice {inv.number} from {who}"
    if kind == "receipt":
        return f"Receipt {payment.receipt_number} for invoice {inv.number}"
    if kind == "reminder":
        return f"Reminder: payment due for invoice {inv.number}"
    return f"Invoice {inv.number} has been cancelled"


async def queue(
    db: AsyncSession,
    inv: Invoice,
    kind: str,
    *,
    payment: Payment | None = None,
    actor: CurrentUser | None = None,
    strict: bool = False,
) -> MoneyMessage | None:
    """Queue one email. strict (a person pressed "Email"): say why it cannot go.
    Otherwise (automatic): quietly skip."""

    def stop(why: str) -> None:
        if strict:
            raise Invalid(why)

    if await _account(db) is None:
        return stop("Connect your company's mailbox in Settings → Money to email customers")
    lead = await db.get(Lead, inv.lead_id)
    to = lead.primary_email
    if not to:
        return stop("This customer has no email address")
    if await is_suppressed(db, "email", [to.lower()]):
        return stop("This customer has unsubscribed from email")
    entity = await db.get(BillingEntity, inv.entity_id)
    msg = MoneyMessage(
        tenant_id=inv.tenant_id,
        invoice_id=inv.id,
        payment_id=payment.id if payment else None,
        kind=kind,
        channel="email",
        to_address=to,
        subject=_subject(kind, inv, entity, payment)[:300],
        status="queued",
        created_by_user_id=actor.user.id if actor else None,
    )
    db.add(msg)
    await db.flush()
    await enqueue("money_mail_job", str(inv.tenant_id), str(msg.id), defer_by=3)
    return msg


async def auto(db: AsyncSession, inv: Invoice, kind: str, *, payment: Payment | None = None):
    """An automatic email, if the company has this kind switched on (Settings → Money)."""
    settings = await db.get(TenantSettings, inv.tenant_id)
    if settings and (settings.money_emails or {}).get(kind, True):
        await queue(db, inv, kind, payment=payment)


async def _body(
    db: AsyncSession, kind: str, inv: Invoice, entity: BillingEntity, payment: Payment | None
) -> str:
    lead = await db.get(Lead, inv.lead_id)
    name = (lead.display_name or "there").split(" ")[0]
    cur = inv.currency
    due = inv.total_minor - inv.paid_minor
    lines = [f"Hello {name},", ""]
    if kind == "invoice":
        lines.append(
            f"Please find attached invoice {inv.number} for {display(inv.total_minor, cur)}, "
            f"due by {inv.due_date:%d %b %Y}."
        )
    elif kind == "receipt":
        lines.append(
            f"Thank you. We received {display(payment.amount_minor, cur)} for invoice "
            f"{inv.number}. Your receipt {payment.receipt_number} is attached."
        )
        lines.append(
            f"Balance still due: {display(due, cur)}." if due else "This invoice is now fully paid."
        )
    elif kind == "reminder":
        nxt = await db.scalar(
            select(Installment)
            .where(
                Installment.invoice_id == inv.id, Installment.paid_minor < Installment.amount_minor
            )
            .order_by(Installment.position)
            .limit(1)
        )
        if nxt:
            left = nxt.amount_minor - nxt.paid_minor
            when = "was due" if nxt.due_date < await company_today(db) else "is due"
            lines.append(
                f"A payment of {display(left, cur)} for invoice {inv.number} {when} on "
                f"{nxt.due_date:%d %b %Y}."
            )
    else:
        lines.append(f"Invoice {inv.number} has been cancelled. You do not need to pay it.")
        if inv.void_reason:
            lines.append(f"Reason: {inv.void_reason}")
    if kind in ("invoice", "reminder") and due:
        how: list[str] = []
        if inv.pay_link:
            for link in (
                await db.scalars(
                    select(PaymentLink).where(
                        PaymentLink.invoice_id == inv.id, PaymentLink.status == "active"
                    )
                )
            ).all():
                how.append(f"Pay {display(link.amount_minor, cur)} online: {link.url}")
        if inv.pay_direct:
            if entity.upi_id and cur == "INR":
                how.append(f"UPI: {entity.upi_id} (or scan the QR code on the invoice)")
            if entity.bank_details:
                how.append(f"Bank transfer:\n{entity.bank_details}")
        if how:
            lines += ["", "How to pay:", *how]
    lines += ["", "Regards,", entity.legal_name]
    if entity.email or entity.phone:
        lines.append(" · ".join(x for x in (entity.email, entity.phone) if x))
    return "\n".join(lines)


async def send(db: AsyncSession, message_id: uuid.UUID) -> str:
    """Worker: send one queued email. Returns its status."""
    msg = await db.scalar(
        select(MoneyMessage).where(MoneyMessage.id == message_id).with_for_update(skip_locked=True)
    )
    if msg is None or msg.status != "queued":
        return msg.status if msg else "missing"
    account = await _account(db)
    inv = await db.get(Invoice, msg.invoice_id)
    if account is None:
        msg.status, msg.error = "failed", "The company's mailbox is not connected"
        await db.flush()
        return msg.status
    entity = await db.get(BillingEntity, inv.entity_id)
    payment = await db.get(Payment, msg.payment_id) if msg.payment_id else None
    files = []
    if msg.kind in ("invoice", "reminder", "void"):
        files.append(mailbox.Attachment(f"{inv.number}.pdf", await docs.invoice_pdf(db, inv)))
    elif payment is not None:
        files.append(
            mailbox.Attachment(f"{payment.receipt_number}.pdf", await docs.receipt_pdf(db, payment))
        )
    email = mailbox.build(
        box(account),
        msg.to_address,
        msg.subject,
        await _body(db, msg.kind, inv, entity, payment),
        files,
    )
    try:
        await mailbox.send(box(account), email)
    except Invalid as e:
        msg.error = e.detail[:500]
        account.last_error = msg.error
        raise
    msg.status, msg.sent_at, msg.error = "sent", L.now(), None
    lead = await db.get(Lead, inv.lead_id)
    word = {
        "invoice": "Invoice",
        "receipt": "Receipt",
        "reminder": "Reminder",
        "void": "Cancellation",
    }
    await L.log(
        db,
        lead,
        "invoice_emailed",
        f"{word[msg.kind]} for {inv.number} emailed to {msg.to_address}",
        None,
        {"invoice_id": str(inv.id), "message_id": str(msg.id)},
    )
    await db.flush()
    return msg.status

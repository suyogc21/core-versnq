"""Payment links on the gateway's own page, and what happens when the gateway says "paid".

A webhook is applied only when its signature is right, it has not been seen before, it matches
one of our open links, and the amount and currency match exactly. Anything else is kept for
Finance to look at ("flagged"), never applied.
"""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets
from app.core.errors import Conflict, Invalid, NotFound
from app.core.money import display
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import Lead
from app.modules.crm.notify import notify
from app.modules.money import gateways as G
from app.modules.money import service as S
from app.modules.money.models import (
    GatewayAccount,
    GatewayEvent,
    Installment,
    Invoice,
    Payment,
    PaymentLink,
)
from app.modules.roles.models import Role
from app.modules.users.models import User


def keys(account: GatewayAccount) -> G.Keys:
    return G.Keys(
        gateway=account.gateway,
        key_id=account.key_id,
        secret=secrets.decrypt(account.secret_enc),
        webhook_secret=secrets.decrypt(account.webhook_secret_enc),
    )


async def account_for(db: AsyncSession, entity_id: uuid.UUID) -> GatewayAccount | None:
    return await db.scalar(
        select(GatewayAccount)
        .where(GatewayAccount.entity_id == entity_id, GatewayAccount.is_active.is_(True))
        .order_by(GatewayAccount.created_at)
        .limit(1)
    )


async def create_link(
    db: AsyncSession, actor: CurrentUser, inv: Invoice, installment_id: uuid.UUID | None
) -> PaymentLink:
    S.need(actor, "invoices.create")
    if inv.status not in S.OPEN:
        raise Conflict("Payment links are only for issued invoices with money still due")
    if not inv.pay_link:
        raise Invalid("This invoice is set to be paid directly, not by a link")
    account = await account_for(db, inv.entity_id)
    if account is None:
        raise Invalid("Connect Razorpay or Stripe for this billing entity in Settings → Money")
    inst = None
    if installment_id:
        inst = await db.scalar(
            select(Installment).where(
                Installment.id == installment_id, Installment.invoice_id == inv.id
            )
        )
        if inst is None:
            raise NotFound("Installment not found")
        amount = inst.amount_minor - inst.paid_minor
    else:
        amount = inv.total_minor - inv.paid_minor
    if amount <= 0:
        raise Conflict("Nothing is left to pay here")
    same = await db.scalar(
        select(PaymentLink).where(
            PaymentLink.invoice_id == inv.id,
            PaymentLink.installment_id == inst.id if inst else PaymentLink.installment_id.is_(None),
            PaymentLink.amount_minor == amount,
            PaymentLink.status == "active",
        )
    )
    if same:
        return same  # one open link per amount: sending it again is the same link
    lead = await db.get(Lead, inv.lead_id)
    what = f"Invoice {inv.number}" + (f", installment {inst.position + 1}" if inst else "")
    new = await G.gateway(keys(account)).create(
        amount=amount,
        currency=inv.currency,
        description=what,
        reference=f"{inv.number}-{(inst.position + 1) if inst else 'all'}",
        customer={
            "name": lead.display_name,
            "email": lead.primary_email,
            "contact": lead.primary_phone,
        },
    )
    link = PaymentLink(
        tenant_id=inv.tenant_id,
        invoice_id=inv.id,
        installment_id=inst.id if inst else None,
        gateway_account_id=account.id,
        gateway=account.gateway,
        gateway_link_id=new.link_id,
        amount_minor=amount,
        currency=inv.currency,
        url=new.url,
        status="active",
        created_by_user_id=actor.user.id,
    )
    db.add(link)
    await db.flush()
    await L.log(
        db,
        lead,
        "payment_link_sent",
        f"Payment link for {display(amount, inv.currency)} ({what})",
        actor,
        {"invoice_id": str(inv.id), "link_id": str(link.id), "url": new.url},
    )
    return link


async def cancel_link(db: AsyncSession, actor: CurrentUser, link: PaymentLink) -> None:
    S.need(actor, "invoices.create")
    if link.status != "active":
        raise Conflict("This link is not active")
    account = await db.get(GatewayAccount, link.gateway_account_id)
    await G.gateway(keys(account)).cancel(link.gateway_link_id)
    link.status = "cancelled"
    await db.flush()


async def _money_people(db: AsyncSession) -> list[uuid.UUID]:
    """Who hears about a payment that needs a person: Finance, Admins and Owners."""
    return list(
        (
            await db.scalars(
                select(User.id)
                .join(Role, Role.id == User.role_id)
                .where(User.status == "active", Role.key.in_(("owner", "admin", "finance")))
            )
        ).all()
    )


async def apply_paid(
    db: AsyncSession, account: GatewayAccount, paid: G.Paid
) -> tuple[str, str | None]:
    """(result, detail): applied / ignored / flagged. Safe to call again for the same payment."""
    if await db.scalar(
        select(Payment.id).where(
            Payment.gateway_account_id == account.id,
            Payment.gateway_payment_id == paid.payment_id,
        )
    ):
        return "ignored", "payment already recorded"
    link = await db.scalar(
        select(PaymentLink).where(
            PaymentLink.gateway_account_id == account.id,
            PaymentLink.gateway_link_id == paid.link_id,
        )
    )
    if link is None:
        return "ignored", "not one of our links"
    inv = await db.get(Invoice, link.invoice_id)
    problem = None
    if paid.currency != link.currency or paid.amount_minor != link.amount_minor:
        problem = (
            f"paid {display(paid.amount_minor, paid.currency)}, link was for "
            f"{display(link.amount_minor, link.currency)}"
        )
    elif inv.status not in S.OPEN:
        problem = f"invoice {inv.number} is {inv.status.replace('_', ' ')}"
    elif paid.amount_minor > inv.total_minor - inv.paid_minor:
        problem = (
            f"more than the {display(inv.total_minor - inv.paid_minor, inv.currency)} still due"
        )
    if problem:
        link.status = "flagged"
        lead = await db.get(Lead, inv.lead_id)
        await notify(
            db,
            inv.tenant_id,
            await _money_people(db),
            "payment_flagged",
            f"Check an online payment for {inv.number or 'an invoice'}: {problem}",
            lead.id,
        )
        await db.flush()
        return "flagged", problem
    payment = await S.apply_payment(
        db,
        inv,
        amount=paid.amount_minor,
        method="gateway",
        paid_on=await S.company_today(db),
        actor=None,
        reference=paid.payment_id,
        gateway_account_id=account.id,
        gateway_payment_id=paid.payment_id,
    )
    link.status, link.payment_id, link.paid_at = "paid", payment.id, L.now()
    await db.flush()
    from app.modules.money import messages  # sends the receipt

    await messages.auto(db, inv, "receipt", payment=payment)
    return "applied", None


async def handle_webhook(
    db: AsyncSession, account: GatewayAccount, headers: dict, body: bytes
) -> str:
    hook = G.gateway(keys(account)).webhook(headers, body)  # GatewayError on a bad signature
    new = await db.execute(
        insert(GatewayEvent)
        .values(
            id=uuid.uuid4(),
            tenant_id=account.tenant_id,
            gateway_account_id=account.id,
            event_id=hook.event_id[:120],
            event_type=hook.event_type[:80],
            payload=hook.payload,
            result="received",
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "gateway_account_id", "event_id"])
        .returning(GatewayEvent.id)
    )
    event_id = new.scalar()
    if event_id is None:
        return "duplicate"
    event = await db.get(GatewayEvent, event_id)
    if hook.paid is None:
        event.result = "ignored"
    else:
        event.result, event.detail = await apply_paid(db, account, hook.paid)
    await db.flush()
    return event.result


async def check_open_links(db: AsyncSession) -> int:
    """Nightly: ask the gateway about links still open, in case a webhook was missed."""
    applied = 0
    cutoff = L.now() - timedelta(minutes=10)
    links = (
        await db.scalars(
            select(PaymentLink).where(
                PaymentLink.status == "active", PaymentLink.created_at < cutoff
            )
        )
    ).all()
    for link in links:
        account = await db.get(GatewayAccount, link.gateway_account_id)
        if account is None or not account.is_active:
            continue
        try:
            paid = await G.gateway(keys(account)).lookup(link.gateway_link_id)
        except (G.GatewayError, ValueError, OSError):
            continue
        if paid is None:
            continue
        result, _ = await apply_paid(db, account, paid)
        applied += result == "applied"
    await db.flush()
    return applied

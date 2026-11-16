"""Once a night for each company: payment reminders, repeat invoices and the check on payment
links still open. Reminders are in Core now (notification + task for the owner, events for
automations) and go to the customer by email when the company's mailbox is connected."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import display
from app.modules.crm import leads as L
from app.modules.crm.models import Customer, Lead, Task
from app.modules.crm.notify import notify
from app.modules.money import messages
from app.modules.money import service as S
from app.modules.money.models import Installment, Invoice, InvoiceLine
from app.modules.settings.models import TenantSettings


async def remind(db: AsyncSession) -> int:
    settings = await db.scalar(select(TenantSettings))
    if settings is None:
        return 0
    day = S.today(settings.timezone)
    before = settings.money_reminder_before_days
    every = settings.money_overdue_every_days
    rows = (
        await db.execute(
            select(Installment, Invoice, Lead)
            .join(Invoice, Invoice.id == Installment.invoice_id)
            .join(Lead, Lead.id == Invoice.lead_id)
            .where(
                Invoice.status.in_(S.OPEN),
                Installment.paid_minor < Installment.amount_minor,
                Installment.due_date <= day + timedelta(days=before),
            )
            .order_by(Installment.due_date)
        )
    ).all()
    sent = 0
    emailed: set = set()  # one email per invoice per night
    for inst, inv, lead in rows:
        left = inst.amount_minor - inst.paid_minor
        money = display(left, inv.currency)
        kind = None
        if inst.due_date > day:
            if before and inst.before_sent_on is None:
                kind, inst.before_sent_on = "soon", day
                on = f"{inst.due_date:%d %b}"
                title = f"{money} from {lead.display_name} is due on {on} ({inv.number})"
        elif inst.due_date == day:
            if inst.due_sent_on is None:
                kind, inst.due_sent_on = "today", day
                title = f"{money} from {lead.display_name} is due today ({inv.number})"
        elif inst.overdue_sent_on is None or (day - inst.overdue_sent_on).days >= every:
            kind, inst.overdue_sent_on = "overdue", day
            late = (day - inst.due_date).days
            title = f"{money} from {lead.display_name} is {late} days overdue ({inv.number})"
        if kind is None:
            continue
        sent += 1
        payload = S._payload(
            inv, installment_id=str(inst.id), amount_minor=left, due_date=inst.due_date.isoformat()
        )
        if kind == "overdue":
            await L.event(
                db, lead, "payment.overdue", payload | {"days": (day - inst.due_date).days}
            )
        else:
            await L.event(db, lead, "payment.due", payload | {"when": kind})
        if lead.owner_user_id:
            await notify(db, inv.tenant_id, [lead.owner_user_id], f"payment_{kind}", title, lead.id)
            if kind == "overdue":
                has_task = await db.scalar(
                    select(Task.id).where(
                        Task.lead_id == lead.id, Task.created_from == "money", Task.status == "open"
                    )
                )
                if not has_task:
                    db.add(
                        Task(
                            tenant_id=inv.tenant_id,
                            lead_id=lead.id,
                            title=f"Follow up overdue payment {inv.number}",
                            due_at=L.now(),
                            owner_user_id=lead.owner_user_id,
                            created_from="money",
                        )
                    )
        if inv.id not in emailed:
            emailed.add(inv.id)
            await messages.auto(db, inv, "reminder")
            from app.modules.engage import whatsapp as WA  # step 10b (W7)

            await WA.payment_reminder(
                db, lead, number=inv.number, amount_due=money, due_date=inst.due_date,
                invoice_id=inv.id,
            )  # fmt: skip
    await db.flush()
    return sent


async def repeat(db: AsyncSession) -> int:
    """Repeat invoices whose next date has come: the next one is issued and emailed."""
    day = await S.company_today(db)
    due = (
        await db.scalars(
            select(Invoice).where(
                Invoice.status.in_(S.BILLED),
                Invoice.repeat_months.isnot(None),
                Invoice.repeat_next_date <= day,
            )
        )
    ).all()
    made = 0
    for old in due:
        customer = await db.get(Customer, old.customer_id)
        old.repeat_next_date = None  # the chain continues from the new invoice
        if customer is None or customer.status != "active":
            continue
        new = Invoice(
            tenant_id=old.tenant_id,
            customer_id=old.customer_id,
            lead_id=old.lead_id,
            deal_id=old.deal_id,
            entity_id=old.entity_id,
            currency=old.currency,
            status="draft",
            pay_link=old.pay_link,
            pay_direct=old.pay_direct,
            notes=old.notes,
            tax_breakdown=[],
            repeat_months=old.repeat_months,
            repeated_from_id=old.id,
            created_by_user_id=old.created_by_user_id,
            brand_id=old.brand_id,
        )
        db.add(new)
        await db.flush()
        lines = (
            await db.scalars(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == old.id)
                .order_by(InvoiceLine.position)
            )
        ).all()
        await S.set_lines(
            db,
            new,
            [
                S.LineIn(
                    ln.description,
                    ln.quantity,
                    ln.unit_price_minor,
                    ln.discount_minor,
                    ln.tax_rate_id,
                    ln.product_id,
                )
                for ln in lines
            ],
        )
        if new.total_minor <= 0:
            await db.delete(new)
            continue
        gap = (old.due_date - old.issue_date).days
        await S.issue(db, None, new, issue_date=day, due_date=day + timedelta(days=gap))
        await messages.auto(db, new, "invoice")
        made += 1
    await db.flush()
    return made

"""Key accounts (step 7b, Decision log #36).

A key account is an organisation marked as key. Who sees it: whoever can see the organisation,
plus its account owner. Who changes it: `key_accounts.manage`, or the account owner (who works
leads). Every change is an activity on the organisation's timeline and an `account.updated`
event. Money roll-ups are per currency, never added across currencies (rule 7).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.events import emit
from app.modules.accounts.models import (
    AccountCell,
    AccountContact,
    AccountUnit,
    KeyAccount,
)
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import Deal, DealProduct, Lead
from app.modules.money.models import Installment, Invoice, Payment
from app.modules.settings.models import TenantSettings

TIERS = ("strategic", "growth", "maintain")
HEALTH = ("on_track", "at_risk", "off_track")
QUIET_DAYS = 30


# ---------- who may see and change ----------
async def visible(db: AsyncSession, actor: CurrentUser):
    """SQL condition on (KeyAccount joined with its organisation Lead)."""
    return or_(await L.visibility_filter(db, actor), KeyAccount.owner_user_id == actor.user.id)


async def get_visible(
    db: AsyncSession, actor: CurrentUser, account_id: uuid.UUID
) -> tuple[KeyAccount, Lead]:
    row = (
        await db.execute(
            select(KeyAccount, Lead)
            .join(Lead, Lead.id == KeyAccount.org_lead_id)
            .where(KeyAccount.id == account_id, await visible(db, actor))
        )
    ).first()
    if row is None:
        raise NotFound("Key account not found")
    return row[0], row[1]


def can_edit(actor: CurrentUser, account: KeyAccount) -> bool:
    if L.can(actor, "key_accounts.manage"):
        return True
    return L.can(actor, "leads.edit") and account.owner_user_id == actor.user.id


def need_edit(actor: CurrentUser, account: KeyAccount) -> None:
    if not can_edit(actor, account):
        raise Forbidden("permission_denied")


def need_manage(actor: CurrentUser) -> None:
    if not L.can(actor, "key_accounts.manage"):
        raise Forbidden("permission_denied")


async def changed(
    db: AsyncSession, actor: CurrentUser | None, account: KeyAccount, org: Lead, what: str
) -> None:
    """Timeline entry on the organisation, and the event for automations and webhooks."""
    await L.log(db, org, "key_account_updated", what, actor, {"account_id": str(account.id)})
    await emit(
        db,
        account.tenant_id,
        "account.updated",
        {"account_id": str(account.id), "lead_id": str(org.id), "change": what},
    )


# ---------- the group tree ----------
async def _parents(db: AsyncSession) -> dict[uuid.UUID, uuid.UUID | None]:
    return dict((await db.execute(select(KeyAccount.id, KeyAccount.parent_id))).all())


async def check_parent(db: AsyncSession, account_id: uuid.UUID, parent_id: uuid.UUID | None):
    """A parent must be another key account, and the tree can never loop."""
    if parent_id is None:
        return
    parents = await _parents(db)
    if parent_id not in parents:
        raise Invalid("The parent must be another key account")
    seen, node = set(), parent_id
    while node is not None:
        if node == account_id or node in seen:
            raise Invalid("That would make the group tree go round in a circle")
        seen.add(node)
        node = parents.get(node)


async def subtree(db: AsyncSession, account_id: uuid.UUID) -> list[uuid.UUID]:
    """The account and every account below it."""
    parents = await _parents(db)
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for a, p in parents.items():
        children.setdefault(p, []).append(a)
    out, todo = [], [account_id]
    while todo:
        node = todo.pop()
        if node in out:
            continue
        out.append(node)
        todo += children.get(node, [])
    return out


async def top_of(db: AsyncSession, account_id: uuid.UUID) -> uuid.UUID:
    parents = await _parents(db)
    node, seen = account_id, set()
    while parents.get(node) and node not in seen:
        seen.add(node)
        node = parents[node]
    return node


# ---------- roll-ups ----------
async def lead_ids(db: AsyncSession, account_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """The organisations of these accounts and everyone who works there."""
    orgs = list(
        (
            await db.scalars(select(KeyAccount.org_lead_id).where(KeyAccount.id.in_(account_ids)))
        ).all()
    )
    people = (await db.scalars(select(Lead.id).where(Lead.organisation_id.in_(orgs)))).all()
    return orgs + list(people)


def _amounts(rows) -> list[dict]:
    return [{"currency": c, "minor": int(v or 0)} for c, v in sorted(rows) if v]


async def rollup(db: AsyncSession, account_ids: list[uuid.UUID]) -> dict:
    """Won this year, open pipeline, collected this year and overdue now — per currency."""
    ids = await lead_ids(db, account_ids)
    tz = ZoneInfo(await db.scalar(select(TenantSettings.timezone)) or "UTC")
    today = datetime.now(tz).date()
    year = datetime.combine(date(today.year, 1, 1), datetime.min.time(), tz).astimezone(UTC)
    won = (
        await db.execute(
            select(Deal.currency, func.sum(Deal.amount_minor))
            .where(Deal.lead_id.in_(ids), Deal.status == "won", Deal.closed_at >= year)
            .group_by(Deal.currency)
        )
    ).all()
    pipeline = (
        await db.execute(
            select(Deal.currency, func.sum(Deal.amount_minor))
            .where(Deal.lead_id.in_(ids), Deal.status == "open")
            .group_by(Deal.currency)
        )
    ).all()
    open_count = await db.scalar(
        select(func.count()).where(Deal.lead_id.in_(ids), Deal.status == "open")
    )
    collected = (
        await db.execute(
            select(Payment.currency, func.sum(Payment.amount_minor))
            .where(
                Payment.lead_id.in_(ids),
                Payment.status == "ok",
                Payment.paid_on >= date(today.year, 1, 1),
            )
            .group_by(Payment.currency)
        )
    ).all()
    overdue = (
        await db.execute(
            select(Invoice.currency, func.sum(Installment.amount_minor - Installment.paid_minor))
            .join(Installment, Installment.invoice_id == Invoice.id)
            .where(
                Invoice.lead_id.in_(ids),
                Invoice.status.in_(("issued", "partly_paid")),
                Installment.due_date < today,
            )
            .group_by(Invoice.currency)
        )
    ).all()
    lost_lately = await db.scalar(
        select(func.count()).where(
            Deal.lead_id.in_(ids),
            Deal.status == "lost",
            Deal.closed_at >= datetime.now(UTC) - timedelta(days=90),
        )
    )
    last_touch = await db.scalar(select(func.max(Lead.last_activity_at)).where(Lead.id.in_(ids)))
    return {
        "won_this_year": _amounts(won),
        "pipeline": _amounts(pipeline),
        "open_deals": int(open_count or 0),
        "collected_this_year": _amounts(collected),
        "overdue": _amounts(overdue),
        "lost_last_90_days": int(lost_lately or 0),
        "last_touch": last_touch,
    }


def hints(r: dict) -> list[str]:
    """Data that suggests the account needs attention (the owner still sets the health)."""
    out = []
    lt = r["last_touch"]
    if lt is None or lt < datetime.now(UTC) - timedelta(days=QUIET_DAYS):
        out.append(f"No contact in the last {QUIET_DAYS} days")
    if r["overdue"]:
        out.append("Money is overdue")
    if r["lost_last_90_days"]:
        out.append(f"{r['lost_last_90_days']} deal(s) lost in the last 90 days")
    return out


# ---------- the opportunity grid ----------
async def grid(db: AsyncSession, account: KeyAccount, products: list) -> dict:
    """Departments × products. A cell shows what real deals say (won beats in progress beats
    lost); with no deal, what the rep set (a competitor holds it / not a fit); else empty."""
    units = list(
        (
            await db.scalars(
                select(AccountUnit)
                .where(AccountUnit.account_id == account.id)
                .order_by(AccountUnit.position)
            )
        ).all()
    )
    ids = await lead_ids(db, [account.id])
    deals = (
        await db.execute(
            select(Deal, DealProduct.product_id)
            .join(DealProduct, DealProduct.deal_id == Deal.id)
            .where(
                Deal.lead_id.in_(ids),
                Deal.account_unit_id.in_([u.id for u in units]),
                DealProduct.product_id.isnot(None),
            )
        )
    ).all()
    manual = {
        (c.unit_id, c.product_id): c
        for c in (
            await db.scalars(select(AccountCell).where(AccountCell.account_id == account.id))
        ).all()
    }
    by_cell: dict[tuple, list[Deal]] = {}
    for deal, product_id in deals:
        by_cell.setdefault((deal.account_unit_id, product_id), []).append(deal)
    rank = {"won": 3, "open": 2, "lost": 1}
    cells = []
    for u in units:
        for p in products:
            ds = by_cell.get((u.id, p.id), [])
            m = manual.get((u.id, p.id))
            if ds:
                state = max(ds, key=lambda d: rank[d.status]).status
            elif m:
                state = m.status
            else:
                state = "empty"
            cells.append(
                {
                    "unit_id": u.id,
                    "product_id": p.id,
                    "state": state,
                    "deals": [
                        {
                            "id": d.id,
                            "name": d.name,
                            "status": d.status,
                            "amount_minor": d.amount_minor,
                            "currency": d.currency,
                        }
                        for d in ds
                    ],
                    "competitor_id": m.competitor_id if m else None,
                    "note": m.note if m else None,
                }
            )
    return {"units": units, "cells": cells}


async def unit_of(db: AsyncSession, account: KeyAccount, unit_id: uuid.UUID) -> AccountUnit:
    unit = await db.scalar(
        select(AccountUnit).where(AccountUnit.id == unit_id, AccountUnit.account_id == account.id)
    )
    if unit is None:
        raise NotFound("Department not found")
    return unit


async def check_contact(db: AsyncSession, org: Lead, lead_id: uuid.UUID) -> Lead:
    """Only people who work at this organisation go on its people map."""
    person = await db.get(Lead, lead_id)
    if person is None or person.kind != "person" or person.organisation_id != org.id:
        raise Invalid(f"Choose a contact who works at {org.display_name}")
    return person


async def people(db: AsyncSession, account: KeyAccount, org: Lead) -> list[tuple]:
    rows = (
        await db.execute(
            select(Lead, AccountContact)
            .outerjoin(
                AccountContact,
                (AccountContact.lead_id == Lead.id) & (AccountContact.account_id == account.id),
            )
            .where(Lead.organisation_id == org.id, Lead.kind == "person")
            .order_by(Lead.display_name)
        )
    ).all()
    return [(ld, c) for ld, c in rows]


async def ensure_not_key(db: AsyncSession, org_id: uuid.UUID) -> None:
    if await db.scalar(select(KeyAccount.id).where(KeyAccount.org_lead_id == org_id)):
        raise Conflict("This organisation is already a key account")

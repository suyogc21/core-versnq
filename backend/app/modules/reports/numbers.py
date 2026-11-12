"""Dashboard numbers (step 7, Decision log #35). Everything is worked out live from the data
steps 1–6 already keep; nothing is typed in twice.

Who is counted: `owners` is the set of people whose records count (a rep: themselves; a
manager: their team; the owner: None = everyone). Money is always per currency, never added
across currencies (rule 7). Periods follow the company's time zone; `end` is exclusive.

Definitions (shown to people on hover, so every screen means the same thing):
- New leads: leads that reached the owner in the period (assigned, or created if never assigned).
- Contacted: a lead someone has reached (a call, message or meeting was logged).
- Won: deals closed as won in the period; booked revenue = their value.
- Converted: became a customer in the period.
- Collected: payments received in the period (reversed ones excluded).
- Overdue: installments past their due date and not fully paid, right now.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, literal, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import (
    Activity,
    Customer,
    Deal,
    Lead,
    LeadSource,
    LostReason,
    PipelineStage,
    Task,
)
from app.modules.money.calc import AGING, aging_bucket
from app.modules.money.models import BillingEntity, Installment, Invoice, Payment
from app.modules.users.models import User

PERIODS = ("today", "week", "month", "last_month", "quarter", "year", "custom")
LIVE = ("issued", "partly_paid")
BILLED = ("issued", "partly_paid", "paid")


# ---------- periods ----------
@dataclass(frozen=True)
class Period:
    kind: str
    start_day: date
    end_day: date  # exclusive
    prev_start_day: date
    tz: str

    def _dt(self, d: date) -> datetime:
        return datetime.combine(d, time.min, ZoneInfo(self.tz)).astimezone(UTC)

    @property
    def start(self) -> datetime:
        return self._dt(self.start_day)

    @property
    def end(self) -> datetime:
        return self._dt(self.end_day)

    @property
    def prev(self) -> "Period":
        return Period(self.kind, self.prev_start_day, self.start_day, self.prev_start_day, self.tz)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def period(
    kind: str, tz: str, today: date, frm: date | None = None, to: date | None = None
) -> Period:
    """The period and the one just before it, of the same kind and length."""
    if kind == "today":
        return Period(kind, today, today + timedelta(days=1), today - timedelta(days=1), tz)
    if kind == "week":  # weeks start on Monday (Decision log #35 R3)
        start = today - timedelta(days=today.weekday())
        return Period(kind, start, start + timedelta(days=7), start - timedelta(days=7), tz)
    if kind == "month":
        start = _month_start(today)
        return Period(kind, start, _add_months(start, 1), _add_months(start, -1), tz)
    if kind == "last_month":
        start = _add_months(_month_start(today), -1)
        return Period(kind, start, _add_months(start, 1), _add_months(start, -1), tz)
    if kind == "quarter":
        start = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
        return Period(kind, start, _add_months(start, 3), _add_months(start, -3), tz)
    if kind == "year":
        start = date(today.year, 1, 1)
        return Period(kind, start, date(today.year + 1, 1, 1), date(today.year - 1, 1, 1), tz)
    frm = frm or today
    to = to or today
    if to < frm:
        frm, to = to, frm
    end = to + timedelta(days=1)
    days = (end - frm).days
    return Period("custom", frm, end, frm - timedelta(days=days), tz)


# ---------- helpers ----------
def _owned(col, owners: set[uuid.UUID] | None):
    return true() if owners is None else col.in_(owners or {uuid.UUID(int=0)})


def _amounts(rows) -> list[dict]:
    return [{"currency": c, "minor": int(v or 0)} for c, v in sorted(rows) if v]


async def _count(db: AsyncSession, stmt) -> int:
    return int(await db.scalar(stmt) or 0)


# ---------- the headline numbers (My numbers, Team, Business) ----------
async def headline(db: AsyncSession, owners: set | None, p: Period) -> dict:
    s, e = p.start, p.end
    reached = func.coalesce(Lead.assigned_at, Lead.created_at)
    new_leads = await _count(
        db,
        select(func.count()).where(reached >= s, reached < e, _owned(Lead.owner_user_id, owners)),
    )
    calls = await _count(
        db,
        select(func.count()).where(
            Activity.type_key == "call",
            Activity.actor_type == "user",
            Activity.occurred_at >= s,
            Activity.occurred_at < e,
            _owned(Activity.actor_id, owners),
        ),
    )
    follow_ups = await _count(
        db,
        select(func.count()).where(
            Task.status == "done",
            Task.completed_at >= s,
            Task.completed_at < e,
            _owned(Task.owner_user_id, owners),
        ),
    )
    won = (
        await db.execute(
            select(Deal.currency, func.count(), func.sum(Deal.amount_minor))
            .where(
                Deal.status == "won",
                Deal.closed_at >= s,
                Deal.closed_at < e,
                _owned(Deal.owner_user_id, owners),
            )
            .group_by(Deal.currency)
        )
    ).all()
    customers = await _count(
        db,
        select(func.count())
        .select_from(Customer)
        .join(Lead, Lead.id == Customer.lead_id)
        .where(Customer.since >= s, Customer.since < e, _owned(Lead.owner_user_id, owners)),
    )
    collected = (
        await db.execute(
            select(Payment.currency, func.sum(Payment.amount_minor))
            .join(Lead, Lead.id == Payment.lead_id)
            .where(
                Payment.status == "ok",
                Payment.paid_on >= p.start_day,
                Payment.paid_on < p.end_day,
                _owned(Lead.owner_user_id, owners),
            )
            .group_by(Payment.currency)
        )
    ).all()
    return {
        "new_leads": new_leads,
        "calls": calls,
        "follow_ups_done": follow_ups,
        "deals_won": sum(n for _, n, _ in won),
        "booked": _amounts((c, v) for c, _, v in won),
        "converted": customers,
        "collected": _amounts(collected),
    }


async def right_now(db: AsyncSession, owners: set | None, today: date, tz: str) -> dict:
    """Numbers that are about now, not a period: what is due, open and overdue."""
    now = datetime.now(UTC)
    day_end = datetime.combine(today + timedelta(days=1), time.min, ZoneInfo(tz)).astimezone(UTC)
    open_tasks = select(func.count()).where(
        Task.status == "open", _owned(Task.owner_user_id, owners)
    )
    overdue_tasks = await _count(db, open_tasks.where(Task.due_at < now))
    due_today = await _count(db, open_tasks.where(Task.due_at >= now, Task.due_at < day_end))
    pipeline = (
        await db.execute(
            select(
                Deal.currency,
                func.count(),
                func.sum(Deal.amount_minor),
                func.sum(Deal.amount_minor * PipelineStage.probability),
            )
            .join(PipelineStage, PipelineStage.id == Deal.stage_id)
            .where(Deal.status == "open", _owned(Deal.owner_user_id, owners))
            .group_by(Deal.currency)
        )
    ).all()
    overdue_money = (
        await db.execute(
            select(Invoice.currency, func.sum(Installment.amount_minor - Installment.paid_minor))
            .join(Installment, Installment.invoice_id == Invoice.id)
            .join(Lead, Lead.id == Invoice.lead_id)
            .where(
                Invoice.status.in_(LIVE),
                Installment.due_date < today,
                _owned(Lead.owner_user_id, owners),
            )
            .group_by(Invoice.currency)
        )
    ).all()
    leaking = await _count(
        db,
        select(func.count()).where(
            Lead.is_open.is_(True),
            Lead.leak_alerted_at.isnot(None),
            _owned(Lead.owner_user_id, owners),
        ),
    )
    return {
        "tasks_overdue": overdue_tasks,
        "tasks_due_today": due_today,
        "open_deals": sum(n for _, n, _, _ in pipeline),
        "pipeline": _amounts((c, v) for c, _, v, _ in pipeline),
        # weighted = value × win %, rounded half up per currency (rule 7)
        "weighted": _amounts((c, (int(w or 0) * 2 + 100) // 200) for c, _, _, w in pipeline),
        "overdue_money": _amounts(overdue_money),
        "leaking": leaking,
    }


# ---------- Team ----------
async def funnel(db: AsyncSession, owners: set | None, p: Period) -> list[dict]:
    """Leads that came in this period, and how far they have got since."""
    cohort = and_(
        Lead.created_at >= p.start, Lead.created_at < p.end, _owned(Lead.owner_user_id, owners)
    )
    has_deal = select(Deal.id).where(Deal.lead_id == Lead.id).exists()
    won = select(Deal.id).where(Deal.lead_id == Lead.id, Deal.status == "won").exists()
    customer = select(Customer.id).where(Customer.lead_id == Lead.id).exists()
    contacted = or_(Lead.first_response_at.isnot(None), Lead.last_contacted_at.isnot(None))
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(contacted),
                func.count().filter(has_deal),
                func.count().filter(won),
                func.count().filter(customer),
            ).where(cohort)
        )
    ).one()
    names = ("New leads", "Contacted", "Got a deal", "Won", "Converted")
    return [
        {"key": k, "label": n, "count": int(v)}
        for k, n, v in zip(
            ("leads", "contacted", "deal", "won", "converted"), names, row, strict=True
        )
    ]


async def sources(db: AsyncSession, owners: set | None, p: Period) -> list[dict]:
    customer = select(Customer.id).where(Customer.lead_id == Lead.id).exists()
    contacted = or_(Lead.first_response_at.isnot(None), Lead.last_contacted_at.isnot(None))
    rows = (
        await db.execute(
            select(
                LeadSource.id,
                LeadSource.name,
                func.count(),
                func.count().filter(contacted),
                func.count().filter(customer),
            )
            .join(LeadSource, LeadSource.id == Lead.source_id)
            .where(
                Lead.created_at >= p.start,
                Lead.created_at < p.end,
                _owned(Lead.owner_user_id, owners),
            )
            .group_by(LeadSource.id, LeadSource.name)
            .order_by(func.count().desc())
        )
    ).all()
    return [
        {
            "source_id": str(sid),
            "name": name,
            "leads": int(n),
            "contacted": int(c),
            "converted": int(cv),
            "conversion_bp": (int(cv) * 10_000 + int(n) // 2) // int(n) if n else 0,
        }
        for sid, name, n, c, cv in rows
    ]


async def leaderboard(db: AsyncSession, owners: set | None, p: Period) -> list[dict]:
    s, e = p.start, p.end
    users = select(User.id, User.name).where(User.status == "active", _owned(User.id, owners))
    people = {uid: name for uid, name in (await db.execute(users)).all()}

    async def per(stmt) -> dict:
        return {k: int(v or 0) for k, v in (await db.execute(stmt)).all()}

    reached = func.coalesce(Lead.assigned_at, Lead.created_at)
    leads = await per(
        select(Lead.owner_user_id, func.count())
        .where(reached >= s, reached < e, _owned(Lead.owner_user_id, owners))
        .group_by(Lead.owner_user_id)
    )
    calls = await per(
        select(Activity.actor_id, func.count())
        .where(
            Activity.type_key == "call",
            Activity.actor_type == "user",
            Activity.occurred_at >= s,
            Activity.occurred_at < e,
            _owned(Activity.actor_id, owners),
        )
        .group_by(Activity.actor_id)
    )
    tasks = await per(
        select(Task.owner_user_id, func.count())
        .where(
            Task.status == "done",
            Task.completed_at >= s,
            Task.completed_at < e,
            _owned(Task.owner_user_id, owners),
        )
        .group_by(Task.owner_user_id)
    )
    won_rows = (
        await db.execute(
            select(Deal.owner_user_id, Deal.currency, func.count(), func.sum(Deal.amount_minor))
            .where(
                Deal.status == "won",
                Deal.closed_at >= s,
                Deal.closed_at < e,
                _owned(Deal.owner_user_id, owners),
            )
            .group_by(Deal.owner_user_id, Deal.currency)
        )
    ).all()
    paid_rows = (
        await db.execute(
            select(Lead.owner_user_id, Payment.currency, func.sum(Payment.amount_minor))
            .join(Lead, Lead.id == Payment.lead_id)
            .where(
                Payment.status == "ok",
                Payment.paid_on >= p.start_day,
                Payment.paid_on < p.end_day,
                _owned(Lead.owner_user_id, owners),
            )
            .group_by(Lead.owner_user_id, Payment.currency)
        )
    ).all()
    sla = await per(
        select(Lead.owner_user_id, func.count())
        .select_from(Activity)
        .join(Lead, Lead.id == Activity.lead_id)
        .where(
            Activity.type_key == "sla_missed",
            Activity.occurred_at >= s,
            Activity.occurred_at < e,
            _owned(Lead.owner_user_id, owners),
        )
        .group_by(Lead.owner_user_id)
    )
    out = []
    for uid, name in people.items():
        won = [(c, n, v) for o, c, n, v in won_rows if o == uid]
        paid = [(c, v) for o, c, v in paid_rows if o == uid]
        row = {
            "user_id": str(uid),
            "name": name,
            "new_leads": leads.get(uid, 0),
            "calls": calls.get(uid, 0),
            "follow_ups_done": tasks.get(uid, 0),
            "deals_won": sum(n for _, n, _ in won),
            "booked": _amounts((c, v) for c, _, v in won),
            "collected": _amounts(paid),
            "sla_missed": sla.get(uid, 0),
        }
        if (
            any(
                row[k] for k in ("new_leads", "calls", "follow_ups_done", "deals_won", "sla_missed")
            )
            or row["collected"]
        ):
            out.append(row)
    out.sort(key=lambda r: (-r["deals_won"], -r["calls"], -r["new_leads"], r["name"]))
    return out


async def sla_breaches(db: AsyncSession, owners: set | None, p: Period) -> int:
    return await _count(
        db,
        select(func.count())
        .select_from(Activity)
        .join(Lead, Lead.id == Activity.lead_id)
        .where(
            Activity.type_key == "sla_missed",
            Activity.occurred_at >= p.start,
            Activity.occurred_at < p.end,
            _owned(Lead.owner_user_id, owners),
        ),
    )


async def lost_reasons(db: AsyncSession, owners: set | None, p: Period) -> list[dict]:
    rows = (
        await db.execute(
            select(func.coalesce(LostReason.name, literal("No reason")), func.count())
            .select_from(Deal)
            .outerjoin(LostReason, LostReason.id == Deal.lost_reason_id)
            .where(
                Deal.status == "lost",
                Deal.closed_at >= p.start,
                Deal.closed_at < p.end,
                _owned(Deal.owner_user_id, owners),
            )
            .group_by(LostReason.name)
            .order_by(func.count().desc())
        )
    ).all()
    return [{"name": n, "count": int(c)} for n, c in rows]


# ---------- Business ----------
async def trend(
    db: AsyncSession, owners: set | None, today: date, tz: str, months: int = 6
) -> list[dict]:
    """Same definitions as `headline`, one grouped query per number for all months at once."""
    first = _add_months(_month_start(today), -(months - 1))
    whole = Period("month", first, _add_months(first, months), first, tz)
    s, e = whole.start, whole.end
    keys = [_add_months(first, i).isoformat()[:7] for i in range(months)]

    def month(col):  # 'YYYY-MM' in the company's time zone
        return func.to_char(func.timezone(tz, col), "YYYY-MM")

    reached = func.coalesce(Lead.assigned_at, Lead.created_at)
    m = month(reached)
    new_leads = dict(
        (
            await db.execute(
                select(m, func.count())
                .where(reached >= s, reached < e, _owned(Lead.owner_user_id, owners))
                .group_by(m)
            )
        ).all()
    )
    m = month(Customer.since)
    converted = dict(
        (
            await db.execute(
                select(m, func.count())
                .select_from(Customer)
                .join(Lead, Lead.id == Customer.lead_id)
                .where(Customer.since >= s, Customer.since < e, _owned(Lead.owner_user_id, owners))
                .group_by(m)
            )
        ).all()
    )
    m = month(Deal.closed_at)
    won = (
        await db.execute(
            select(m, Deal.currency, func.sum(Deal.amount_minor))
            .where(
                Deal.status == "won",
                Deal.closed_at >= s,
                Deal.closed_at < e,
                _owned(Deal.owner_user_id, owners),
            )
            .group_by(m, Deal.currency)
        )
    ).all()
    m = func.to_char(Payment.paid_on, "YYYY-MM")
    paid = (
        await db.execute(
            select(m, Payment.currency, func.sum(Payment.amount_minor))
            .join(Lead, Lead.id == Payment.lead_id)
            .where(
                Payment.status == "ok",
                Payment.paid_on >= whole.start_day,
                Payment.paid_on < whole.end_day,
                _owned(Lead.owner_user_id, owners),
            )
            .group_by(m, Payment.currency)
        )
    ).all()
    return [
        {
            "month": k,
            "new_leads": int(new_leads.get(k, 0)),
            "converted": int(converted.get(k, 0)),
            "booked": _amounts((c, v) for mk, c, v in won if mk == k),
            "collected": _amounts((c, v) for mk, c, v in paid if mk == k),
        }
        for k in keys
    ]


# ---------- Money ----------
async def money(db: AsyncSession, visible, p: Period, today: date) -> dict:
    """`visible` is the SQL condition (on Lead) for whose money this person may see."""
    invoiced = (
        await db.execute(
            select(Invoice.currency, func.count(), func.sum(Invoice.total_minor))
            .join(Lead, Lead.id == Invoice.lead_id)
            .where(
                visible,
                Invoice.status.in_(BILLED),
                Invoice.issue_date >= p.start_day,
                Invoice.issue_date < p.end_day,
            )
            .group_by(Invoice.currency)
        )
    ).all()
    pay = (
        select(Payment.currency, func.sum(Payment.amount_minor))
        .join(Lead, Lead.id == Payment.lead_id)
        .where(
            visible,
            Payment.status == "ok",
            Payment.paid_on >= p.start_day,
            Payment.paid_on < p.end_day,
        )
    )
    collected = (await db.execute(pay.group_by(Payment.currency))).all()
    by_method = (
        await db.execute(
            select(Payment.method, Payment.currency, func.sum(Payment.amount_minor))
            .join(Lead, Lead.id == Payment.lead_id)
            .where(
                visible,
                Payment.status == "ok",
                Payment.paid_on >= p.start_day,
                Payment.paid_on < p.end_day,
            )
            .group_by(Payment.method, Payment.currency)
        )
    ).all()
    entity_names = dict((await db.execute(select(BillingEntity.id, BillingEntity.name))).all())
    by_entity = (
        await db.execute(
            select(Payment.entity_id, Payment.currency, func.sum(Payment.amount_minor))
            .join(Lead, Lead.id == Payment.lead_id)
            .where(
                visible,
                Payment.status == "ok",
                Payment.paid_on >= p.start_day,
                Payment.paid_on < p.end_day,
            )
            .group_by(Payment.entity_id, Payment.currency)
        )
    ).all()
    open_rows = (
        await db.execute(
            select(
                Invoice.entity_id,
                Invoice.currency,
                Installment.due_date,
                Installment.amount_minor - Installment.paid_minor,
                Invoice.customer_id,
            )
            .join(Installment, Installment.invoice_id == Invoice.id)
            .join(Lead, Lead.id == Invoice.lead_id)
            .where(
                visible, Invoice.status.in_(LIVE), Installment.paid_minor < Installment.amount_minor
            )
        )
    ).all()
    due: dict[str, int] = {}
    overdue: dict[str, int] = {}
    soon: dict[str, int] = {}
    soon_count = 0
    aging: dict[tuple, dict] = {}
    debtors: dict[tuple, int] = {}
    for entity_id, cur, due_date, left, customer_id in open_rows:
        left = int(left)
        due[cur] = due.get(cur, 0) + left
        if due_date < today:
            overdue[cur] = overdue.get(cur, 0) + left
            row = aging.setdefault(
                (entity_id, cur),
                {
                    "entity_id": str(entity_id),
                    "entity_name": entity_names.get(entity_id, ""),
                    "currency": cur,
                    "buckets": dict.fromkeys(AGING, 0),
                    "total_minor": 0,
                },
            )
            row["buckets"][aging_bucket((today - due_date).days)] += left
            row["total_minor"] += left
            debtors[(customer_id, cur)] = debtors.get((customer_id, cur), 0) + left
        elif due_date < today + timedelta(days=30):
            soon[cur] = soon.get(cur, 0) + left
            soon_count += 1
    top = sorted(debtors.items(), key=lambda kv: -kv[1])[:10]
    names = {}
    if top:
        names = {
            c.id: (c.number, ld.display_name, c.lead_id)
            for c, ld in (
                await db.execute(
                    select(Customer, Lead)
                    .join(Lead, Lead.id == Customer.lead_id)
                    .where(Customer.id.in_([cid for (cid, _), _ in top]))
                )
            ).all()
        }
    return {
        "invoiced": _amounts((c, v) for c, _, v in invoiced),
        "invoices_issued": sum(int(n) for _, n, _ in invoiced),
        "collected": _amounts(collected),
        "due": _amounts(due.items()),
        "overdue": _amounts(overdue.items()),
        "due_next_30_days": _amounts(soon.items()),
        "installments_next_30_days": soon_count,
        "aging": sorted(aging.values(), key=lambda r: (r["entity_name"], r["currency"])),
        "by_method": [
            {"method": m, "currency": c, "minor": int(v)} for m, c, v in sorted(by_method) if v
        ],
        "by_entity": [
            {
                "entity_id": str(e),
                "entity_name": entity_names.get(e, ""),
                "currency": c,
                "minor": int(v),
            }
            for e, c, v in sorted(by_entity, key=lambda r: (entity_names.get(r[0], ""), r[1]))
            if v
        ],
        "top_overdue": [
            {
                "customer_id": str(cid),
                "number": names.get(cid, ("", "", None))[0],
                "name": names.get(cid, ("", "", None))[1],
                "lead_id": str(names.get(cid, ("", "", None))[2] or ""),
                "currency": cur,
                "minor": amount,
            }
            for (cid, cur), amount in top
        ],
    }

"""Dashboards and CSV export (step 7, Decision log #35).

Dashboards: My numbers (anyone who works leads), Team, Business and Money (permissions the admin
gives per role). Every number obeys the same visibility as the lists.

Export: one permission per list, default Owner and Admin only. An export holds exactly the rows
the list shows (same filters, by calling the list itself), is audited, and alerts the Owners and
Admins. Registered before the CRM routers so `/leads/export` is not read as a lead id.
"""

import csv
import io
import uuid
from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.core.errors import Forbidden, Invalid, NotFound
from app.core.modules import is_enabled
from app.modules.auth.deps import ActiveUser, CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.lead_query import LeadFilter
from app.modules.crm.lead_query import SortKey as LeadSort
from app.modules.crm.models import (
    CustomFieldDefinition,
    LeadSource,
    LeadStage,
    Pipeline,
)
from app.modules.crm.notify import notify
from app.modules.money import service as S
from app.modules.reports import numbers as N
from app.modules.roles.models import Role
from app.modules.settings.models import TenantSettings
from app.modules.teams.service import visible_user_ids
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["reports"], dependencies=CRM)
MAX_ROWS = 50_000
PAGE = 1000


# ---------- dashboards ----------
class Amount(BaseModel):
    currency: str
    minor: int


class Headline(BaseModel):
    new_leads: int
    calls: int
    follow_ups_done: int
    deals_won: int
    booked: list[Amount]
    converted: int
    collected: list[Amount]


class RightNow(BaseModel):
    tasks_overdue: int
    tasks_due_today: int
    open_deals: int
    pipeline: list[Amount]
    weighted: list[Amount]
    overdue_money: list[Amount]
    leaking: int


class PeriodOut(BaseModel):
    kind: str
    start: date
    end: date  # last day included
    previous_start: date
    previous_end: date


class MyDashboard(BaseModel):
    period: PeriodOut
    now: RightNow
    current: Headline
    previous: Headline


class FunnelStep(BaseModel):
    key: str
    label: str
    count: int


class SourceRow(BaseModel):
    source_id: str
    name: str
    leads: int
    contacted: int
    converted: int
    conversion_bp: int


class LeaderRow(BaseModel):
    user_id: str
    name: str
    new_leads: int
    calls: int
    follow_ups_done: int
    deals_won: int
    booked: list[Amount]
    collected: list[Amount]
    sla_missed: int


class Named(BaseModel):
    name: str
    count: int


class TeamDashboard(BaseModel):
    period: PeriodOut
    everyone: bool
    now: RightNow
    current: Headline
    previous: Headline
    funnel: list[FunnelStep]
    sources: list[SourceRow]
    leaderboard: list[LeaderRow]
    sla_breaches: int
    lost_reasons: list[Named]


class TrendMonth(BaseModel):
    month: str
    new_leads: int
    converted: int
    booked: list[Amount]
    collected: list[Amount]


class BusinessDashboard(BaseModel):
    period: PeriodOut
    now: RightNow
    current: Headline
    previous: Headline
    trend: list[TrendMonth]


class AgingOut(BaseModel):
    entity_id: str
    entity_name: str
    currency: str
    buckets: dict[str, int]
    total_minor: int


class MethodAmount(BaseModel):
    method: str
    currency: str
    minor: int


class EntityAmount(BaseModel):
    entity_id: str
    entity_name: str
    currency: str
    minor: int


class Debtor(BaseModel):
    customer_id: str
    number: str
    name: str
    lead_id: str
    currency: str
    minor: int


class MoneyNumbers(BaseModel):
    invoiced: list[Amount]
    invoices_issued: int
    collected: list[Amount]
    due: list[Amount]
    overdue: list[Amount]
    due_next_30_days: list[Amount]
    installments_next_30_days: int
    aging: list[AgingOut]
    by_method: list[MethodAmount]
    by_entity: list[EntityAmount]
    top_overdue: list[Debtor]


class MoneyDashboard(BaseModel):
    period: PeriodOut
    current: MoneyNumbers
    previous_invoiced: list[Amount]
    previous_collected: list[Amount]


PeriodKind = Literal["today", "week", "month", "last_month", "quarter", "year", "custom"]


async def _period(db, kind: str, frm: date | None, to: date | None) -> N.Period:
    tz = await db.scalar(select(TenantSettings.timezone)) or "UTC"
    today = datetime.now(ZoneInfo(tz)).date()
    if kind == "custom" and not (frm and to):
        raise Invalid("Choose both dates")
    return N.period(kind, tz, today, frm, to)


def _period_out(p: N.Period) -> PeriodOut:
    from datetime import timedelta

    return PeriodOut(
        kind=p.kind,
        start=p.start_day,
        end=p.end_day - timedelta(days=1),
        previous_start=p.prev_start_day,
        previous_end=p.start_day - timedelta(days=1),
    )


def _need(actor: CurrentUser, code: str) -> None:
    if not L.can(actor, code):
        raise Forbidden("permission_denied")


async def _scope_owners(db, actor: CurrentUser) -> set | None:
    """Whose records count on Team / Business: the role's own visibility (all / team / own)."""
    return await visible_user_ids(db, actor.user.id, actor.role.scope)


def _today(p: N.Period) -> date:
    return datetime.now(ZoneInfo(p.tz)).date()


@router.get("/dashboards/me", response_model=MyDashboard)
async def my_dashboard(
    db: CrmDb,
    actor: ActiveUser,
    period: PeriodKind = "month",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
):
    _need(actor, "leads.edit")
    p = await _period(db, period, from_, to)
    me = {actor.user.id}
    return MyDashboard(
        period=_period_out(p),
        now=RightNow(**await N.right_now(db, me, _today(p), p.tz)),
        current=Headline(**await N.headline(db, me, p)),
        previous=Headline(**await N.headline(db, me, p.prev)),
    )


@router.get("/dashboards/team", response_model=TeamDashboard)
async def team_dashboard(
    db: CrmDb,
    actor: ActiveUser,
    period: PeriodKind = "month",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
):
    _need(actor, "dashboards.team")
    p = await _period(db, period, from_, to)
    owners = await _scope_owners(db, actor)
    return TeamDashboard(
        period=_period_out(p),
        everyone=owners is None,
        now=RightNow(**await N.right_now(db, owners, _today(p), p.tz)),
        current=Headline(**await N.headline(db, owners, p)),
        previous=Headline(**await N.headline(db, owners, p.prev)),
        funnel=[FunnelStep(**x) for x in await N.funnel(db, owners, p)],
        sources=[SourceRow(**x) for x in await N.sources(db, owners, p)],
        leaderboard=[LeaderRow(**x) for x in await N.leaderboard(db, owners, p)],
        sla_breaches=await N.sla_breaches(db, owners, p),
        lost_reasons=[Named(**x) for x in await N.lost_reasons(db, owners, p)],
    )


@router.get("/dashboards/business", response_model=BusinessDashboard)
async def business_dashboard(
    db: CrmDb,
    actor: ActiveUser,
    period: PeriodKind = "month",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
):
    _need(actor, "dashboards.business")
    p = await _period(db, period, from_, to)
    owners = await _scope_owners(db, actor)
    return BusinessDashboard(
        period=_period_out(p),
        now=RightNow(**await N.right_now(db, owners, _today(p), p.tz)),
        current=Headline(**await N.headline(db, owners, p)),
        previous=Headline(**await N.headline(db, owners, p.prev)),
        trend=[TrendMonth(**x) for x in await N.trend(db, owners, _today(p), p.tz)],
    )


@router.get("/dashboards/money", response_model=MoneyDashboard)
async def money_dashboard(
    db: CrmDb,
    actor: ActiveUser,
    period: PeriodKind = "month",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
):
    _need(actor, "dashboards.money")
    if not await is_enabled(db, actor.user.tenant_id, "money"):
        raise NotFound("Not found")
    p = await _period(db, period, from_, to)
    visible = await S.visible(db, actor)
    current = await N.money(db, visible, p, _today(p))
    before = await N.money(db, visible, p.prev, _today(p))
    return MoneyDashboard(
        period=_period_out(p),
        current=MoneyNumbers(**current),
        previous_invoiced=[Amount(**a) for a in before["invoiced"]],
        previous_collected=[Amount(**a) for a in before["collected"]],
    )


# ---------- CSV export ----------
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(v) -> str:
    """Safe to open in Excel: a value that starts like a formula is written as plain text."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v)
    s = str(v)
    return f"'{s}" if s.startswith(_FORMULA) else s


def _csv(name: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    stamp = datetime.now().strftime("%Y-%m-%d")
    return Response(
        "﻿" + buf.getvalue(),  # the mark makes Excel read accents and ₹ correctly
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}-{stamp}.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _tz(db) -> ZoneInfo:
    return ZoneInfo(await db.scalar(select(TenantSettings.timezone)) or "UTC")


def _local(dt: datetime | None, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M") if dt else ""


def _major(minor: int | None, currency: str) -> str:
    from app.core.money import plain

    return plain(minor or 0, currency) if currency else ""


async def _fields(db, entity: str, actor) -> list[CustomFieldDefinition]:
    """Custom columns for an export, without the ones this person may not see (step 8)."""
    from app.modules.crm import access as A

    rules = await A.rules(db, actor, entity)
    rows = await db.scalars(
        select(CustomFieldDefinition)
        .where(CustomFieldDefinition.entity == entity)
        .order_by(CustomFieldDefinition.position)
    )
    return [d for d in rows.all() if not rules.hidden(f"cf.{d.key}")]


async def _done(db, actor: CurrentUser, what: str, count: int) -> None:
    """Every export is in the audit log, and Owners / Admins are told (Decision log #35)."""
    await audit(db, actor, "data.exported", what, None, after={"rows": count})
    admins = (
        await db.scalars(
            select(User.id)
            .join(Role, Role.id == User.role_id)
            .where(
                User.status == "active", Role.key.in_(("owner", "admin")), User.id != actor.user.id
            )
        )
    ).all()
    await notify(
        db,
        actor.user.tenant_id,
        list(admins),
        "data_exported",
        f"{actor.user.name} exported {count} {what}",
    )


def _too_many(total: int) -> None:
    if total > MAX_ROWS:
        raise Invalid(
            f"That is {total:,} rows; exports are limited to {MAX_ROWS:,}. Narrow the filters."
        )


@router.get(
    "/leads/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}}
)
async def export_leads(
    db: CrmDb,
    actor: ActiveUser,
    f: Annotated[LeadFilter, Query()],
    sort: LeadSort = "created",
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "desc",
):
    _need(actor, "leads.export")
    from app.modules.crm.leads_router import list_leads

    first = await list_leads(
        db=db, actor=actor, f=f, sort=sort, direction=direction, limit=PAGE, offset=0
    )
    _too_many(first.total)
    items = list(first.items)
    while len(items) < first.total:
        page = await list_leads(
            db=db, actor=actor, f=f, sort=sort, direction=direction, limit=PAGE, offset=len(items)
        )
        if not page.items:
            break
        items += page.items
    tz = await _tz(db)
    stages = dict((await db.execute(select(LeadStage.id, LeadStage.name))).all())
    sources = dict((await db.execute(select(LeadSource.id, LeadSource.name))).all())
    fields = await _fields(db, "lead", actor)
    header = [
        "Name",
        "Email",
        "Phone",
        "Stage",
        "Open",
        "Source",
        "Owner",
        "Origin",
        "Score",
        "Band",
        "Tags",
        "Next follow-up",
        "Last contacted",
        "Last outcome",
        "City",
        "Country",
        "Campaign",
        "UTM source",
        "UTM medium",
        "UTM campaign",
        "Created",
        *[d.label for d in fields],
    ]
    rows = [
        [
            x.display_name,
            x.primary_email,
            x.primary_phone,
            stages.get(x.stage_id),
            x.is_open,
            sources.get(x.source_id),
            x.owner_name,
            x.origin,
            x.score,
            x.score_band,
            [t.name for t in x.tags],
            _local(x.next_follow_up_at, tz),
            _local(x.last_contacted_at, tz),
            x.last_disposition,
            x.city,
            x.country_code,
            x.campaign,
            x.utm_source,
            x.utm_medium,
            x.utm_campaign,
            _local(x.created_at, tz),
            *[x.custom_fields.get(d.key) for d in fields],
        ]
        for x in items
    ]
    await _done(db, actor, "leads", len(rows))
    return _csv("leads", header, rows)


@router.get(
    "/deals/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}}
)
async def export_deals(
    db: CrmDb,
    actor: ActiveUser,
    pipeline_id: uuid.UUID | None = None,
    stage_id: Annotated[list[uuid.UUID], Query()] = [],  # noqa: B006
    status_: Annotated[Literal["open", "won", "lost"] | None, Query(alias="status")] = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
    close_from: date | None = None,
    close_to: date | None = None,
    q: str | None = None,
    cf: Annotated[list[str], Query()] = [],  # noqa: B006
    tag: Annotated[list[uuid.UUID], Query()] = [],  # noqa: B006
):
    _need(actor, "deals.export")
    from app.modules.crm.deals_router import list_deals

    async def page(offset: int):
        return await list_deals(
            db=db,
            actor=actor,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            status_=status_,
            owner=owner,
            lead_id=None,
            close_from=close_from,
            close_to=close_to,
            q=q,
            cf=cf,
            tag=tag,
            sort="created",
            direction="desc",
            limit=PAGE,
            offset=offset,
        )

    first = await page(0)
    _too_many(first.total)
    items = list(first.items)
    while len(items) < first.total:
        more = await page(len(items))
        if not more.items:
            break
        items += more.items
    tz = await _tz(db)
    pipes = dict((await db.execute(select(Pipeline.id, Pipeline.name))).all())
    fields = await _fields(db, "deal", actor)
    header = [
        "Deal",
        "Contact",
        "Pipeline",
        "Stage",
        "Status",
        "Owner",
        "Amount",
        "Currency",
        "Expected close",
        "Closed",
        "Lost reason",
        "Note",
        "Tags",
        "Created",
        *[d.label for d in fields],
    ]
    rows = [
        [
            d.name,
            d.lead_name,
            pipes.get(d.pipeline_id),
            d.stage_name,
            d.status,
            d.owner_name,
            "" if d.amount_minor is None else _major(d.amount_minor, d.currency),  # hidden: blank
            d.currency,
            d.expected_close_on,
            _local(d.closed_at, tz),
            d.lost_reason,
            d.close_note,
            [t.name for t in d.tags],
            _local(d.created_at, tz),
            *[d.custom_fields.get(f.key) for f in fields],
        ]
        for d in items
    ]
    await _done(db, actor, "deals", len(rows))
    return _csv("deals", header, rows)


@router.get(
    "/customers/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}}
)
async def export_customers(
    db: CrmDb,
    actor: ActiveUser,
    q: str | None = None,
    status_: Annotated[Literal["active", "inactive"] | None, Query(alias="status")] = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
    documents: Literal["missing", "complete"] | None = None,
):
    _need(actor, "customers.export")
    from app.modules.crm.customers_router import list_customers

    async def page(n: int):
        return await list_customers(
            db=db,
            actor=actor,
            q=q,
            status_=status_,
            owner=owner,
            documents=documents,
            sort="-since",
            page=n,
            page_size=PAGE,
        )

    first = await page(1)
    _too_many(first.total)
    items = list(first.items)
    n = 1
    while len(items) < first.total:
        n += 1
        more = await page(n)
        if not more.items:
            break
        items += more.items
    tz = await _tz(db)
    fields = await _fields(db, "customer", actor)
    header = [
        "Number",
        "Name",
        "Email",
        "Phone",
        "Status",
        "Owner",
        "Since",
        "Documents done",
        "Documents required",
        *[d.label for d in fields],
    ]
    rows = [
        [
            c.number,
            c.name,
            c.email,
            c.phone,
            c.status,
            c.owner_name,
            _local(c.since, tz),
            c.docs_done,
            c.docs_required,
            *[c.custom_fields.get(f.key) for f in fields],
        ]
        for c in items
    ]
    await _done(db, actor, "customers", len(rows))
    return _csv("customers", header, rows)


async def _money_on(db, actor: CurrentUser) -> None:
    if not await is_enabled(db, actor.user.tenant_id, "money"):
        raise NotFound("Not found")


@router.get(
    "/invoices/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}}
)
async def export_invoices(
    db: CrmDb,
    actor: ActiveUser,
    q: str | None = None,
    status_: Annotated[
        list[Literal["draft", "issued", "partly_paid", "paid", "void"]], Query(alias="status")
    ] = [],  # noqa: B006
    entity_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
    overdue: bool = False,
):
    _need(actor, "invoices.export")
    await _money_on(db, actor)
    from app.modules.money.router import list_invoices

    async def page(n: int):
        return await list_invoices(
            db=db,
            actor=actor,
            q=q,
            status_=status_,
            entity_id=entity_id,
            customer_id=customer_id,
            owner=owner,
            overdue=overdue,
            sort="-created",
            page=n,
            page_size=PAGE,
        )

    first = await page(1)
    _too_many(first.total)
    items = list(first.items)
    n = 1
    while len(items) < first.total:
        n += 1
        more = await page(n)
        if not more.items:
            break
        items += more.items
    header = [
        "Number",
        "Status",
        "Customer",
        "Customer number",
        "Owner",
        "Currency",
        "Total",
        "Paid",
        "Due",
        "Overdue",
        "Issued",
        "Due date",
        "Next due",
    ]
    rows = [
        [
            i.number or "Draft",
            i.status,
            i.customer_name,
            i.customer_number,
            i.owner_name,
            i.currency,
            _major(i.total_minor, i.currency),
            _major(i.paid_minor, i.currency),
            _major(
                0 if i.status in ("void", "draft") else i.total_minor - i.paid_minor, i.currency
            ),
            _major(i.overdue_minor, i.currency),
            i.issue_date,
            i.due_date,
            i.next_due_date,
        ]
        for i in items
    ]
    await _done(db, actor, "invoices", len(rows))
    return _csv("invoices", header, rows)


@router.get(
    "/payments/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}}
)
async def export_payments(
    db: CrmDb,
    actor: ActiveUser,
    entity_id: uuid.UUID | None = None,
    since: date | None = None,
    until: date | None = None,
):
    _need(actor, "invoices.export")
    await _money_on(db, actor)
    from app.modules.money.router import list_payments

    items = await list_payments(
        db=db, actor=actor, entity_id=entity_id, since=since, until=until, limit=MAX_ROWS + 1
    )
    _too_many(len(items))
    header = [
        "Paid on",
        "Receipt",
        "Invoice",
        "Customer",
        "Currency",
        "Amount",
        "Method",
        "Reference",
        "Status",
        "Reverse reason",
        "Recorded by",
    ]
    rows = [
        [
            p.paid_on,
            p.receipt_number,
            p.invoice_number,
            p.customer_name,
            p.currency,
            _major(p.amount_minor, p.currency),
            p.method,
            p.reference,
            p.status,
            p.reverse_reason,
            p.recorded_by_name,
        ]
        for p in items
    ]
    await _done(db, actor, "payments", len(rows))
    return _csv("payments", header, rows)

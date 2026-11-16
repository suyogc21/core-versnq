"""Custom reports (finishing plan, batch 5c).

A report counts, sums or averages one kind of record (leads, deals, tasks, calls, activities,
invoices, payments), filtered, grouped by up to two dimensions, and shown as a table or chart.

Safety:
- Only the dimensions, measures and filters listed here exist. The client names them by key,
  never by column or SQL.
- Every query goes through the same visibility as the lists: a rep's report counts only what
  the rep can see. Brand limits come with those filters. Money needs `invoices.read`.
- A hidden field (field permissions, step 8) can't be grouped, summed or filtered.
- Money is integer minor units and is never added across currencies: any money measure is
  also grouped by currency.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import Numeric, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.brands.models import Brand
from app.modules.calls.models import Call
from app.modules.crm import access as A
from app.modules.crm import deals as D
from app.modules.crm import leads as L
from app.modules.crm.lead_query import LeadFilter, where_clauses
from app.modules.crm.models import (
    Activity,
    ActivityType,
    CustomFieldDefinition,
    Deal,
    Lead,
    LeadSource,
    LeadStage,
    Pipeline,
    PipelineStage,
    Task,
)
from app.modules.money import service as MS
from app.modules.money.models import BillingEntity, Invoice, Payment
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import Team
from app.modules.teams.service import visible_user_ids
from app.modules.users.models import User

MAX_GROUPS = 500
Source = Literal["leads", "deals", "tasks", "calls", "activities", "invoices", "payments"]
UNITS = ("day", "week", "month")


# ---------- the definition (what the client sends and what is saved) ----------
class ReportMeasure(BaseModel):
    op: Literal["count", "sum", "avg"] = "count"
    field: str | None = Field(default=None, max_length=80)


class ReportDefinition(BaseModel):
    source: Source
    group_by: list[str] = Field(default=[], max_length=2)
    measure: ReportMeasure = ReportMeasure()
    date_from: date | None = None  # on the source's main date, whole company days
    date_to: date | None = None
    filters: dict = Field(
        default={}, description="leads: the leads list's filters; others: see catalogue"
    )
    display: Literal["table", "bar", "line", "pie"] = "table"


def parse(raw: dict) -> ReportDefinition:
    try:
        return ReportDefinition.model_validate(raw)
    except ValidationError as e:
        raise Invalid(
            f"This report isn't valid: {e.errors()[0]['msg']}", code="report_invalid"
        ) from None


# ---------- what each source offers ----------
@dataclass
class Dim:
    label: str
    expr: Callable  # () -> SQL expression
    names: Callable[[AsyncSession, list], Awaitable[dict]] | None = None  # id -> name
    hidden: str | None = None  # field-permission name that hides it
    time: bool = False


@dataclass
class Meas:
    label: str
    expr: Callable
    money: bool = False
    hidden: str | None = None


@dataclass
class Filt:
    expr: Callable  # () -> column
    kind: Literal["uuid", "text"] = "uuid"


@dataclass
class Spec:
    label: str
    model: type
    date: Callable  # () -> the main date column
    date_is_day: bool = False  # a Date column (not a timestamp)
    entity: str | None = None  # field permissions / custom fields ("lead", "deal")
    permission: str | None = None
    currency: Callable | None = None
    dims: dict[str, Dim] = field(default_factory=dict)
    measures: dict[str, Meas] = field(default_factory=dict)
    filters: dict[str, Filt] = field(default_factory=dict)
    dates: dict[str, tuple[str, Callable]] = field(default_factory=dict)  # time dims


def _names(model, label_col="name", key_col="id"):
    async def load(db: AsyncSession, ids: list) -> dict:
        ids = [i for i in ids if i is not None]
        if not ids:
            return {}
        col = getattr(model, key_col)
        rows = await db.execute(select(col, getattr(model, label_col)).where(col.in_(ids)))
        return {k: v for k, v in rows.all()}

    return load


USERS = _names(User)


def _specs() -> dict[str, Spec]:
    return {
        "leads": Spec(
            "Leads",
            Lead,
            lambda: Lead.created_at,
            entity="lead",
            dims={
                "stage": Dim("Stage", lambda: Lead.stage_id, _names(LeadStage)),
                "owner": Dim("Owner", lambda: Lead.owner_user_id, USERS),
                "source": Dim("Source", lambda: Lead.source_id, _names(LeadSource)),
                "brand": Dim("Brand", lambda: Lead.brand_id, _names(Brand)),
                "team": Dim("Team", lambda: Lead.team_id, _names(Team)),
                "status": Dim(
                    "Open or closed", lambda: case((Lead.is_open, "Open"), else_="Closed")
                ),
                "band": Dim("Score band", lambda: Lead.score_band),
                "city": Dim("City", lambda: Lead.city, hidden="city"),
                "country": Dim("Country", lambda: Lead.country_code, hidden="country_code"),
            },
            dates={"created": ("Created", lambda: Lead.created_at)},
            measures={"score": Meas("Score", lambda: Lead.score)},
        ),
        "deals": Spec(
            "Deals",
            Deal,
            lambda: Deal.created_at,
            entity="deal",
            currency=lambda: Deal.currency,
            dims={
                "stage": Dim("Stage", lambda: Deal.stage_id, _names(PipelineStage)),
                "pipeline": Dim("Pipeline", lambda: Deal.pipeline_id, _names(Pipeline)),
                "owner": Dim("Owner", lambda: Deal.owner_user_id, USERS),
                "brand": Dim("Brand", lambda: Deal.brand_id, _names(Brand)),
                "team": Dim("Team", lambda: Deal.team_id, _names(Team)),
                "status": Dim("Status", lambda: Deal.status),
                "currency": Dim("Currency", lambda: Deal.currency),
            },
            dates={
                "created": ("Created", lambda: Deal.created_at),
                "closed": ("Closed", lambda: Deal.closed_at),
            },
            measures={
                "amount": Meas("Value", lambda: Deal.amount_minor, money=True, hidden="amount")
            },
            filters={
                "pipeline_id": Filt(lambda: Deal.pipeline_id),
                "owner_user_id": Filt(lambda: Deal.owner_user_id),
                "brand_id": Filt(lambda: Deal.brand_id),
                "status": Filt(lambda: Deal.status, "text"),
                "currency": Filt(lambda: Deal.currency, "text"),
            },
        ),
        "tasks": Spec(
            "Tasks",
            Task,
            lambda: Task.due_at,
            dims={
                "owner": Dim("Owner", lambda: Task.owner_user_id, USERS),
                "status": Dim("Status", lambda: Task.status),
                "priority": Dim("Priority", lambda: Task.priority),
            },
            dates={
                "due": ("Due", lambda: Task.due_at),
                "completed": ("Done", lambda: Task.completed_at),
            },
            filters={
                "owner_user_id": Filt(lambda: Task.owner_user_id),
                "status": Filt(lambda: Task.status, "text"),
            },
        ),
        "calls": Spec(
            "Calls",
            Call,
            lambda: Call.started_at,
            dims={
                "owner": Dim("Rep", lambda: Call.user_id, USERS),
                "direction": Dim("Direction", lambda: Call.direction),
                "status": Dim("Status", lambda: Call.status),
                "source": Dim("Made through", lambda: Call.source),
            },
            dates={"started": ("Started", lambda: Call.started_at)},
            measures={"duration": Meas("Talk time (seconds)", lambda: Call.duration_seconds)},
            filters={
                "user_id": Filt(lambda: Call.user_id),
                "direction": Filt(lambda: Call.direction, "text"),
                "status": Filt(lambda: Call.status, "text"),
            },
        ),
        "activities": Spec(
            "Activities",
            Activity,
            lambda: Activity.occurred_at,
            dims={
                "type": Dim(
                    "Type", lambda: Activity.type_key, _names(ActivityType, "label", "key")
                ),
                "owner": Dim("Who", lambda: Activity.actor_id, USERS),
                "outcome": Dim("Outcome", lambda: Activity.disposition),
            },
            dates={"occurred": ("When", lambda: Activity.occurred_at)},
            filters={
                "type_key": Filt(lambda: Activity.type_key, "text"),
                "actor_id": Filt(lambda: Activity.actor_id),
            },
        ),
        "invoices": Spec(
            "Invoices",
            Invoice,
            lambda: Invoice.issue_date,
            date_is_day=True,
            permission="invoices.read",
            currency=lambda: Invoice.currency,
            dims={
                "status": Dim("Status", lambda: Invoice.status),
                "currency": Dim("Currency", lambda: Invoice.currency),
                "entity": Dim("Billing entity", lambda: Invoice.entity_id, _names(BillingEntity)),
                "brand": Dim("Brand", lambda: Invoice.brand_id, _names(Brand)),
            },
            dates={
                "issued": ("Issued", lambda: Invoice.issue_date),
                "due": ("Due", lambda: Invoice.due_date),
            },
            measures={
                "total": Meas("Total", lambda: Invoice.total_minor, money=True),
                "paid": Meas("Paid", lambda: Invoice.paid_minor, money=True),
                "due": Meas(
                    "Still due", lambda: Invoice.total_minor - Invoice.paid_minor, money=True
                ),
            },
            filters={
                "status": Filt(lambda: Invoice.status, "text"),
                "currency": Filt(lambda: Invoice.currency, "text"),
                "entity_id": Filt(lambda: Invoice.entity_id),
                "brand_id": Filt(lambda: Invoice.brand_id),
            },
        ),
        "payments": Spec(
            "Payments",
            Payment,
            lambda: Payment.paid_on,
            date_is_day=True,
            permission="invoices.read",
            currency=lambda: Payment.currency,
            dims={
                "method": Dim("Method", lambda: Payment.method),
                "currency": Dim("Currency", lambda: Payment.currency),
                "status": Dim("Status", lambda: Payment.status),
                "entity": Dim("Billing entity", lambda: Payment.entity_id, _names(BillingEntity)),
            },
            dates={"paid": ("Paid on", lambda: Payment.paid_on)},
            measures={"amount": Meas("Amount", lambda: Payment.amount_minor, money=True)},
            filters={
                "method": Filt(lambda: Payment.method, "text"),
                "currency": Filt(lambda: Payment.currency, "text"),
                "status": Filt(lambda: Payment.status, "text"),
            },
        ),
    }


SPECS = _specs()


async def _custom_fields(db: AsyncSession, spec: Spec, rules: A.Rules) -> tuple[dict, dict]:
    """Choice fields become dimensions, number fields measures (not hidden ones)."""
    if spec.entity is None:
        return {}, {}
    rows = (
        await db.scalars(
            select(CustomFieldDefinition)
            .where(CustomFieldDefinition.entity == spec.entity)
            .order_by(CustomFieldDefinition.position)
        )
    ).all()
    dims, measures = {}, {}
    cf = spec.model.custom_fields
    for f in rows:
        name = f"cf.{f.key}"
        if rules.hidden(name):
            continue
        if f.type == "select":
            dims[name] = Dim(f.label, lambda k=f.key: cf[k].astext, hidden=name)
        elif f.type == "number":
            measures[name] = Meas(
                f.label,
                lambda k=f.key: case(
                    (func.jsonb_typeof(cf[k]) == "number", cast(cf[k].astext, Numeric)), else_=None
                ),
                hidden=name,
            )
    return dims, measures


async def _rules(db: AsyncSession, actor: CurrentUser, spec: Spec) -> A.Rules:
    return await A.rules(db, actor, spec.entity) if spec.entity else A.Rules("none")


async def available(db: AsyncSession, actor: CurrentUser, source: str) -> Spec | None:
    """The source as this person may use it (None: not allowed)."""
    spec = SPECS[source]
    if spec.permission and not L.can(actor, spec.permission):
        return None
    rules = await _rules(db, actor, spec)
    cf_dims, cf_measures = await _custom_fields(db, spec, rules)
    dims = {k: d for k, d in spec.dims.items() if not (d.hidden and rules.hidden(d.hidden))}
    for key, (label, col) in spec.dates.items():
        for unit in UNITS:
            dims[f"{key}:{unit}"] = Dim(f"{label} ({unit})", col, time=True)
    measures = {k: m for k, m in spec.measures.items() if not (m.hidden and rules.hidden(m.hidden))}
    return Spec(
        spec.label, spec.model, spec.date, spec.date_is_day, spec.entity, spec.permission,
        spec.currency, {**dims, **cf_dims}, {**measures, **cf_measures}, spec.filters, spec.dates,
    )  # fmt: skip


# ---------- visibility ----------
async def _visibility(db: AsyncSession, actor: CurrentUser, source: str, filters: dict):
    """(joins, where) so the report counts only what this person may see in the lists."""
    if source == "leads":
        try:
            f = LeadFilter.model_validate(filters)
        except ValidationError:
            raise Invalid("These lead filters aren't valid", code="report_invalid") from None
        return [], await where_clauses(db, actor, f)
    if source == "deals":
        return [], [await D.visibility_filter(db, actor)]
    if source == "tasks":
        visible = await visible_user_ids(db, actor.user.id, actor.role.scope)
        return [], [] if visible is None else [Task.owner_user_id.in_(visible or [uuid.uuid4()])]
    if source in ("calls", "activities"):
        model = Call if source == "calls" else Activity
        return [(Lead, Lead.id == model.lead_id)], [await L.visibility_filter(db, actor)]
    model = Invoice if source == "invoices" else Payment
    return [(Lead, Lead.id == model.lead_id)], [await MS.visible(db, actor)]


def _filters(spec: Spec, source: str, raw: dict) -> list:
    if source == "leads":
        return []  # the leads list's own filters, applied with visibility
    out = []
    for key, values in raw.items():
        f = spec.filters.get(key)
        if f is None:
            raise Invalid(f"Unknown filter: {key}", code="report_invalid")
        values = values if isinstance(values, list) else [values]
        if not values or len(values) > 100:
            continue
        try:
            clean = (
                [uuid.UUID(str(v)) for v in values]
                if f.kind == "uuid"
                else [str(v)[:60] for v in values]
            )
        except ValueError:
            raise Invalid(f"Filter {key} isn't valid", code="report_invalid") from None
        out.append(f.expr().in_(clean))
    return out


# ---------- running ----------
class ReportRow(BaseModel):
    keys: list[str | None]  # the group's raw values (ids, dates, text)
    labels: list[str]
    currency: str | None = None
    value: int | float  # money and counts are whole numbers


class ReportResult(BaseModel):
    columns: list[str]  # dimension labels, then the measure label
    rows: list[ReportRow]
    money: bool
    truncated: bool


def _bucket(col, unit: str, tz: str, is_day: bool):
    local = col if is_day else func.timezone(tz, col)
    fmt = {"day": "YYYY-MM-DD", "week": 'IYYY-"W"IW', "month": "YYYY-MM"}[unit]
    return func.to_char(func.date_trunc(unit, local), fmt)


async def run(db: AsyncSession, actor: CurrentUser, d: ReportDefinition) -> ReportResult:
    spec = await available(db, actor, d.source)
    if spec is None:
        raise Forbidden("You can't report on money")
    tz = await db.scalar(select(TenantSettings.timezone)) or "UTC"

    groups = []
    for key in d.group_by:
        name, _, unit = key.partition(":")
        dim = spec.dims.get(key)
        if dim is None:
            hidden = SPECS[d.source].dims.get(name) or key.startswith("cf.")
            raise Invalid(
                f"You can't group by {key}" if hidden else f"Unknown grouping: {key}",
                code="field_hidden" if hidden else "report_invalid",
            )
        # invoices and payments keep plain dates; everything else is a moment in time
        expr = _bucket(dim.expr(), unit, tz, spec.date_is_day) if dim.time else dim.expr()
        groups.append((key, dim, expr.label(f"g{len(groups)}")))

    m = d.measure
    if m.op == "count":
        meas, label = func.count(), "Count"
        money = False
    else:
        meas_spec = spec.measures.get(m.field or "")
        if meas_spec is None:
            hidden = (m.field or "") in SPECS[d.source].measures or (m.field or "").startswith(
                "cf."
            )
            raise Invalid(
                f"You can't use {m.field}" if hidden else f"Unknown measure: {m.field}",
                code="field_hidden" if hidden else "report_invalid",
            )
        meas = (func.sum if m.op == "sum" else func.avg)(meas_spec.expr())
        label = f"{'Total' if m.op == 'sum' else 'Average'} {meas_spec.label.lower()}"
        money = meas_spec.money
    cur = spec.currency().label("cur") if money and spec.currency else None

    joins, where = await _visibility(db, actor, d.source, d.filters)
    where += _filters(spec, d.source, d.filters)
    if d.date_from or d.date_to:
        col = spec.date()
        if spec.date_is_day:
            where += [col >= d.date_from] if d.date_from else []
            where += [col <= d.date_to] if d.date_to else []
        else:
            zone = ZoneInfo(tz)
            if d.date_from:
                where.append(col >= datetime.combine(d.date_from, time.min, zone))
            if d.date_to:
                where.append(col < datetime.combine(d.date_to + timedelta(days=1), time.min, zone))

    cols = [g[2] for g in groups] + ([cur] if cur is not None else [])
    q = select(*cols, meas.label("v")).select_from(spec.model)
    for model, on in joins:
        q = q.join(model, on)
    q = q.where(and_(*where)) if where else q
    if cols:
        q = q.group_by(*cols)
    time_first = bool(groups) and groups[0][1].time
    q = q.order_by(cols[0].asc() if time_first else func.coalesce(meas, 0).desc()).limit(
        MAX_GROUPS + 1
    )
    rows = (await db.execute(q)).all()

    names: list[dict] = []
    for i, (_, dim, _) in enumerate(groups):
        names.append(await dim.names(db, [r[i] for r in rows]) if dim.names else {})
    out = []
    for r in rows[:MAX_GROUPS]:
        keys = [None if r[i] is None else str(r[i]) for i in range(len(groups))]
        labels = [
            "—" if r[i] is None else str(names[i].get(r[i], r[i])) for i in range(len(groups))
        ]
        value = r[-1]
        if value is None:
            value = 0
        if money:
            value = int(round(float(value)))  # minor units stay whole numbers
        elif m.op == "count":
            value = int(value)
        else:
            value = round(float(value), 2)
        out.append(
            ReportRow(
                keys=keys,
                labels=labels,
                currency=r[len(groups)] if cur is not None else None,
                value=value,
            )
        )
    columns = [g[1].label for g in groups] + ([("Currency")] if cur is not None else []) + [label]
    return ReportResult(columns=columns, rows=out, money=money, truncated=len(rows) > MAX_GROUPS)


# ---------- the catalogue (what the builder offers this person) ----------
class ReportOption(BaseModel):
    key: str
    label: str


class ReportSource(BaseModel):
    key: str
    label: str
    dimensions: list[ReportOption]
    measures: list[ReportOption]  # count is always there
    money_measures: list[str]
    filters: list[str]


async def catalogue(db: AsyncSession, actor: CurrentUser) -> list[ReportSource]:
    out = []
    for key in SPECS:
        spec = await available(db, actor, key)
        if spec is None:
            continue
        out.append(
            ReportSource(
                key=key, label=spec.label,
                dimensions=[ReportOption(key=k, label=v.label) for k, v in spec.dims.items()],
                measures=[ReportOption(key=k, label=v.label) for k, v in spec.measures.items()],
                money_measures=[k for k, v in spec.measures.items() if v.money],
                filters=list(spec.filters) if key != "leads" else list(LeadFilter.model_fields),
            )
        )  # fmt: skip
    return out

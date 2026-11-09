"""Deals: list, board (kanban with per-stage totals), forecast summary, one deal, moving
between stages, product lines, bulk actions and the deal's timeline."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Text, cast, func, inspect, nulls_last, or_, select

from app.core import money
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.modules.auth.deps import ActiveUser
from app.modules.crm import deals as D
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import (
    Activity,
    CustomFieldUniqueValue,
    Deal,
    DealProduct,
    Lead,
    LostReason,
    Pipeline,
    PipelineStage,
)
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["deals"], dependencies=CRM)


# ---------- schemas ----------
class DealOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    lead_id: uuid.UUID
    lead_name: str | None = None
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    stage_name: str | None = None
    stage_changed_at: datetime
    status: str
    owner_user_id: uuid.UUID | None
    owner_name: str | None = None
    amount_minor: int
    currency: str
    expected_close_on: date | None
    closed_at: datetime | None
    lost_reason_id: uuid.UUID | None
    lost_reason: str | None = None
    close_note: str | None
    custom_fields: dict
    has_lines: bool = False
    created_at: datetime
    updated_at: datetime
    version: int


class DealPage(BaseModel):
    items: list[DealOut]
    total: int


class LineIn(BaseModel):
    product_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    quantity: int = Field(default=1, ge=1, le=money.MAX_QUANTITY)
    unit_price_minor: int | None = Field(default=None, ge=0)  # default: the catalogue price
    discount_minor: int = Field(default=0, ge=0)


class LineOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    product_id: uuid.UUID | None
    name: str
    quantity: int
    unit_price_minor: int
    discount_minor: int
    total_minor: int


class DealIn(BaseModel):
    lead_id: uuid.UUID
    name: str | None = Field(default=None, max_length=300)  # default: the lead's name
    pipeline_id: uuid.UUID | None = None  # default: the first active pipeline
    stage_id: uuid.UUID | None = None  # default: its first open stage
    owner_user_id: uuid.UUID | None = None
    assign_to_me: bool = True
    amount_minor: int = Field(default=0, ge=0)
    expected_close_on: date | None = None
    custom_fields: dict = {}
    lines: list[LineIn] = []


class DealPatch(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=300)
    owner_user_id: uuid.UUID | None = None
    amount_minor: int | None = Field(default=None, ge=0)
    expected_close_on: date | None = None
    custom_fields: dict | None = None
    pipeline_id: uuid.UUID | None = None  # to another pipeline in the same currency
    stage_id: uuid.UUID | None = None  # with pipeline_id: where it lands (default first open)


class MoveIn(BaseModel):
    version: int
    stage_id: uuid.UUID
    lost_reason_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


class LinesIn(BaseModel):
    version: int
    lines: list[LineIn] = Field(max_length=D.MAX_LINES)


class DealWithLines(BaseModel):
    deal: DealOut
    lines: list[LineOut]


# ---------- helpers ----------
async def _out(db, deals: list[Deal]) -> list[DealOut]:
    for d in deals:
        if inspect(d).expired_attributes:
            await db.refresh(d)
    if not deals:
        return []

    async def names(model, col, ids):
        ids = {i for i in ids if i}
        if not ids:
            return {}
        return dict((await db.execute(select(model.id, col).where(model.id.in_(ids)))).all())

    leads = await names(Lead, Lead.display_name, [d.lead_id for d in deals])
    owners = await names(User, User.name, [d.owner_user_id for d in deals])
    stages = await names(PipelineStage, PipelineStage.name, [d.stage_id for d in deals])
    reasons = await names(LostReason, LostReason.name, [d.lost_reason_id for d in deals])
    with_lines = set(
        (
            await db.scalars(
                select(DealProduct.deal_id)
                .where(DealProduct.deal_id.in_([d.id for d in deals]))
                .distinct()
            )
        ).all()
    )
    out = []
    for d in deals:
        item = DealOut.model_validate(d)
        item.lead_name = leads.get(d.lead_id)
        item.owner_name = owners.get(d.owner_user_id)
        item.stage_name = stages.get(d.stage_id)
        item.lost_reason = reasons.get(d.lost_reason_id)
        item.has_lines = d.id in with_lines
        out.append(item)
    return out


async def _one(db, deal: Deal) -> DealOut:
    await db.flush()
    return (await _out(db, [deal]))[0]


def _lines(items: list[LineIn]) -> list[D.LineIn]:
    return [D.LineIn(**i.model_dump()) for i in items]


async def _editable(db, actor, deal_id: uuid.UUID, version: int | None = None) -> Deal:
    deal = await D.get_visible(db, actor, deal_id)
    D.require(actor, "deals.edit")
    if version is not None and version != deal.version:
        raise Conflict("Someone else changed this deal. Reload to see their changes")
    return deal


def _owner_filter(owner: list[str], actor):
    conds = []
    for o in owner:
        if o == "me":
            conds.append(Deal.owner_user_id == actor.user.id)
        elif o == "unassigned":
            conds.append(Deal.owner_user_id.is_(None))
        else:
            try:
                conds.append(Deal.owner_user_id == uuid.UUID(o))
            except ValueError:
                raise Invalid("Unknown owner filter") from None
    return or_(*conds)


def _cf_filters(cf: list[str]) -> list:
    by_key: dict[str, list[str]] = {}
    for item in cf:
        key, _, value = item.partition(":")
        if not key or not value:
            raise Invalid("Custom field filters look like key:value")
        by_key.setdefault(key, []).append(value)
    out = []
    for key, values in by_key.items():
        field = Deal.custom_fields[key]
        out.append(or_(*[or_(field.astext == v, field.contains([v])) for v in values]))
    return out


# ---------- list ----------
SortKey = Literal["created", "updated", "name", "amount", "close", "stage", "owner"]


@router.get("/deals", response_model=DealPage)
async def list_deals(
    db: CrmDb,
    actor: ActiveUser,
    pipeline_id: uuid.UUID | None = None,
    stage_id: Annotated[list[uuid.UUID], Query()] = [],  # noqa: B006 — FastAPI query lists
    status_: Annotated[Literal["open", "won", "lost"] | None, Query(alias="status")] = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
    lead_id: uuid.UUID | None = None,
    close_from: date | None = None,
    close_to: date | None = None,
    q: str | None = None,
    cf: Annotated[list[str], Query()] = [],  # noqa: B006 — "key:value"
    sort: SortKey = "created",
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DealPage:
    where = [await D.visibility_filter(db, actor)]
    if pipeline_id:
        where.append(Deal.pipeline_id == pipeline_id)
    if stage_id:
        where.append(Deal.stage_id.in_(stage_id))
    if status_:
        where.append(Deal.status == status_)
    if owner:
        where.append(_owner_filter(owner, actor))
    if lead_id:
        where.append(Deal.lead_id == lead_id)
    if close_from:
        where.append(Deal.expected_close_on >= close_from)
    if close_to:
        where.append(Deal.expected_close_on <= close_to)
    if q and q.strip():
        term = f"%{q.strip()}%"
        lead_match = select(Lead.id).where(Lead.display_name.ilike(term))
        where.append(
            or_(
                Deal.name.ilike(term),
                Deal.lead_id.in_(lead_match),
                cast(Deal.custom_fields, Text).ilike(term),
            )
        )
    where += _cf_filters(cf)
    total = await db.scalar(select(func.count()).select_from(Deal).where(*where)) or 0
    order = {
        "created": Deal.created_at,
        "updated": Deal.updated_at,
        "name": func.lower(Deal.name),
        "amount": Deal.amount_minor,
        "close": Deal.expected_close_on,
        "stage": select(PipelineStage.position)
        .where(PipelineStage.id == Deal.stage_id)
        .scalar_subquery(),
        "owner": select(User.name).where(User.id == Deal.owner_user_id).scalar_subquery(),
    }[sort]
    order = order.asc() if direction == "asc" else order.desc()
    rows = await db.scalars(
        select(Deal)
        .where(*where)
        .order_by(nulls_last(order), Deal.created_at.desc(), Deal.id)
        .limit(limit)
        .offset(offset)
    )
    return DealPage(items=await _out(db, list(rows.all())), total=total)


# ---------- board + forecast ----------
class BoardColumn(BaseModel):
    stage_id: uuid.UUID
    name: str
    kind: str
    probability: int
    colour: str | None
    count: int
    amount_minor: int
    weighted_minor: int
    deals: list[DealOut]


class BoardOut(BaseModel):
    pipeline_id: uuid.UUID
    pipeline_name: str
    currency: str
    columns: list[BoardColumn]
    open_count: int
    open_minor: int
    weighted_minor: int
    won_minor: int


CARDS_PER_STAGE = 100


@router.get("/deals/board", response_model=BoardOut)
async def board(
    db: CrmDb,
    actor: ActiveUser,
    pipeline_id: uuid.UUID | None = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
    q: str | None = None,
) -> BoardOut:
    """The pipeline's stages with their visible deals (newest move first, up to 100 each) and
    exact totals: value, and weighted value = value × the stage's win %."""
    pipeline = (
        await D.get_pipeline(db, pipeline_id) if pipeline_id else await D.default_pipeline(db)
    )
    where = []
    if owner:
        where.append(_owner_filter(owner, actor))
    if q and q.strip():
        term = f"%{q.strip()}%"
        where.append(
            or_(
                Deal.name.ilike(term),
                Deal.lead_id.in_(select(Lead.id).where(Lead.display_name.ilike(term))),
            )
        )
    totals = await D.stage_totals(db, actor, pipeline, where)
    ranked = (
        select(
            Deal.id,
            func.row_number()
            .over(partition_by=Deal.stage_id, order_by=(Deal.stage_changed_at.desc(), Deal.id))
            .label("n"),
        )
        .where(Deal.pipeline_id == pipeline.id, await D.visibility_filter(db, actor), *where)
        .subquery()
    )
    cards = (
        await db.scalars(
            select(Deal)
            .join(ranked, ranked.c.id == Deal.id)
            .where(ranked.c.n <= CARDS_PER_STAGE)
            .order_by(Deal.stage_changed_at.desc(), Deal.id)
        )
    ).all()
    cards_out = await _out(db, list(cards))
    columns = []
    for stage in await D.stages_of(db, pipeline.id):
        t = totals[stage.id]
        columns.append(
            BoardColumn(
                stage_id=stage.id,
                name=stage.name,
                kind=stage.kind,
                probability=stage.probability,
                colour=stage.colour,
                count=t.count,
                amount_minor=t.amount_minor,
                weighted_minor=t.weighted_minor,
                deals=[c for c in cards_out if c.stage_id == stage.id],
            )
        )
    open_cols = [c for c in columns if c.kind == "open"]
    return BoardOut(
        pipeline_id=pipeline.id,
        pipeline_name=pipeline.name,
        currency=pipeline.currency,
        columns=columns,
        open_count=sum(c.count for c in open_cols),
        open_minor=sum(c.amount_minor for c in open_cols),
        weighted_minor=sum(c.weighted_minor for c in open_cols),
        won_minor=sum(c.amount_minor for c in columns if c.kind == "won"),
    )


class PipelineSummary(BaseModel):
    pipeline_id: uuid.UUID
    name: str
    currency: str
    open_count: int
    open_minor: int
    weighted_minor: int
    won_count: int
    won_minor: int
    lost_count: int


@router.get("/deals/summary", response_model=list[PipelineSummary])
async def summary(
    db: CrmDb,
    actor: ActiveUser,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
) -> list[PipelineSummary]:
    """Forecast per pipeline (each in its own currency; never added across currencies)."""
    where = [_owner_filter(owner, actor)] if owner else []
    out = []
    for p in (await db.scalars(select(Pipeline).order_by(Pipeline.position))).all():
        totals = await D.stage_totals(db, actor, p, where)
        stages = {s.id: s for s in await D.stages_of(db, p.id)}

        def of(kind, field, stages=stages, totals=totals):
            return sum(getattr(t, field) for sid, t in totals.items() if stages[sid].kind == kind)

        out.append(
            PipelineSummary(
                pipeline_id=p.id,
                name=p.name,
                currency=p.currency,
                open_count=of("open", "count"),
                open_minor=of("open", "amount_minor"),
                weighted_minor=of("open", "weighted_minor"),
                won_count=of("won", "count"),
                won_minor=of("won", "amount_minor"),
                lost_count=of("lost", "count"),
            )
        )
    return out


# ---------- one deal ----------
@router.post("/deals", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def create_deal(body: DealIn, db: CrmDb, actor: ActiveUser) -> DealOut:
    D.require(actor, "deals.create")
    lead = await L.get_visible(db, actor, body.lead_id)
    if body.pipeline_id:
        pipeline = await D.get_pipeline(db, body.pipeline_id)
        if not pipeline.is_active:
            raise Invalid(f"{pipeline.name} is switched off")
    else:
        pipeline = await D.default_pipeline(db)
    stage = (
        await D.get_stage(db, pipeline, body.stage_id)
        if body.stage_id
        else await D.first_open_stage(db, pipeline)
    )
    if stage.kind != "open":
        raise Invalid("New deals start in an open stage")
    owner_id = body.owner_user_id or (actor.user.id if body.assign_to_me else None)
    owner = await D.check_owner(db, actor, owner_id)
    deal = Deal(
        tenant_id=actor.user.tenant_id,
        name=" ".join((body.name or lead.display_name).split())[:300] or lead.display_name,
        lead_id=lead.id,
        pipeline_id=pipeline.id,
        stage_id=stage.id,
        stage_changed_at=L.now(),
        status="open",
        owner_user_id=owner.id if owner else None,
        team_id=await L.owner_team(db, owner.id if owner else None),
        amount_minor=money.check_amount(body.amount_minor),
        currency=pipeline.currency,
        expected_close_on=body.expected_close_on,
        custom_fields={},
        created_by_user_id=actor.user.id,
    )
    db.add(deal)
    await db.flush()
    await L.apply_custom_fields(db, deal, body.custom_fields, creating=True, entity=D.ENTITY)
    if body.lines:
        await D.set_lines(db, deal, _lines(body.lines))
    await D.check_stage_entry(db, deal, stage)
    await D.log(db, deal, "deal_created", f"Deal added: {deal.name}", actor)
    await D.event(db, deal, "deal.created")
    return await _one(db, deal)


@router.get("/deals/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> DealOut:
    return await _one(db, await D.get_visible(db, actor, deal_id))


@router.patch("/deals/{deal_id}", response_model=DealOut)
async def update_deal(deal_id: uuid.UUID, body: DealPatch, db: CrmDb, actor: ActiveUser) -> DealOut:
    deal = await _editable(db, actor, deal_id, body.version)
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    changed: list[str] = []
    if body.name is not None and " ".join(body.name.split()) != deal.name:
        deal.name = " ".join(body.name.split())
        changed.append("name")
    if body.amount_minor is not None and body.amount_minor != deal.amount_minor:
        if await D.has_lines(db, deal.id):
            raise Invalid("This deal's amount comes from its products; change those instead")
        deal.amount_minor = money.check_amount(body.amount_minor)
        changed.append("amount")
    if "expected_close_on" in changes and changes["expected_close_on"] != deal.expected_close_on:
        deal.expected_close_on = changes["expected_close_on"]
        changed.append("expected close date")
    if body.custom_fields is not None:
        changed += await L.apply_custom_fields(
            db, deal, body.custom_fields, creating=False, entity=D.ENTITY
        )
    if "owner_user_id" in changes and changes["owner_user_id"] != deal.owner_user_id:
        owner = await D.check_owner(db, actor, changes["owner_user_id"])
        deal.owner_user_id = owner.id if owner else None
        deal.team_id = await L.owner_team(db, deal.owner_user_id)
        await D.log(
            db, deal, "deal_updated",
            f"{deal.name}: assigned to {owner.name}" if owner else f"{deal.name}: unassigned",
            actor, {"owner_user_id": str(owner.id) if owner else None},
        )  # fmt: skip
        changed.append("owner")
    if body.pipeline_id and body.pipeline_id != deal.pipeline_id:
        await _change_pipeline(db, actor, deal, body.pipeline_id, body.stage_id)
        changed.append("pipeline")
    details = [c for c in changed if c not in ("owner", "pipeline")]
    if details:
        await D.log(
            db, deal, "deal_updated", f"{deal.name}: changed {', '.join(details)}", actor,
            {"fields": details},
        )  # fmt: skip
    if changed:
        await D.event(db, deal, "deal.updated", {"fields": changed})
    deal.version += 1
    return await _one(db, deal)


async def _change_pipeline(db, actor, deal: Deal, pipeline_id, stage_id) -> None:
    pipeline = await D.get_pipeline(db, pipeline_id)
    if not pipeline.is_active:
        raise Invalid(f"{pipeline.name} is switched off")
    if pipeline.currency != deal.currency:
        raise Invalid(f"{pipeline.name} is in {pipeline.currency}; this deal is in {deal.currency}")
    if deal.status != "open":
        raise Invalid("Reopen the deal before moving it to another pipeline")
    stage = (
        await D.get_stage(db, pipeline, stage_id)
        if stage_id
        else await D.first_open_stage(db, pipeline)
    )
    if stage.kind != "open":
        raise Invalid("Choose an open stage")
    await D.check_stage_entry(db, deal, stage)
    old = await db.get(Pipeline, deal.pipeline_id)
    deal.pipeline_id, deal.stage_id, deal.stage_changed_at = pipeline.id, stage.id, L.now()
    data = {"from_pipeline": str(old.id), "to_pipeline": str(pipeline.id), "to": str(stage.id)}
    await D.log(
        db, deal, "deal_stage_changed", f"{deal.name}: {old.name} → {pipeline.name} ({stage.name})",
        actor, data,
    )  # fmt: skip
    await D.event(db, deal, "deal.stage_changed", data)


@router.post("/deals/{deal_id}/move", response_model=DealOut)
async def move_deal(deal_id: uuid.UUID, body: MoveIn, db: CrmDb, actor: ActiveUser) -> DealOut:
    """Drag on the board. Lost needs a reason; won/lost close the deal; open reopens it."""
    deal = await _editable(db, actor, deal_id, body.version)
    pipeline = await db.get(Pipeline, deal.pipeline_id)
    stage = await D.get_stage(db, pipeline, body.stage_id)
    if stage.id == deal.stage_id:
        return await _one(db, deal)
    await D.move(db, actor, deal, stage, lost_reason_id=body.lost_reason_id, note=body.note)
    deal.version += 1
    return await _one(db, deal)


@router.delete("/deals/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(deal_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> None:
    """Permanent (#18): the deal, its lines, tasks, links and deal timeline entries go.
    The lead keeps one 'Deal deleted' entry."""
    deal = await D.get_visible(db, actor, deal_id)
    D.require(actor, "deals.delete")
    await _delete(db, actor, deal)


async def _delete(db, actor, deal: Deal) -> None:
    await db.execute(
        CustomFieldUniqueValue.__table__.delete().where(
            CustomFieldUniqueValue.entity == D.ENTITY, CustomFieldUniqueValue.record_id == deal.id
        )
    )
    await D.event(db, deal, "deal.deleted")
    lead = await db.get(Lead, deal.lead_id)
    await L.log(
        db, lead, "deal_deleted", f"Deal deleted: {deal.name}", actor,
        {"deal_name": deal.name, "amount_minor": deal.amount_minor, "currency": deal.currency},
    )  # fmt: skip
    deal_id, name = deal.id, deal.name
    await db.delete(deal)
    await db.flush()
    await audit(db, actor, "deal.deleted", "deal", deal_id, {"name": name})


# ---------- lines ----------
@router.get("/deals/{deal_id}/products", response_model=list[LineOut])
async def get_lines(deal_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> list[DealProduct]:
    deal = await D.get_visible(db, actor, deal_id)
    return await D.lines_of(db, deal.id)


@router.put("/deals/{deal_id}/products", response_model=DealWithLines)
async def set_lines(deal_id: uuid.UUID, body: LinesIn, db: CrmDb, actor: ActiveUser):
    """Replace the lines. With lines, the deal's amount is their exact sum; with none, the
    amount stays as it was and can be typed again."""
    deal = await _editable(db, actor, deal_id, body.version)
    before = deal.amount_minor
    rows = await D.set_lines(db, deal, _lines(body.lines))
    summary = f"{deal.name}: products updated ({len(rows)} line{'s' if len(rows) != 1 else ''})"
    await D.log(db, deal, "deal_updated", summary, actor, {"fields": ["products"]})
    fields = ["products"] + (["amount"] if deal.amount_minor != before else [])
    await D.event(db, deal, "deal.updated", {"fields": fields})
    deal.version += 1
    return DealWithLines(
        deal=await _one(db, deal),
        lines=[LineOut.model_validate(r) for r in await D.lines_of(db, deal.id)],
    )


# ---------- bulk ----------
class BulkIn(BaseModel):
    action: Literal["assign", "stage", "delete"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    owner_user_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    lost_reason_id: uuid.UUID | None = None


class Skipped(BaseModel):
    id: uuid.UUID
    name: str
    reason: str


class BulkOut(BaseModel):
    done: int
    skipped: list[Skipped]


@router.post("/deals/bulk", response_model=BulkOut)
async def bulk_deals(body: BulkIn, db: CrmDb, actor: ActiveUser) -> BulkOut:
    """Same rules as one at a time; deals that fail one are skipped and reported."""
    done, skipped = 0, []
    for did in body.ids:
        try:
            deal = await D.get_visible(db, actor, did)
        except NotFound:
            continue
        try:
            async with db.begin_nested():
                if body.action == "delete":
                    D.require(actor, "deals.delete")
                    await _delete(db, actor, deal)
                elif body.action == "assign":
                    patch = DealPatch(version=deal.version, owner_user_id=body.owner_user_id)
                    await update_deal(did, patch, db, actor)
                else:
                    if body.stage_id is None:
                        raise Invalid("Choose a stage")
                    move = MoveIn(
                        version=deal.version, stage_id=body.stage_id,
                        lost_reason_id=body.lost_reason_id,
                    )  # fmt: skip
                    await move_deal(did, move, db, actor)
            done += 1
        except (Invalid, Forbidden, Conflict) as e:
            skipped.append(Skipped(id=did, name=deal.name, reason=e.detail))
    return BulkOut(done=done, skipped=skipped)


# ---------- timeline ----------
class DealActivityOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    type_key: str
    actor_type: str
    actor_id: uuid.UUID | None
    actor_name: str | None = None
    occurred_at: datetime
    summary: str
    body: str | None
    data: dict


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


async def _acts_out(db, rows: list[Activity]) -> list[DealActivityOut]:
    ids = {a.actor_id for a in rows if a.actor_id}
    names = (
        dict((await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all())
        if ids
        else {}
    )
    out = []
    for a in rows:
        item = DealActivityOut.model_validate(a)
        item.actor_name = names.get(a.actor_id)
        out.append(item)
    return out


@router.get("/deals/{deal_id}/activities", response_model=list[DealActivityOut])
async def deal_timeline(
    deal_id: uuid.UUID,
    db: CrmDb,
    actor: ActiveUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[DealActivityOut]:
    deal = await D.get_visible(db, actor, deal_id)
    rows = (
        await db.scalars(
            select(Activity)
            .where(Activity.deal_id == deal.id)
            .order_by(Activity.occurred_at.desc(), Activity.created_at.desc())
            .limit(limit)
        )
    ).all()
    return await _acts_out(db, list(rows))


@router.post(
    "/deals/{deal_id}/notes", response_model=DealActivityOut, status_code=status.HTTP_201_CREATED
)
async def add_note(deal_id: uuid.UUID, body: NoteIn, db: CrmDb, actor: ActiveUser):
    deal = await _editable(db, actor, deal_id)
    text_ = body.body.strip()
    if not text_:
        raise Invalid("Write the note")
    activity = await D.log(db, deal, "note", text_.splitlines()[0][:120], actor, body=text_)
    return (await _acts_out(db, [activity]))[0]

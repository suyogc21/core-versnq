"""Deal rules: visibility, owners, stage moves (won / lost / reopen), product lines with exact
totals, timeline and events. Generic: pipelines, stages and reasons are company data.

Visibility follows the deal's own owner with the role's own / team / all scope (like leads).
A deal's timeline entries carry its lead too, so they appear on the lead's timeline.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import money
from app.core.errors import Forbidden, Invalid, NotFound
from app.core.events import emit
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import (
    Activity,
    Deal,
    DealProduct,
    Lead,
    LostReason,
    Pipeline,
    PipelineStage,
    Product,
)
from app.modules.teams.service import visible_user_ids
from app.modules.users.models import User

ENTITY = "deal"  # custom fields of deals
MAX_LINES = 100


# ---------- visibility ----------
async def visibility_filter(db: AsyncSession, actor: CurrentUser):
    """The deals this person may see: by owner and scope, and only of their brands (batch 4)."""
    from app.modules.brands import service as B

    brands = await B.condition(db, actor.user.id, Deal.brand_id)
    scope = actor.role.scope
    if scope == "all":
        return brands
    visible = await visible_user_ids(db, actor.user.id, scope)
    owned = Deal.owner_user_id.in_(visible) if visible else false()
    if scope == "team":
        return and_(or_(owned, Deal.owner_user_id.is_(None)), brands)
    return and_(owned, brands)


async def get_visible(db: AsyncSession, actor: CurrentUser, deal_id: uuid.UUID) -> Deal:
    deal = await db.scalar(
        select(Deal).where(Deal.id == deal_id, await visibility_filter(db, actor))
    )
    if deal is None:
        raise NotFound("Deal not found")
    return deal


def require(actor: CurrentUser, code: str) -> None:
    if not L.can(actor, code):
        raise Forbidden("permission_denied")


async def check_owner(
    db: AsyncSession, actor: CurrentUser, user_id: uuid.UUID | None
) -> User | None:
    """An active user the actor can see; 'own' scope may only give deals to themselves."""
    if actor.role.scope == "own" and user_id != actor.user.id:
        raise Forbidden("You can only own deals yourself")
    return await L.check_assignable(db, actor, user_id)


# ---------- pipelines and stages ----------
async def get_pipeline(db: AsyncSession, pipeline_id: uuid.UUID) -> Pipeline:
    pipeline = await db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise Invalid("Choose a pipeline")
    return pipeline


async def default_pipeline(db: AsyncSession) -> Pipeline:
    pipeline = await db.scalar(
        select(Pipeline).where(Pipeline.is_active.is_(True)).order_by(Pipeline.position).limit(1)
    )
    if pipeline is None:
        raise Invalid("Set up a pipeline first")
    return pipeline


async def stages_of(db: AsyncSession, pipeline_id: uuid.UUID) -> list[PipelineStage]:
    return list(
        (
            await db.scalars(
                select(PipelineStage)
                .where(PipelineStage.pipeline_id == pipeline_id)
                .order_by(PipelineStage.position)
            )
        ).all()
    )


async def get_stage(db: AsyncSession, pipeline: Pipeline, stage_id: uuid.UUID) -> PipelineStage:
    stage = await db.get(PipelineStage, stage_id)
    if stage is None or stage.pipeline_id != pipeline.id:
        raise Invalid("Choose a stage of this pipeline")
    return stage


async def first_open_stage(db: AsyncSession, pipeline: Pipeline) -> PipelineStage:
    stage = next((s for s in await stages_of(db, pipeline.id) if s.kind == "open"), None)
    if stage is None:
        raise Invalid(f"{pipeline.name} has no open stage")
    return stage


# Built-in fields a stage can require, besides the deal's custom fields.
BUILTIN_REQUIRED = {
    "amount": ("amount", lambda d, lines: d.amount_minor > 0),
    "expected_close_on": ("expected close date", lambda d, lines: d.expected_close_on is not None),
    "owner": ("owner", lambda d, lines: d.owner_user_id is not None),
    "products": ("products", lambda d, lines: lines > 0),
}


async def check_stage_entry(
    db: AsyncSession, deal: Deal, stage: PipelineStage, actor: CurrentUser | None = None
) -> None:
    """Required fields per stage; a field the person may not edit never blocks them (#38)."""
    if not stage.required_fields:
        return
    from app.modules.crm import access as A

    rules = await A.rules(db, actor, ENTITY)
    defs = await L.lead_fields(db, ENTITY)
    lines = await db.scalar(
        select(func.count()).select_from(DealProduct).where(DealProduct.deal_id == deal.id)
    )
    missing = []
    for key in stage.required_fields:
        if not rules.editable(key if key in BUILTIN_REQUIRED else f"cf.{key}"):
            continue
        if key in BUILTIN_REQUIRED:
            label, ok = BUILTIN_REQUIRED[key]
            if not ok(deal, lines):
                missing.append(label)
        elif (deal.custom_fields or {}).get(key) is None:
            missing.append(defs[key].label if key in defs else key)
    if missing:
        raise Invalid(f"To move to {stage.name}, fill in: {', '.join(missing)}")


# ---------- timeline + events ----------
async def log(
    db: AsyncSession,
    deal: Deal,
    type_key: str,
    summary: str,
    actor: CurrentUser | None,
    data: dict | None = None,
    body: str | None = None,
) -> Activity:
    activity = Activity(
        tenant_id=deal.tenant_id,
        lead_id=deal.lead_id,
        deal_id=deal.id,
        type_key=type_key,
        actor_type=L.actor_type(actor),
        actor_id=actor.user.id if actor else None,
        occurred_at=L.now(),
        summary=summary[:500],
        body=body,
        data=L.automation_note({"deal_name": deal.name} | (data or {})),
    )
    db.add(activity)
    await db.flush()
    lead = await db.get(Lead, deal.lead_id)
    lead.last_activity_at = activity.occurred_at
    return activity


async def event(db: AsyncSession, deal: Deal, type_: str, extra: dict | None = None) -> None:
    await emit(
        db,
        deal.tenant_id,
        type_,
        {
            "deal_id": str(deal.id),
            "lead_id": str(deal.lead_id),
            "pipeline_id": str(deal.pipeline_id),
            "amount_minor": deal.amount_minor,
            "currency": deal.currency,
        }
        | (extra or {}),
    )


# ---------- moving ----------
async def move(
    db: AsyncSession,
    actor: CurrentUser | None,
    deal: Deal,
    stage: PipelineStage,
    *,
    lost_reason_id: uuid.UUID | None = None,
    note: str | None = None,
) -> None:
    """Move to a stage of the deal's pipeline. Lost needs a reason; won/lost close the deal;
    moving a closed deal to an open stage reopens it."""
    if stage.pipeline_id != deal.pipeline_id:
        raise Invalid("Choose a stage of this pipeline")
    if stage.id == deal.stage_id:
        return
    await check_stage_entry(db, deal, stage, actor)
    reason = None
    if stage.kind == "lost":
        if lost_reason_id is None:
            raise Invalid("Choose why the deal was lost")
        reason = await db.get(LostReason, lost_reason_id)
        if reason is None or not reason.is_active:
            raise Invalid("Choose an active lost reason")
    old = await db.get(PipelineStage, deal.stage_id)
    was = deal.status
    deal.stage_id, deal.stage_changed_at = stage.id, L.now()
    deal.status = stage.kind
    note = (note or "").strip() or None
    if stage.kind == "open":
        deal.closed_at, deal.lost_reason_id, deal.close_note = None, None, None
    else:
        deal.closed_at = deal.closed_at if was == stage.kind else L.now()
        deal.lost_reason_id = reason.id if reason else None
        deal.close_note = note
    data = {"from": str(old.id) if old else None, "to": str(stage.id)}
    await log(
        db,
        deal,
        "deal_stage_changed",
        f"{deal.name}: {old.name if old else '—'} → {stage.name}",
        actor,
        data,
    )
    await event(db, deal, "deal.stage_changed", data)
    if stage.kind == "won" and was != "won":
        await log(db, deal, "deal_won", f"Won: {deal.name}", actor, body=note)
        await event(db, deal, "deal.won")
        from app.modules.crm import customers  # customers build on deals

        if customer := await customers.of_lead(db, deal.lead_id):
            await customers.sync_documents(db, customer)  # product-specific checklist items
    elif stage.kind == "lost" and was != "lost":
        await log(
            db,
            deal,
            "deal_lost",
            f"Lost: {deal.name} — {reason.name}",
            actor,
            {"lost_reason_id": str(reason.id), "lost_reason": reason.name},
            body=note,
        )
        await event(db, deal, "deal.lost", {"lost_reason": reason.name})
    elif stage.kind == "open" and was != "open":
        await log(db, deal, "deal_reopened", f"Reopened: {deal.name}", actor)


# ---------- product lines ----------
@dataclass
class LineIn:
    product_id: uuid.UUID | None
    name: str | None
    quantity: int
    unit_price_minor: int | None
    discount_minor: int


async def set_lines(db: AsyncSession, deal: Deal, items: list[LineIn]) -> list[DealProduct]:
    """Replace the deal's lines. Prices default to the catalogue; every line is in the deal's
    currency (D3). The deal's amount becomes the exact sum of the lines."""
    if len(items) > MAX_LINES:
        raise Invalid(f"A deal can have at most {MAX_LINES} lines")
    rows: list[DealProduct] = []
    for i, item in enumerate(items):
        product = None
        if item.product_id:
            product = await db.get(Product, item.product_id)
            if product is None:
                raise Invalid("Choose a product from the catalogue")
            if product.currency != deal.currency:
                raise Invalid(
                    f"{product.name} is priced in {product.currency}, not {deal.currency}"
                )
        name = " ".join((item.name or (product.name if product else "")).split())
        if not name:
            raise Invalid("Each line needs a name")
        price = item.unit_price_minor if item.unit_price_minor is not None else None
        if price is None:
            if product is None:
                raise Invalid(f"Give a price for {name}")
            price = product.price_minor
        total = money.line_total(item.quantity, price, item.discount_minor)
        rows.append(
            DealProduct(
                tenant_id=deal.tenant_id,
                deal_id=deal.id,
                product_id=product.id if product else None,
                name=name[:200],
                quantity=item.quantity,
                unit_price_minor=price,
                discount_minor=item.discount_minor,
                total_minor=total,
                position=i,
            )
        )
    amount = money.check_amount(sum(r.total_minor for r in rows), "The deal total")
    for old in (await db.scalars(select(DealProduct).where(DealProduct.deal_id == deal.id))).all():
        await db.delete(old)
    await db.flush()
    db.add_all(rows)
    if rows:
        deal.amount_minor = amount
    await db.flush()
    return rows


async def lines_of(db: AsyncSession, deal_id: uuid.UUID) -> list[DealProduct]:
    return list(
        (
            await db.scalars(
                select(DealProduct)
                .where(DealProduct.deal_id == deal_id)
                .order_by(DealProduct.position)
            )
        ).all()
    )


async def has_lines(db: AsyncSession, deal_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(select(DealProduct.id).where(DealProduct.deal_id == deal_id).limit(1))
    )


# ---------- forecast ----------
@dataclass
class StageTotals:
    count: int
    amount_minor: int
    weighted_minor: int


async def stage_totals(db: AsyncSession, actor: CurrentUser, pipeline: Pipeline, where=()):
    """Per stage: visible deals, their value and the weighted value (value × win %)."""
    rows = (
        await db.execute(
            select(Deal.stage_id, func.count(), func.coalesce(func.sum(Deal.amount_minor), 0))
            .where(Deal.pipeline_id == pipeline.id, await visibility_filter(db, actor), *where)
            .group_by(Deal.stage_id)
        )
    ).all()
    by_stage = {sid: (int(n), int(total)) for sid, n, total in rows}
    out: dict[uuid.UUID, StageTotals] = {}
    for stage in await stages_of(db, pipeline.id):
        n, total = by_stage.get(stage.id, (0, 0))
        out[stage.id] = StageTotals(n, total, money.weighted(total, stage.probability))
    return out

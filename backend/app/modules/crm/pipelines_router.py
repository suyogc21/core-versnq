"""Setting up deals: pipelines and their stages, lost reasons, the product catalogue.
Everyone may read them (the board needs them); changing them needs crm.configure."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.core import money
from app.core.errors import Conflict, Invalid
from app.modules.auth.deps import ActiveUser
from app.modules.crm import deals as D
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import (
    Deal,
    DealProduct,
    LostReason,
    Pipeline,
    PipelineStage,
    Product,
)
from app.modules.crm.setup_router import (
    HEX,
    Configurer,
    OrderIn,
    _get,
    _next_position,
    _reorder,
    _snap,
)
from app.modules.settings.models import TenantSettings

router = APIRouter(prefix="/api/v1", tags=["deal setup"], dependencies=CRM)

Kind = Literal["open", "won", "lost"]


# ---------- schemas ----------
class PipelineStageOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    pipeline_id: uuid.UUID
    name: str
    position: int
    kind: str
    probability: int
    colour: str | None
    required_fields: list[str]


class PipelineOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    currency: str
    is_active: bool
    position: int
    stages: list[PipelineStageOut] = []
    deal_count: int = 0


class StageIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Kind = "open"
    probability: int = Field(default=0, ge=0, le=100)
    colour: str | None = Field(default=None, pattern=HEX)
    required_fields: list[str] = []


class StagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: Kind | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    colour: str | None = Field(default=None, pattern=HEX)
    required_fields: list[str] | None = None


class PipelineIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")  # default: company's
    stages: list[StageIn] = []  # default: New, Won, Lost


class PipelinePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    is_active: bool | None = None


class LostReasonOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    is_active: bool
    position: int


class LostReasonIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class LostReasonPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class ProductOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    price_minor: int
    currency: str
    is_active: bool
    created_at: datetime


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    price_minor: int
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")  # default: company's


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    price_minor: int | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    is_active: bool | None = None


DEFAULT_STAGES = [
    StageIn(name="New", kind="open", probability=10),
    StageIn(name="Won", kind="won", probability=100),
    StageIn(name="Lost", kind="lost", probability=0),
]


# ---------- helpers ----------
async def _company_currency(db, tenant_id: uuid.UUID) -> str:
    return (
        await db.scalar(
            select(TenantSettings.default_currency).where(TenantSettings.tenant_id == tenant_id)
        )
        or "USD"
    )


async def _check_required(db, keys: list[str]) -> list[str]:
    allowed = set(D.BUILTIN_REQUIRED) | set(await L.lead_fields(db, D.ENTITY))
    unknown = [k for k in keys if k not in allowed]
    if unknown:
        raise Invalid(f"Unknown field: {unknown[0]}")
    return list(dict.fromkeys(keys))


def _check_kinds(kinds: list[str]) -> None:
    for kind, word in (("open", "an open"), ("won", "a won"), ("lost", "a lost")):
        if kind not in kinds:
            raise Invalid(f"A pipeline needs {word} stage")


async def _pipelines_out(db, pipelines: list[Pipeline]) -> list[PipelineOut]:
    ids = [p.id for p in pipelines]
    stages = (
        await db.scalars(
            select(PipelineStage)
            .where(PipelineStage.pipeline_id.in_(ids))
            .order_by(PipelineStage.position)
        )
    ).all()
    counts = dict(
        (
            await db.execute(
                select(Deal.pipeline_id, func.count())
                .where(Deal.pipeline_id.in_(ids))
                .group_by(Deal.pipeline_id)
            )
        ).all()
    )
    out = []
    for p in pipelines:
        item = PipelineOut.model_validate(p)
        item.stages = [PipelineStageOut.model_validate(s) for s in stages if s.pipeline_id == p.id]
        item.deal_count = counts.get(p.id, 0)
        out.append(item)
    return out


async def _one(db, pipeline: Pipeline) -> PipelineOut:
    await db.flush()
    await db.refresh(pipeline)
    return (await _pipelines_out(db, [pipeline]))[0]


async def _add_stage(db, pipeline: Pipeline, body: StageIn, position: int) -> PipelineStage:
    stage = PipelineStage(
        tenant_id=pipeline.tenant_id,
        pipeline_id=pipeline.id,
        name=body.name.strip(),
        kind=body.kind,
        probability=body.probability,
        colour=body.colour,
        required_fields=await _check_required(db, body.required_fields),
        position=position,
    )
    db.add(stage)
    return stage


# ---------- pipelines ----------
@router.get("/pipelines", response_model=list[PipelineOut])
async def list_pipelines(db: CrmDb, _: ActiveUser) -> list[PipelineOut]:
    rows = (await db.scalars(select(Pipeline).order_by(Pipeline.position))).all()
    return await _pipelines_out(db, list(rows))


@router.post("/pipelines", response_model=PipelineOut, status_code=status.HTTP_201_CREATED)
async def create_pipeline(body: PipelineIn, db: CrmDb, actor: Configurer) -> PipelineOut:
    name = body.name.strip()
    if await db.scalar(select(Pipeline.id).where(func.lower(Pipeline.name) == name.lower())):
        raise Conflict(f"There is already a pipeline called {name}")
    stages = body.stages or DEFAULT_STAGES
    _check_kinds([s.kind for s in stages])
    if len({s.name.strip().lower() for s in stages}) != len(stages):
        raise Invalid("Stage names must be different")
    pipeline = Pipeline(
        tenant_id=actor.user.tenant_id,
        name=name,
        currency=money.currency(body.currency or await _company_currency(db, actor.user.tenant_id)),
        position=await _next_position(db, Pipeline),
    )
    db.add(pipeline)
    await db.flush()
    for i, st in enumerate(stages):
        await _add_stage(db, pipeline, st, i)
    await audit(db, actor, "pipeline.created", "pipeline", pipeline.id, None, {"name": name})
    return await _one(db, pipeline)


@router.patch("/pipelines/{pipeline_id}", response_model=PipelineOut)
async def update_pipeline(
    pipeline_id: uuid.UUID, body: PipelinePatch, db: CrmDb, actor: Configurer
) -> PipelineOut:
    pipeline = await _get(db, Pipeline, pipeline_id, "Pipeline")
    before = {"name": pipeline.name, "currency": pipeline.currency, "active": pipeline.is_active}
    if body.name is not None and body.name.strip() != pipeline.name:
        name = body.name.strip()
        clash = await db.scalar(
            select(Pipeline.id).where(
                func.lower(Pipeline.name) == name.lower(), Pipeline.id != pipeline.id
            )
        )
        if clash:
            raise Conflict(f"There is already a pipeline called {name}")
        pipeline.name = name
    if body.currency is not None and money.currency(body.currency) != pipeline.currency:
        if await db.scalar(select(Deal.id).where(Deal.pipeline_id == pipeline.id).limit(1)):
            raise Conflict("This pipeline has deals; its currency cannot change")
        pipeline.currency = money.currency(body.currency)
    if body.is_active is False and pipeline.is_active:
        others = await db.scalar(
            select(Pipeline.id).where(Pipeline.is_active.is_(True), Pipeline.id != pipeline.id)
        )
        if not others:
            raise Conflict("Keep at least one pipeline switched on")
    if body.is_active is not None:
        pipeline.is_active = body.is_active
    after = {"name": pipeline.name, "currency": pipeline.currency, "active": pipeline.is_active}
    await audit(db, actor, "pipeline.updated", "pipeline", pipeline.id, before, after)
    return await _one(db, pipeline)


@router.delete("/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(pipeline_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    pipeline = await _get(db, Pipeline, pipeline_id, "Pipeline")
    if await db.scalar(select(Deal.id).where(Deal.pipeline_id == pipeline.id).limit(1)):
        raise Conflict("This pipeline has deals. Switch it off instead")
    if not await db.scalar(select(Pipeline.id).where(Pipeline.id != pipeline.id).limit(1)):
        raise Conflict("Keep at least one pipeline")
    await db.delete(pipeline)
    await audit(db, actor, "pipeline.deleted", "pipeline", pipeline_id, {"name": pipeline.name})


@router.put("/pipelines/order", response_model=list[PipelineOut])
async def order_pipelines(body: OrderIn, db: CrmDb, actor: Configurer) -> list[PipelineOut]:
    await _reorder(db, Pipeline, body.ids)
    return await list_pipelines(db, actor)


# ---------- stages ----------
@router.post(
    "/pipelines/{pipeline_id}/stages",
    response_model=PipelineOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_stage(
    pipeline_id: uuid.UUID, body: StageIn, db: CrmDb, actor: Configurer
) -> PipelineOut:
    pipeline = await _get(db, Pipeline, pipeline_id, "Pipeline")
    if await db.scalar(
        select(PipelineStage.id).where(
            PipelineStage.pipeline_id == pipeline.id,
            func.lower(PipelineStage.name) == body.name.strip().lower(),
        )
    ):
        raise Conflict(f"{pipeline.name} already has a stage called {body.name.strip()}")
    # New open stages go before the closed ones.
    stages = await D.stages_of(db, pipeline.id)
    position = len(stages)
    if body.kind == "open":
        position = next((s.position for s in stages if s.kind != "open"), len(stages))
        for s in stages:
            if s.position >= position:
                s.position += 1
    await _add_stage(db, pipeline, body, position)
    await audit(db, actor, "pipeline.stage_added", "pipeline", pipeline.id, None, body.model_dump())
    return await _one(db, pipeline)


@router.patch("/pipeline-stages/{stage_id}", response_model=PipelineOut)
async def update_stage(
    stage_id: uuid.UUID, body: StagePatch, db: CrmDb, actor: Configurer
) -> PipelineOut:
    stage = await _get(db, PipelineStage, stage_id, "Stage")
    pipeline = await db.get(Pipeline, stage.pipeline_id)
    before = _snap(stage, PipelineStageOut)
    if body.name is not None and body.name.strip() != stage.name:
        clash = await db.scalar(
            select(PipelineStage.id).where(
                PipelineStage.pipeline_id == pipeline.id,
                func.lower(PipelineStage.name) == body.name.strip().lower(),
                PipelineStage.id != stage.id,
            )
        )
        if clash:
            raise Conflict(f"{pipeline.name} already has a stage called {body.name.strip()}")
        stage.name = body.name.strip()
    if body.kind is not None and body.kind != stage.kind:
        if await db.scalar(select(Deal.id).where(Deal.stage_id == stage.id).limit(1)):
            raise Conflict("Deals are in this stage; move them before changing its kind")
        kinds = [s.kind for s in await D.stages_of(db, pipeline.id) if s.id != stage.id]
        _check_kinds([*kinds, body.kind])
        stage.kind = body.kind
    if body.probability is not None:
        stage.probability = body.probability
    if "colour" in body.model_fields_set:
        stage.colour = body.colour
    if body.required_fields is not None:
        stage.required_fields = await _check_required(db, body.required_fields)
    await audit(
        db, actor, "pipeline.stage_updated", "pipeline", pipeline.id, before,
        _snap(stage, PipelineStageOut),
    )  # fmt: skip
    return await _one(db, pipeline)


@router.delete("/pipeline-stages/{stage_id}", response_model=PipelineOut)
async def delete_stage(
    stage_id: uuid.UUID, db: CrmDb, actor: Configurer, move_to: uuid.UUID | None = None
) -> PipelineOut:
    """Deals in the stage move to `move_to`, a stage of the same pipeline and kind."""
    stage = await _get(db, PipelineStage, stage_id, "Stage")
    pipeline = await db.get(Pipeline, stage.pipeline_id)
    _check_kinds([s.kind for s in await D.stages_of(db, pipeline.id) if s.id != stage.id])
    if await db.scalar(select(Deal.id).where(Deal.stage_id == stage.id).limit(1)):
        if move_to is None:
            raise Conflict("Deals are in this stage. Choose where to move them")
        target = await D.get_stage(db, pipeline, move_to)
        if target.id == stage.id or target.kind != stage.kind:
            raise Invalid("Move them to another stage of the same kind")
        await db.execute(
            update(Deal)
            .where(Deal.stage_id == stage.id)
            .values(stage_id=target.id, version=Deal.version + 1)
        )
    await db.delete(stage)
    await audit(db, actor, "pipeline.stage_deleted", "pipeline", pipeline.id, {"stage": stage.name})
    return await _one(db, pipeline)


@router.put("/pipelines/{pipeline_id}/stages/order", response_model=PipelineOut)
async def order_stages(
    pipeline_id: uuid.UUID, body: OrderIn, db: CrmDb, actor: Configurer
) -> PipelineOut:
    pipeline = await _get(db, Pipeline, pipeline_id, "Pipeline")
    await _reorder(db, PipelineStage, body.ids, PipelineStage.pipeline_id == pipeline.id)
    return await _one(db, pipeline)


# ---------- lost reasons ----------
@router.get("/lost-reasons", response_model=list[LostReasonOut])
async def list_lost_reasons(db: CrmDb, _: ActiveUser) -> list[LostReason]:
    return list((await db.scalars(select(LostReason).order_by(LostReason.position))).all())


@router.post("/lost-reasons", response_model=LostReasonOut, status_code=status.HTTP_201_CREATED)
async def create_lost_reason(body: LostReasonIn, db: CrmDb, actor: Configurer) -> LostReason:
    name = body.name.strip()
    if await db.scalar(select(LostReason.id).where(func.lower(LostReason.name) == name.lower())):
        raise Conflict(f"'{name}' is already a reason")
    reason = LostReason(
        tenant_id=actor.user.tenant_id, name=name, position=await _next_position(db, LostReason)
    )
    db.add(reason)
    await db.flush()
    await audit(db, actor, "lost_reason.created", "lost_reason", reason.id, None, {"name": name})
    await db.refresh(reason)
    return reason


@router.patch("/lost-reasons/{reason_id}", response_model=LostReasonOut)
async def update_lost_reason(
    reason_id: uuid.UUID, body: LostReasonPatch, db: CrmDb, actor: Configurer
) -> LostReason:
    reason = await _get(db, LostReason, reason_id, "Reason")
    if body.name is not None and body.name.strip() != reason.name:
        name = body.name.strip()
        clash = await db.scalar(
            select(LostReason.id).where(
                func.lower(LostReason.name) == name.lower(), LostReason.id != reason.id
            )
        )
        if clash:
            raise Conflict(f"'{name}' is already a reason")
        reason.name = name
    if body.is_active is not None:
        reason.is_active = body.is_active
    await audit(
        db, actor, "lost_reason.updated", "lost_reason", reason.id, None,
        body.model_dump(exclude_unset=True),
    )  # fmt: skip
    await db.flush()
    await db.refresh(reason)
    return reason


@router.delete("/lost-reasons/{reason_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lost_reason(reason_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    reason = await _get(db, LostReason, reason_id, "Reason")
    if await db.scalar(select(Deal.id).where(Deal.lost_reason_id == reason.id).limit(1)):
        raise Conflict("Deals were lost for this reason. Switch it off instead")
    await db.delete(reason)
    await audit(db, actor, "lost_reason.deleted", "lost_reason", reason_id, {"name": reason.name})


@router.put("/lost-reasons/order", response_model=list[LostReasonOut])
async def order_lost_reasons(body: OrderIn, db: CrmDb, actor: Configurer) -> list[LostReason]:
    await _reorder(db, LostReason, body.ids)
    return await list_lost_reasons(db, actor)


# ---------- products ----------
@router.get("/products", response_model=list[ProductOut])
async def list_products(
    db: CrmDb, _: ActiveUser, active: bool | None = None, currency: str | None = None
) -> list[Product]:
    q = select(Product)
    if active is not None:
        q = q.where(Product.is_active.is_(active))
    if currency:
        q = q.where(Product.currency == currency.upper())
    return list((await db.scalars(q.order_by(func.lower(Product.name)))).all())


async def _code_free(db, code: str | None, own_id: uuid.UUID | None = None) -> str | None:
    code = (code or "").strip() or None
    if code:
        q = select(Product.id).where(func.lower(Product.code) == code.lower())
        if own_id:
            q = q.where(Product.id != own_id)
        if await db.scalar(q):
            raise Conflict(f"Another product has the code {code}")
    return code


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(body: ProductIn, db: CrmDb, actor: Configurer) -> Product:
    product = Product(
        tenant_id=actor.user.tenant_id,
        name=" ".join(body.name.split()),
        code=await _code_free(db, body.code),
        description=(body.description or "").strip() or None,
        price_minor=money.check_amount(body.price_minor, "Price"),
        currency=money.currency(body.currency or await _company_currency(db, actor.user.tenant_id)),
    )
    db.add(product)
    await db.flush()
    await audit(
        db, actor, "product.created", "product", product.id, None, _snap(product, ProductOut)
    )
    await db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID, body: ProductPatch, db: CrmDb, actor: Configurer
) -> Product:
    """Price changes apply to new deal lines only; existing lines keep their price."""
    product = await _get(db, Product, product_id, "Product")
    before = _snap(product, ProductOut)
    if body.name is not None:
        product.name = " ".join(body.name.split())
    if "code" in body.model_fields_set:
        product.code = await _code_free(db, body.code, product.id)
    if "description" in body.model_fields_set:
        product.description = (body.description or "").strip() or None
    if body.price_minor is not None:
        product.price_minor = money.check_amount(body.price_minor, "Price")
    if body.currency is not None and money.currency(body.currency) != product.currency:
        if await db.scalar(select(DealProduct.id).where(DealProduct.product_id == product.id)):
            raise Conflict("This product is on deals; its currency cannot change")
        product.currency = money.currency(body.currency)
    if body.is_active is not None:
        product.is_active = body.is_active
    await db.flush()
    await db.refresh(product)
    await audit(
        db, actor, "product.updated", "product", product.id, before, _snap(product, ProductOut)
    )
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    product = await _get(db, Product, product_id, "Product")
    if await db.scalar(select(DealProduct.id).where(DealProduct.product_id == product.id).limit(1)):
        raise Conflict("This product is on deals. Switch it off instead")
    await db.delete(product)
    await audit(db, actor, "product.deleted", "product", product_id, {"name": product.name})

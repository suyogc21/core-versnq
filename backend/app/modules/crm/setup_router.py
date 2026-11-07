"""CRM setup: stages, sources, custom fields and activity types. Everyone signed in can read
(forms need them); changes need crm.configure and are audited."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import fields as F
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import (
    Activity,
    ActivityType,
    CustomFieldDefinition,
    CustomFieldUniqueValue,
    Lead,
    LeadSource,
    LeadStage,
)

router = APIRouter(prefix="/api/v1", tags=["crm-setup"], dependencies=CRM)
Configurer = Annotated[CurrentUser, require("crm.configure")]
HEX = r"^#[0-9A-Fa-f]{6}$"


# ---------- schemas ----------
class StageOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    position: int
    is_open: bool
    is_unqualified: bool
    is_converted: bool
    is_system: bool
    colour: str | None
    required_fields: list[str]


class StageIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    is_open: bool = True
    is_unqualified: bool = False
    is_converted: bool = False
    colour: str | None = Field(default=None, pattern=HEX)
    required_fields: list[str] = []


class StagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_open: bool | None = None
    is_unqualified: bool | None = None
    is_converted: bool | None = None
    colour: str | None = Field(default=None, pattern=HEX)
    required_fields: list[str] | None = None


class SourceOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    position: int
    is_active: bool


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None


class FieldOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    entity: str
    key: str
    label: str
    type: str
    options: list[dict]
    required: bool
    is_unique: bool
    depends_on: str | None
    group_name: str | None
    position: int


class FieldIn(BaseModel):
    key: str = Field(pattern=F.KEY.pattern)
    label: str = Field(min_length=1, max_length=120)
    type: str
    options: list[dict] = []
    required: bool = False
    is_unique: bool = False
    depends_on: str | None = None
    group_name: str | None = Field(default=None, max_length=80)


class FieldPatch(BaseModel):
    """key, type and is_unique are fixed once created."""

    label: str | None = Field(default=None, min_length=1, max_length=120)
    options: list[dict] | None = None
    required: bool | None = None
    group_name: str | None = Field(default=None, max_length=80)


class TypeOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    key: str
    label: str
    is_system: bool
    is_loggable: bool
    is_active: bool
    fields: list[dict]
    icon: str | None
    position: int


class TypeIn(BaseModel):
    key: str = Field(pattern=F.KEY.pattern)
    label: str = Field(min_length=1, max_length=80)
    fields: list[dict] = []
    icon: str | None = Field(default=None, max_length=40)


class TypePatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    fields: list[dict] | None = None
    icon: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class OrderIn(BaseModel):
    ids: list[uuid.UUID]


# ---------- helpers ----------
def _snap(obj, cls) -> dict:
    return cls.model_validate(obj).model_dump(mode="json")


async def _get(db, model, item_id: uuid.UUID, what: str):
    item = await db.get(model, item_id)
    if item is None:
        raise NotFound(f"{what} not found")
    return item


async def _next_position(db, model) -> int:
    return (await db.scalar(select(func.coalesce(func.max(model.position), -1)))) + 1


async def _reorder(db, model, ids: list[uuid.UUID]) -> None:
    current = set((await db.scalars(select(model.id))).all())
    if set(ids) != current or len(ids) != len(current):
        raise Invalid("Send every item exactly once")
    for i, item_id in enumerate(ids):
        await db.execute(update(model).where(model.id == item_id).values(position=i))


async def _lead_field_keys(db) -> set[str]:
    rows = await db.scalars(
        select(CustomFieldDefinition.key).where(CustomFieldDefinition.entity == "lead")
    )
    return set(rows.all())


async def _check_stage(db, stage: LeadStage) -> None:
    if stage.is_unqualified and stage.is_open:
        raise Invalid("Only a closed stage can be an unqualified stage")
    if stage.is_converted and stage.is_open:
        raise Invalid("Only a closed stage can be a converted stage")
    known = F.BUILTIN_REQUIRABLE | await _lead_field_keys(db)
    unknown = [f for f in stage.required_fields if f not in known]
    if unknown:
        raise Invalid(f"Unknown required field: {unknown[0]}")
    stage.required_fields = sorted(set(stage.required_fields))


async def _keep_an_open_stage(db) -> None:
    if not await db.scalar(select(exists().where(LeadStage.is_open.is_(True)))):
        raise Conflict("Keep at least one open stage")


async def _flush_unique(db, message: str) -> None:
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict(message) from None


# ---------- stages ----------
@router.get("/lead-stages", response_model=list[StageOut])
async def list_stages(db: CrmDb, _: ActiveUser) -> list[LeadStage]:
    return list((await db.scalars(select(LeadStage).order_by(LeadStage.position))).all())


@router.post("/lead-stages", response_model=StageOut, status_code=status.HTTP_201_CREATED)
async def create_stage(body: StageIn, db: CrmDb, actor: Configurer) -> LeadStage:
    stage = LeadStage(
        tenant_id=actor.user.tenant_id,
        position=await _next_position(db, LeadStage),
        **body.model_dump(),
    )
    await _check_stage(db, stage)
    db.add(stage)
    await _flush_unique(db, "A stage with this name already exists")
    await audit(
        db, actor, "crm.stage_created", "lead_stage", stage.id, after=_snap(stage, StageOut)
    )
    return stage


@router.patch("/lead-stages/{stage_id}", response_model=StageOut)
async def update_stage(
    stage_id: uuid.UUID, body: StagePatch, db: CrmDb, actor: Configurer
) -> LeadStage:
    stage = await _get(db, LeadStage, stage_id, "Stage")
    before = _snap(stage, StageOut)
    changes = body.model_dump(exclude_unset=True)
    if stage.is_system and set(changes) & {"is_open", "is_unqualified", "is_converted"}:
        raise Conflict("The Invalid stage always stays closed and unqualified")
    for k, v in changes.items():
        setattr(stage, k, v)
    await _check_stage(db, stage)
    await _flush_unique(db, "A stage with this name already exists")
    await _keep_an_open_stage(db)
    if "is_open" in changes:  # leads copy is_open from their stage
        await db.execute(
            update(Lead).where(Lead.stage_id == stage.id).values(is_open=stage.is_open)
        )
    await audit(
        db, actor, "crm.stage_updated", "lead_stage", stage.id, before, _snap(stage, StageOut)
    )
    return stage


@router.delete("/lead-stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage(stage_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    stage = await _get(db, LeadStage, stage_id, "Stage")
    if stage.is_system:
        raise Conflict("The Invalid stage cannot be deleted")
    if await db.scalar(select(exists().where(Lead.stage_id == stage.id))):
        raise Conflict("Move the leads in this stage first")
    before = _snap(stage, StageOut)
    await db.delete(stage)
    await db.flush()
    await _keep_an_open_stage(db)
    await audit(db, actor, "crm.stage_deleted", "lead_stage", stage_id, before=before)


@router.put("/lead-stages/order", response_model=list[StageOut])
async def order_stages(body: OrderIn, db: CrmDb, actor: Configurer) -> list[LeadStage]:
    await _reorder(db, LeadStage, body.ids)
    await audit(
        db,
        actor,
        "crm.stages_reordered",
        "lead_stage",
        None,
        after={"ids": [str(i) for i in body.ids]},
    )
    return await list_stages(db, actor)


# ---------- sources ----------
@router.get("/lead-sources", response_model=list[SourceOut])
async def list_sources(db: CrmDb, _: ActiveUser) -> list[LeadSource]:
    return list((await db.scalars(select(LeadSource).order_by(LeadSource.position))).all())


@router.post("/lead-sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(body: SourceIn, db: CrmDb, actor: Configurer) -> LeadSource:
    source = LeadSource(
        tenant_id=actor.user.tenant_id,
        name=body.name.strip(),
        position=await _next_position(db, LeadSource),
    )
    db.add(source)
    await _flush_unique(db, "A source with this name already exists")
    await audit(
        db, actor, "crm.source_created", "lead_source", source.id, after=_snap(source, SourceOut)
    )
    return source


@router.patch("/lead-sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: uuid.UUID, body: SourcePatch, db: CrmDb, actor: Configurer
) -> LeadSource:
    source = await _get(db, LeadSource, source_id, "Source")
    before = _snap(source, SourceOut)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(source, k, v.strip() if isinstance(v, str) else v)
    await _flush_unique(db, "A source with this name already exists")
    await audit(
        db, actor, "crm.source_updated", "lead_source", source.id, before, _snap(source, SourceOut)
    )
    return source


@router.delete("/lead-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    source = await _get(db, LeadSource, source_id, "Source")
    if await db.scalar(select(exists().where(Lead.source_id == source.id))):
        raise Conflict("Leads use this source. Switch it off instead of deleting it")
    before = _snap(source, SourceOut)
    await db.delete(source)
    await audit(db, actor, "crm.source_deleted", "lead_source", source_id, before=before)


@router.put("/lead-sources/order", response_model=list[SourceOut])
async def order_sources(body: OrderIn, db: CrmDb, actor: Configurer) -> list[LeadSource]:
    await _reorder(db, LeadSource, body.ids)
    await audit(
        db,
        actor,
        "crm.sources_reordered",
        "lead_source",
        None,
        after={"ids": [str(i) for i in body.ids]},
    )
    return await list_sources(db, actor)


# ---------- custom fields ----------
async def _parent_options(
    db, entity: str, depends_on: str | None, own_key: str
) -> list[dict] | None:
    if depends_on is None:
        return None
    if depends_on == own_key:
        raise Invalid("A field cannot depend on itself")
    parent = await db.scalar(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity == entity, CustomFieldDefinition.key == depends_on
        )
    )
    if parent is None or parent.type != "select":
        raise Invalid("A field can only depend on an existing single-choice dropdown")
    if parent.depends_on == own_key:
        raise Invalid("Two fields cannot depend on each other")
    return parent.options


@router.get("/custom-fields", response_model=list[FieldOut])
async def list_fields(
    db: CrmDb, _: ActiveUser, entity: Literal["lead"] = "lead"
) -> list[CustomFieldDefinition]:
    q = select(CustomFieldDefinition).where(CustomFieldDefinition.entity == entity)
    return list((await db.scalars(q.order_by(CustomFieldDefinition.position))).all())


@router.post("/custom-fields", response_model=FieldOut, status_code=status.HTTP_201_CREATED)
async def create_field(
    body: FieldIn, db: CrmDb, actor: Configurer, entity: Literal["lead"] = "lead"
) -> CustomFieldDefinition:
    if body.type not in F.TYPES:
        raise Invalid(f"Unknown field type: {body.type}")
    if body.key in F.RESERVED_KEYS:
        raise Invalid(f"'{body.key}' is a built-in field; choose another key")
    if body.is_unique and body.type not in F.UNIQUE_TYPES:
        raise Invalid("Only text, number, email, phone and link fields can be unique")
    if body.depends_on and body.type not in F.CHOICE_TYPES:
        raise Invalid("Only dropdown fields can depend on another field")
    options = F.check_options(body.type, body.options)
    F.check_dependency(options, await _parent_options(db, entity, body.depends_on, body.key))
    field = CustomFieldDefinition(
        tenant_id=actor.user.tenant_id,
        entity=entity,
        position=await _next_position(db, CustomFieldDefinition),
        **(body.model_dump() | {"options": options}),
    )
    db.add(field)
    await _flush_unique(db, "A field with this key already exists")
    await audit(
        db, actor, "crm.field_created", "custom_field", field.id, after=_snap(field, FieldOut)
    )
    return field


@router.patch("/custom-fields/{field_id}", response_model=FieldOut)
async def update_field(
    field_id: uuid.UUID, body: FieldPatch, db: CrmDb, actor: Configurer
) -> CustomFieldDefinition:
    field = await _get(db, CustomFieldDefinition, field_id, "Field")
    before = _snap(field, FieldOut)
    changes = body.model_dump(exclude_unset=True)
    if "options" in changes:
        options = F.check_options(field.type, changes["options"])
        F.check_dependency(
            options, await _parent_options(db, field.entity, field.depends_on, field.key)
        )
        changes["options"] = options
        # Children must still point at options that exist.
        children = await db.scalars(
            select(CustomFieldDefinition).where(
                CustomFieldDefinition.entity == field.entity,
                CustomFieldDefinition.depends_on == field.key,
            )
        )
        for child in children.all():
            F.check_dependency(child.options, options)
    for k, v in changes.items():
        setattr(field, k, v)
    await audit(
        db, actor, "crm.field_updated", "custom_field", field.id, before, _snap(field, FieldOut)
    )
    return field


@router.delete("/custom-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(field_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    """Delete is permanent: the field's values are removed from every lead."""
    field = await _get(db, CustomFieldDefinition, field_id, "Field")
    child = await db.scalar(
        select(CustomFieldDefinition.label).where(
            CustomFieldDefinition.entity == field.entity,
            CustomFieldDefinition.depends_on == field.key,
        )
    )
    if child:
        raise Conflict(f"'{child}' depends on this field; delete or unlink it first")
    stage = await db.scalar(
        select(LeadStage.name).where(LeadStage.required_fields.contains([field.key]))
    )
    if stage:
        raise Conflict(f"The stage '{stage}' requires this field")
    before = _snap(field, FieldOut)
    await db.execute(
        update(Lead)
        .where(Lead.custom_fields.has_key(field.key))
        .values(custom_fields=Lead.custom_fields - field.key)
    )
    await db.execute(
        delete(CustomFieldUniqueValue).where(
            CustomFieldUniqueValue.entity == field.entity,
            CustomFieldUniqueValue.field_key == field.key,
        )
    )
    await db.delete(field)
    await audit(db, actor, "crm.field_deleted", "custom_field", field_id, before=before)


@router.put("/custom-fields/order", response_model=list[FieldOut])
async def order_fields(body: OrderIn, db: CrmDb, actor: Configurer) -> list[CustomFieldDefinition]:
    await _reorder(db, CustomFieldDefinition, body.ids)
    await audit(
        db,
        actor,
        "crm.fields_reordered",
        "custom_field",
        None,
        after={"ids": [str(i) for i in body.ids]},
    )
    return await list_fields(db, actor)


# ---------- activity types ----------
@router.get("/activity-types", response_model=list[TypeOut])
async def list_types(db: CrmDb, _: ActiveUser) -> list[ActivityType]:
    return list((await db.scalars(select(ActivityType).order_by(ActivityType.position))).all())


@router.post("/activity-types", response_model=TypeOut, status_code=status.HTTP_201_CREATED)
async def create_type(body: TypeIn, db: CrmDb, actor: Configurer) -> ActivityType:
    kind = ActivityType(
        tenant_id=actor.user.tenant_id,
        key=body.key,
        label=body.label,
        icon=body.icon,
        fields=F.check_field_list(body.fields),
        position=await _next_position(db, ActivityType),
    )
    db.add(kind)
    await _flush_unique(db, "An activity type with this key already exists")
    await audit(
        db, actor, "crm.activity_type_created", "activity_type", kind.id, after=_snap(kind, TypeOut)
    )
    return kind


@router.patch("/activity-types/{type_id}", response_model=TypeOut)
async def update_type(
    type_id: uuid.UUID, body: TypePatch, db: CrmDb, actor: Configurer
) -> ActivityType:
    kind = await _get(db, ActivityType, type_id, "Activity type")
    before = _snap(kind, TypeOut)
    changes = body.model_dump(exclude_unset=True)
    if kind.is_system:
        if "is_active" in changes:
            raise Conflict("Built-in activity types cannot be switched off")
        if "fields" in changes and kind.key == "call":
            # Calls always keep a required outcome; only its options are editable.
            new = F.check_field_list(changes["fields"])
            outcome = next((f for f in new if f["key"] == "disposition"), None)
            if not outcome or outcome["type"] != "select" or not outcome["required"]:
                raise Invalid("Calls must keep a required 'disposition' dropdown")
            changes["fields"] = new
        elif "fields" in changes:
            raise Conflict("This built-in type has no editable fields")
    elif "fields" in changes:
        changes["fields"] = F.check_field_list(changes["fields"])
    for k, v in changes.items():
        setattr(kind, k, v)
    await audit(
        db,
        actor,
        "crm.activity_type_updated",
        "activity_type",
        kind.id,
        before,
        _snap(kind, TypeOut),
    )
    return kind


@router.delete("/activity-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_type(type_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    kind = await _get(db, ActivityType, type_id, "Activity type")
    if kind.is_system:
        raise Conflict("Built-in activity types cannot be deleted")
    if await db.scalar(select(exists().where(Activity.type_key == kind.key))):
        raise Conflict("This type is on lead timelines. Switch it off instead of deleting it")
    before = _snap(kind, TypeOut)
    await db.delete(kind)
    await audit(db, actor, "crm.activity_type_deleted", "activity_type", type_id, before=before)

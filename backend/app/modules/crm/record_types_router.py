"""Setting up record types: the types, their stages, who may do what (per role), link types.
Changes need crm.configure; everyone signed in can read the types they may view."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import records as RC
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.leads import lead_fields
from app.modules.crm.models import (
    CustomFieldDefinition,
    CustomFieldUniqueValue,
    Link,
    LinkType,
    Record,
    RecordType,
    RecordTypeAccess,
    RecordTypeStage,
)
from app.modules.roles.models import Role

router = APIRouter(prefix="/api/v1", tags=["record-types"], dependencies=CRM)
Configurer = Annotated[CurrentUser, require("crm.configure")]
TYPE_KEY = r"^[a-z][a-z0-9_]{1,39}$"
# Built-in kinds (and the ones coming next) keep their own names.
RESERVED_TYPE_KEYS = {
    "lead",
    "leads",
    "contact",
    "deal",
    "deals",
    "customer",
    "customers",
    "task",
    "user",
}


class AccessOut(BaseModel):
    view: bool
    create: bool
    edit: bool
    delete: bool
    scope: str


class RecordTypeOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    key: str
    singular: str
    plural: str
    icon: str | None
    has_owner: bool
    has_stages: bool
    is_active: bool
    position: int
    my_access: AccessOut | None = None


class RecordTypeIn(BaseModel):
    key: str = Field(pattern=TYPE_KEY)
    singular: str = Field(min_length=1, max_length=60)
    plural: str = Field(min_length=1, max_length=60)
    icon: str | None = Field(default=None, max_length=40)
    has_owner: bool = True
    has_stages: bool = False


class RecordTypePatch(BaseModel):
    singular: str | None = Field(default=None, min_length=1, max_length=60)
    plural: str | None = Field(default=None, min_length=1, max_length=60)
    icon: str | None = Field(default=None, max_length=40)
    has_owner: bool | None = None
    has_stages: bool | None = None
    is_active: bool | None = None


class OrderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def _access_out(a: RC.Access) -> AccessOut:
    return AccessOut(view=a.view, create=a.create, edit=a.edit, delete=a.delete, scope=a.scope)


async def _flush(db, message: str) -> None:
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict(message) from None


# ---------- types ----------
@router.get("/record-types", response_model=list[RecordTypeOut])
async def list_record_types(
    db: CrmDb, actor: ActiveUser, include_hidden: bool = False
) -> list[RecordTypeOut]:
    """The types you may view (for the sidebar). Admins (crm.configure) can ask for all,
    including switched-off ones."""
    rows = (await db.scalars(select(RecordType).order_by(RecordType.position))).all()
    configurer = "crm.configure" in actor.permissions or actor.role.key == "owner"
    out = []
    for t in rows:
        acc = await RC.access_for(db, actor, t)
        if include_hidden and configurer:
            pass
        elif not (t.is_active and acc.view):
            continue
        item = RecordTypeOut.model_validate(t)
        item.my_access = _access_out(acc)
        out.append(item)
    return out


@router.post("/record-types", response_model=RecordTypeOut, status_code=status.HTTP_201_CREATED)
async def create_record_type(body: RecordTypeIn, db: CrmDb, actor: Configurer) -> RecordTypeOut:
    if body.key in RESERVED_TYPE_KEYS:
        raise Invalid(f"'{body.key}' is a built-in name; choose another key")
    position = await db.scalar(select(func.coalesce(func.max(RecordType.position), -1))) + 1
    rtype = RecordType(
        tenant_id=actor.user.tenant_id,
        key=body.key,
        singular=body.singular.strip(),
        plural=body.plural.strip(),
        icon=body.icon,
        has_owner=body.has_owner,
        has_stages=body.has_stages,
        position=position,
    )
    db.add(rtype)
    await _flush(db, "A record type with this key or name already exists")
    if body.has_stages:
        await _default_stages(db, rtype)
    await RC.seed_access(db, rtype)
    await db.flush()
    await audit(db, actor, "record_type.created", "record_type", rtype.id, None, body.model_dump())
    await db.refresh(rtype)
    item = RecordTypeOut.model_validate(rtype)
    item.my_access = _access_out(await RC.access_for(db, actor, rtype))
    return item


async def _default_stages(db, rtype: RecordType) -> None:
    for i, (name, is_open) in enumerate((("Open", True), ("Closed", False))):
        db.add(
            RecordTypeStage(
                tenant_id=rtype.tenant_id,
                record_type_id=rtype.id,
                name=name,
                position=i,
                is_open=is_open,
                required_fields=[],
            )
        )


@router.patch("/record-types/{type_id}", response_model=RecordTypeOut)
async def update_record_type(
    type_id: uuid.UUID, body: RecordTypePatch, db: CrmDb, actor: Configurer
) -> RecordTypeOut:
    rtype = await RC.get_type(db, type_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is not None or key == "icon":
            setattr(rtype, key, value.strip() if isinstance(value, str) else value)
    if changes.get("has_stages"):
        has_any = await db.scalar(
            select(RecordTypeStage.id).where(RecordTypeStage.record_type_id == rtype.id).limit(1)
        )
        if not has_any:
            await _default_stages(db, rtype)
    await _flush(db, "A record type with this name already exists")
    await audit(db, actor, "record_type.updated", "record_type", rtype.id, None, changes)
    await db.refresh(rtype)
    item = RecordTypeOut.model_validate(rtype)
    item.my_access = _access_out(await RC.access_for(db, actor, rtype))
    return item


@router.delete("/record-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record_type(type_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    """Only an unused type can be deleted; one with records can be switched off instead."""
    rtype = await RC.get_type(db, type_id)
    if await RC.count_records(db, rtype):
        raise Conflict(f"There are {rtype.plural.lower()} of this type. Switch it off instead")
    entity = rtype.entity
    await db.execute(delete(CustomFieldUniqueValue).where(CustomFieldUniqueValue.entity == entity))
    await db.execute(delete(CustomFieldDefinition).where(CustomFieldDefinition.entity == entity))
    await db.delete(rtype)
    await audit(db, actor, "record_type.deleted", "record_type", type_id, {"key": rtype.key})


@router.put("/record-types/order", status_code=status.HTTP_204_NO_CONTENT)
async def order_record_types(body: OrderIn, db: CrmDb, actor: Configurer) -> None:
    types = {t.id: t for t in (await db.scalars(select(RecordType))).all()}
    if set(body.ids) != set(types) or len(body.ids) != len(types):
        raise Invalid("Send every record type once")
    for i, type_id in enumerate(body.ids):
        types[type_id].position = i


# ---------- stages ----------
class RecordStageOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    position: int
    is_open: bool
    colour: str | None
    required_fields: list[str]


class RecordStageIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    is_open: bool = True
    colour: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    required_fields: list[str] = Field(default=[], max_length=50)


class RecordStagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_open: bool | None = None
    colour: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    required_fields: list[str] | None = Field(default=None, max_length=50)


async def _stage_rules(db, rtype: RecordType, stage: RecordTypeStage) -> None:
    known = {"owner"} | set(await lead_fields(db, rtype.entity))
    unknown = [f for f in stage.required_fields if f not in known]
    if unknown:
        raise Invalid(f"Unknown required field: {unknown[0]}")
    stage.required_fields = sorted(set(stage.required_fields))


async def _keep_open(db, rtype: RecordType) -> None:
    await db.flush()
    any_open = await db.scalar(
        select(RecordTypeStage.id).where(
            RecordTypeStage.record_type_id == rtype.id, RecordTypeStage.is_open.is_(True)
        )
    )
    if not any_open:
        raise Conflict("Keep at least one open stage")


@router.get("/record-types/{type_id}/stages", response_model=list[RecordStageOut])
async def list_record_stages(type_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> list:
    rtype = await RC.get_type(db, type_id)
    rows = await db.scalars(
        select(RecordTypeStage)
        .where(RecordTypeStage.record_type_id == rtype.id)
        .order_by(RecordTypeStage.position)
    )
    return list(rows.all())


@router.post(
    "/record-types/{type_id}/stages",
    response_model=RecordStageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_record_stage(
    type_id: uuid.UUID, body: RecordStageIn, db: CrmDb, actor: Configurer
) -> RecordTypeStage:
    rtype = await RC.get_type(db, type_id)
    position = await db.scalar(
        select(func.coalesce(func.max(RecordTypeStage.position), -1)).where(
            RecordTypeStage.record_type_id == rtype.id
        )
    )
    stage = RecordTypeStage(
        tenant_id=rtype.tenant_id,
        record_type_id=rtype.id,
        position=position + 1,
        **body.model_dump() | {"name": body.name.strip()},
    )
    await _stage_rules(db, rtype, stage)
    db.add(stage)
    await _flush(db, "A stage with this name already exists")
    await audit(
        db, actor, "record_stage.created", "record_stage", stage.id, None, body.model_dump()
    )
    return stage


async def _stage(db, type_id: uuid.UUID, stage_id: uuid.UUID) -> tuple[RecordType, RecordTypeStage]:
    rtype = await RC.get_type(db, type_id)
    stage = await db.get(RecordTypeStage, stage_id)
    if stage is None or stage.record_type_id != rtype.id:
        raise NotFound("Stage not found")
    return rtype, stage


@router.patch("/record-types/{type_id}/stages/{stage_id}", response_model=RecordStageOut)
async def update_record_stage(
    type_id: uuid.UUID, stage_id: uuid.UUID, body: RecordStagePatch, db: CrmDb, actor: Configurer
) -> RecordTypeStage:
    rtype, stage = await _stage(db, type_id, stage_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is not None or key == "colour":
            setattr(
                stage, key, value.strip() if isinstance(value, str) and key == "name" else value
            )
    await _stage_rules(db, rtype, stage)
    await _flush(db, "A stage with this name already exists")
    await _keep_open(db, rtype)
    await audit(db, actor, "record_stage.updated", "record_stage", stage.id, None, changes)
    return stage


@router.delete("/record-types/{type_id}/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record_stage(
    type_id: uuid.UUID, stage_id: uuid.UUID, db: CrmDb, actor: Configurer
) -> None:
    rtype, stage = await _stage(db, type_id, stage_id)
    used = await db.scalar(select(Record.id).where(Record.stage_id == stage.id).limit(1))
    if used:
        raise Conflict("Records are in this stage; move them first")
    await db.delete(stage)
    await _keep_open(db, rtype)
    await audit(db, actor, "record_stage.deleted", "record_stage", stage_id, {"name": stage.name})


@router.put("/record-types/{type_id}/stages/order", status_code=status.HTTP_204_NO_CONTENT)
async def order_record_stages(
    type_id: uuid.UUID, body: OrderIn, db: CrmDb, actor: Configurer
) -> None:
    rtype = await RC.get_type(db, type_id)
    stages = {
        s.id: s
        for s in (
            await db.scalars(
                select(RecordTypeStage).where(RecordTypeStage.record_type_id == rtype.id)
            )
        ).all()
    }
    if set(body.ids) != set(stages) or len(body.ids) != len(stages):
        raise Invalid("Send every stage once")
    for i, stage_id in enumerate(body.ids):
        stages[stage_id].position = i


# ---------- access per role ----------
class RoleAccess(BaseModel):
    role_id: uuid.UUID
    role_name: str | None = None
    view: bool
    create: bool
    edit: bool
    delete: bool
    scope: Literal["own", "team", "all"]

    @model_validator(mode="after")
    def _view_needed(self):
        if (self.create or self.edit or self.delete) and not self.view:
            raise ValueError("A role that can add, edit or delete must also be able to view")
        return self


@router.get("/record-types/{type_id}/access", response_model=list[RoleAccess])
async def get_access(type_id: uuid.UUID, db: CrmDb, actor: Configurer) -> list[RoleAccess]:
    """Every role except the Owner (who can always do everything)."""
    rtype = await RC.get_type(db, type_id)
    rows = {
        a.role_id: a
        for a in (
            await db.scalars(
                select(RecordTypeAccess).where(RecordTypeAccess.record_type_id == rtype.id)
            )
        ).all()
    }
    out = []
    for role in (await db.scalars(select(Role).order_by(Role.created_at))).all():
        if role.key == "owner":
            continue
        a = rows.get(role.id)
        out.append(
            RoleAccess(
                role_id=role.id,
                role_name=role.name,
                view=bool(a and a.can_view),
                create=bool(a and a.can_create),
                edit=bool(a and a.can_edit),
                delete=bool(a and a.can_delete),
                scope=a.scope if a else "own",
            )
        )
    return out


@router.put("/record-types/{type_id}/access", response_model=list[RoleAccess])
async def set_access(
    type_id: uuid.UUID, body: list[RoleAccess], db: CrmDb, actor: Configurer
) -> list[RoleAccess]:
    rtype = await RC.get_type(db, type_id)
    roles = {r.id: r for r in (await db.scalars(select(Role))).all()}
    before = await get_access(type_id, db, actor)
    for item in body:
        role = roles.get(item.role_id)
        if role is None or role.key == "owner":
            raise Invalid("Choose roles from the list (the Owner can always do everything)")
        row = await db.scalar(
            select(RecordTypeAccess).where(
                RecordTypeAccess.role_id == role.id, RecordTypeAccess.record_type_id == rtype.id
            )
        )
        if row is None:
            row = RecordTypeAccess(
                tenant_id=rtype.tenant_id, role_id=role.id, record_type_id=rtype.id
            )
            db.add(row)
        row.can_view, row.can_create, row.can_edit, row.can_delete = (
            item.view,
            item.create,
            item.edit,
            item.delete,
        )
        row.scope = item.scope
    await db.flush()
    after = await get_access(type_id, db, actor)
    await audit(
        db,
        actor,
        "record_type.access_changed",
        "record_type",
        rtype.id,
        {"access": [a.model_dump(mode="json") for a in before]},
        {"access": [a.model_dump(mode="json") for a in after]},
    )
    return after


# ---------- link types ----------
Kind = Literal["lead", "deal", "record"]


class LinkTypeOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    from_kind: str
    to_kind: str
    from_type_id: uuid.UUID | None
    to_type_id: uuid.UUID | None
    label: str
    inverse_label: str
    many_to: bool
    many_from: bool
    is_active: bool
    position: int
    created_at: datetime


class LinkTypeIn(BaseModel):
    from_kind: Kind | None = None  # default: "record" when a type is given, else "lead"
    to_kind: Kind | None = None
    from_type_id: uuid.UUID | None = None  # the record type, for kind "record"
    to_type_id: uuid.UUID | None = None
    label: str = Field(min_length=1, max_length=80)
    inverse_label: str = Field(min_length=1, max_length=80)
    many_to: bool = True
    many_from: bool = True


class LinkTypePatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    inverse_label: str | None = Field(default=None, min_length=1, max_length=80)
    many_to: bool | None = None
    many_from: bool | None = None
    is_active: bool | None = None


@router.get("/link-types", response_model=list[LinkTypeOut])
async def list_link_types(db: CrmDb, actor: ActiveUser) -> list[LinkType]:
    return list((await db.scalars(select(LinkType).order_by(LinkType.position))).all())


@router.post("/link-types", response_model=LinkTypeOut, status_code=status.HTTP_201_CREATED)
async def create_link_type(body: LinkTypeIn, db: CrmDb, actor: Configurer) -> LinkType:
    for side in ("from", "to"):
        type_id = getattr(body, f"{side}_type_id")
        kind = getattr(body, f"{side}_kind") or ("record" if type_id else "lead")
        if (kind == "record") != (type_id is not None):
            raise Invalid("Choose a record type for record links, and only for them")
        if type_id:
            await RC.get_type(db, type_id)
        setattr(body, f"{side}_kind", kind)
    position = await db.scalar(select(func.coalesce(func.max(LinkType.position), -1))) + 1
    lt = LinkType(
        tenant_id=actor.user.tenant_id,
        position=position,
        **body.model_dump()
        | {"label": body.label.strip(), "inverse_label": body.inverse_label.strip()},
    )
    db.add(lt)
    await db.flush()
    await audit(
        db, actor, "link_type.created", "link_type", lt.id, None, body.model_dump(mode="json")
    )
    await db.refresh(lt)
    return lt


@router.patch("/link-types/{link_type_id}", response_model=LinkTypeOut)
async def update_link_type(
    link_type_id: uuid.UUID, body: LinkTypePatch, db: CrmDb, actor: Configurer
) -> LinkType:
    lt = await db.get(LinkType, link_type_id)
    if lt is None:
        raise NotFound("Link type not found")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    # Tightening to 'only one' must not contradict links that already exist.
    if changes.get("many_to") is False and lt.many_to:
        await _check_single(db, lt, "from")
    if changes.get("many_from") is False and lt.many_from:
        await _check_single(db, lt, "to")
    for key, value in changes.items():
        setattr(lt, key, value.strip() if isinstance(value, str) else value)
    await audit(db, actor, "link_type.updated", "link_type", lt.id, None, changes)
    await db.flush()
    await db.refresh(lt)
    return lt


async def _check_single(db, lt: LinkType, side: str) -> None:
    cols = [getattr(Link, f"{side}_{k}_id") for k in RC.KINDS]
    clash = await db.scalar(
        select(func.count()).select_from(
            select(*cols)
            .where(Link.link_type_id == lt.id)
            .group_by(*cols)
            .having(func.count() > 1)
            .subquery()
        )
    )
    if clash:
        raise Conflict("Some already have more than one of these links; remove the extras first")


@router.delete("/link-types/{link_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link_type(link_type_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    lt = await db.get(LinkType, link_type_id)
    if lt is None:
        raise NotFound("Link type not found")
    used = await db.scalar(select(Link.id).where(Link.link_type_id == lt.id).limit(1))
    if used:
        raise Conflict("Things are linked this way. Switch it off instead")
    await db.delete(lt)
    await audit(db, actor, "link_type.deleted", "link_type", link_type_id, {"label": lt.label})

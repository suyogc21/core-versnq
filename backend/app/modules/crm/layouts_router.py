"""Page layouts and field access (step 8, Decision log #38).

`GET /layouts/{entity}` is read by every record page: the company's layout (or today's page
when none is saved), the fields it can hold, and what the reader may do with each field.
Changing a layout needs crm.configure; changing field access needs roles.manage.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import access as A
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import CustomFieldDefinition, FieldPermission, RecordLayout, RecordType
from app.modules.roles.models import Role

router = APIRouter(prefix="/api/v1", tags=["layouts"], dependencies=CRM)
Configurer = Annotated[CurrentUser, require("crm.configure")]
RoleManager = Annotated[CurrentUser, require("roles.manage")]

MAX_SECTIONS = 20
MAX_HIGHLIGHTS = 4
# built-in lead fields a layout can place (name, owner, stage, source, phone and email have
# fixed places on the page)
LEAD_PLACEABLE = ["org_name", "website", "industry", "employee_range", "city", "region",
                  "country_code", "preferred_language"]  # fmt: skip


async def _entity(db, entity: str) -> str:
    if entity in ("lead", "deal", "customer"):
        return entity
    if entity.startswith("rt:") and await db.scalar(
        select(RecordType.id).where(RecordType.key == entity[3:])
    ):
        return entity
    raise NotFound("Unknown kind of record")


class LayoutField(BaseModel):
    key: str  # built-in name, or "cf.<key>"
    label: str
    builtin: bool
    type: str | None = None  # custom field type
    required: bool = False


class Section(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    fields: list[str] = Field(max_length=200)


class LayoutIn(BaseModel):
    sections: list[Section] = Field(max_length=MAX_SECTIONS)
    highlights: list[str] = Field(default=[], max_length=MAX_HIGHLIGHTS)
    add_form: list[str] = Field(default=[], max_length=200)


class LayoutOut(LayoutIn):
    entity: str
    is_default: bool
    fields: list[LayoutField]
    my_access: dict[str, Literal["view", "hidden"]]  # missing = edit
    updated_at: datetime | None = None


async def _catalogue(db, entity: str) -> tuple[list[LayoutField], list[CustomFieldDefinition]]:
    defs = list(
        (
            await db.scalars(
                select(CustomFieldDefinition)
                .where(CustomFieldDefinition.entity == entity)
                .order_by(CustomFieldDefinition.position)
            )
        ).all()
    )
    out = []
    if entity == "lead":
        labels = A.builtins("lead")
        out += [LayoutField(key=k, label=labels[k][0], builtin=True) for k in LEAD_PLACEABLE]
    out += [
        LayoutField(
            key=f"cf.{d.key}", label=d.label, builtin=False, type=d.type, required=d.required
        )
        for d in defs
    ]
    return out, defs


def _default(entity: str, defs: list[CustomFieldDefinition]) -> LayoutIn:
    """Today's page: built-ins first, then custom fields grouped as they are now."""
    groups: dict[str, list[str]] = {}
    for d in defs:
        groups.setdefault(d.group_name or "Details", []).append(f"cf.{d.key}")
    if entity == "lead":
        groups = {"Details": ["org_name", "website", "industry", "city", "country_code"]
                  + groups.pop("Details", [])} | groups  # fmt: skip
    sections = [Section(name=n, fields=f) for n, f in groups.items()]
    add_form = [f"cf.{d.key}" for d in defs if d.type != "calculated"]
    return LayoutIn(sections=sections, highlights=[], add_form=add_form)


def _clean(layout: LayoutIn, known: set[str]) -> LayoutIn:
    """Drop fields that no longer exist (deleted since the layout was saved)."""
    return LayoutIn(
        sections=[
            Section(name=s.name, fields=[f for f in s.fields if f in known])
            for s in layout.sections
        ],
        highlights=[f for f in layout.highlights if f in known],
        add_form=[f for f in layout.add_form if f in known],
    )


@router.get("/layouts/{entity}", response_model=LayoutOut)
async def get_layout(entity: str, db: CrmDb, actor: ActiveUser) -> LayoutOut:
    entity = await _entity(db, entity)
    catalogue, defs = await _catalogue(db, entity)
    known = {f.key for f in catalogue}
    row = await db.scalar(select(RecordLayout).where(RecordLayout.entity == entity))
    layout = (
        _clean(
            LayoutIn(sections=row.sections, highlights=row.highlights, add_form=row.add_form), known
        )
        if row
        else _default(entity, defs)
    )
    rules = await A.rules(db, actor, entity)
    return LayoutOut(
        **layout.model_dump(),
        entity=entity,
        is_default=row is None,
        fields=catalogue,
        my_access=rules.access,
        updated_at=row.updated_at if row else None,
    )


@router.put("/layouts/{entity}", response_model=LayoutOut)
async def save_layout(entity: str, body: LayoutIn, db: CrmDb, actor: Configurer) -> LayoutOut:
    entity = await _entity(db, entity)
    catalogue, defs = await _catalogue(db, entity)
    known = {f.key for f in catalogue}
    placed: list[str] = []
    names: set[str] = set()
    for s in body.sections:
        name = " ".join(s.name.split())
        if name.lower() in names:
            raise Invalid(f"Two sections are called {name}")
        names.add(name.lower())
        s.name = name
        for f in s.fields:
            if f not in known:
                raise Invalid(f"Unknown field: {f}")
            if f in placed:
                raise Invalid("A field can be in only one section")
            placed.append(f)
    for f in body.highlights:
        if f not in known:
            raise Invalid(f"Unknown field: {f}")
    if len(set(body.highlights)) != len(body.highlights):
        raise Invalid("Each highlight once")
    for f in body.add_form:
        if f not in known:
            raise Invalid(f"Unknown field: {f}")
    required = {f"cf.{d.key}" for d in defs if d.required}
    add_form = list(dict.fromkeys(body.add_form + sorted(required - set(body.add_form))))
    row = await db.scalar(select(RecordLayout).where(RecordLayout.entity == entity))
    data = {
        "sections": [s.model_dump() for s in body.sections],
        "highlights": body.highlights,
        "add_form": add_form,
        "updated_by_user_id": actor.user.id,
    }
    if row is None:
        row = RecordLayout(id=uuid.uuid4(), tenant_id=actor.user.tenant_id, entity=entity, **data)
        db.add(row)
    else:
        for k, v in data.items():
            setattr(row, k, v)
    await audit(db, actor, "layout.saved", "layout", row.id, None, {"entity": entity})
    await db.flush()
    return await get_layout(entity, db, actor)


@router.delete("/layouts/{entity}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_layout(entity: str, db: CrmDb, actor: Configurer) -> None:
    """Back to the default page."""
    entity = await _entity(db, entity)
    await db.execute(delete(RecordLayout).where(RecordLayout.entity == entity))
    await audit(db, actor, "layout.reset", "layout", None, None, {"entity": entity})


# ---------- field access ----------
class AccessField(BaseModel):
    key: str
    label: str
    builtin: bool
    choices: list[Literal["edit", "view", "hidden"]]


class AccessRole(BaseModel):
    id: uuid.UUID
    name: str
    locked: bool  # Owner and Admin always edit everything
    access: dict[str, Literal["view", "hidden"]]


class AccessOut(BaseModel):
    entity: str
    fields: list[AccessField]
    roles: list[AccessRole]


class AccessIn(BaseModel):
    access: dict[str, Literal["edit", "view", "hidden"]] = Field(max_length=300)


async def _access_fields(db, entity: str) -> list[AccessField]:
    out = [
        AccessField(key=k, label=label, builtin=True, choices=list(A.allowed_access(entity, k)))
        for k, (label, _) in A.builtins(entity).items()
    ]
    defs = (
        await db.scalars(
            select(CustomFieldDefinition)
            .where(CustomFieldDefinition.entity == entity)
            .order_by(CustomFieldDefinition.position)
        )
    ).all()
    out += [
        AccessField(
            key=f"cf.{d.key}", label=d.label, builtin=False, choices=["edit", "view", "hidden"]
        )
        for d in defs
    ]
    return out


@router.get("/field-access/{entity}", response_model=AccessOut)
async def get_access(entity: str, db: CrmDb, actor: RoleManager) -> AccessOut:
    entity = await _entity(db, entity)
    roles = (await db.scalars(select(Role).order_by(Role.is_system.desc(), Role.name))).all()
    out = []
    for r in roles:
        locked = r.key in A.UNRESTRICTED_ROLES
        out.append(
            AccessRole(
                id=r.id,
                name=r.name,
                locked=locked,
                access={} if locked else await A.for_role(db, r.id, entity),
            )  # fmt: skip
        )
    return AccessOut(entity=entity, fields=await _access_fields(db, entity), roles=out)


@router.put("/field-access/{entity}/{role_id}", response_model=AccessOut)
async def set_access(
    entity: str, role_id: uuid.UUID, body: AccessIn, db: CrmDb, actor: RoleManager
) -> AccessOut:
    """Replace one role's access on one kind of record. Fields not sent are Edit."""
    entity = await _entity(db, entity)
    role = await db.get(Role, role_id)
    if role is None:
        raise NotFound("Role not found")
    if role.key in A.UNRESTRICTED_ROLES:
        raise Invalid(f"{role.name} always edits every field")
    fields = {f.key: f for f in await _access_fields(db, entity)}
    for key, access in body.access.items():
        if key not in fields:
            raise Invalid(f"Unknown field: {key}")
        if access not in fields[key].choices:
            raise Invalid(
                f"{fields[key].label} can be view only at most (people must reach the lead)"
            )
    before = await A.for_role(db, role.id, entity)
    await db.execute(
        delete(FieldPermission).where(
            FieldPermission.role_id == role.id, FieldPermission.entity == entity
        )
    )
    after = {k: v for k, v in body.access.items() if v != "edit"}
    for key, access in after.items():
        db.add(
            FieldPermission(
                tenant_id=actor.user.tenant_id,
                role_id=role.id,
                entity=entity,
                field=key,
                access=access,
            )  # fmt: skip
        )
    await audit(
        db, actor, "field_access.updated", "role", role.id,
        {"entity": entity, "access": before}, {"entity": entity, "access": after},
    )  # fmt: skip
    await db.flush()
    return await get_access(entity, db, actor)

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.modules.auth.deps import CurrentUser, TenantDb, effective_permissions, require
from app.modules.roles import service
from app.modules.roles.models import Permission, Role
from app.modules.roles.permissions import ALL_CODES

router = APIRouter(prefix="/api/v1", tags=["roles"])
Scope = Literal["own", "team", "all"]


def _known(codes: list[str] | None) -> list[str] | None:
    if codes is not None:
        unknown = set(codes) - ALL_CODES
        if unknown:
            raise ValueError(f"Unknown permission codes: {sorted(unknown)}")
    return codes


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Scope
    permissions: list[str] = []
    _check = field_validator("permissions")(_known)


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    scope: Scope | None = None
    permissions: list[str] | None = None
    _check = field_validator("permissions")(_known)


class RoleOut(BaseModel):
    id: uuid.UUID
    key: str | None
    name: str
    scope: str
    is_system: bool
    permissions: list[str]


class PermissionOut(BaseModel):
    code: str
    module: str
    description: str


async def _out(db, role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        key=role.key,
        name=role.name,
        scope=role.scope,
        is_system=role.is_system,
        permissions=sorted(await effective_permissions(db, role)),
    )


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    db: TenantDb, _: Annotated[CurrentUser, require("roles.manage")]
) -> list[PermissionOut]:
    rows = (await db.scalars(select(Permission).order_by(Permission.code))).all()
    return [PermissionOut(code=p.code, module=p.module, description=p.description) for p in rows]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    db: TenantDb, _: Annotated[CurrentUser, require("users.read")]
) -> list[RoleOut]:
    roles = (await db.scalars(select(Role).order_by(Role.is_system.desc(), Role.name))).all()
    return [await _out(db, r) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleIn, db: TenantDb, actor: Annotated[CurrentUser, require("roles.manage")]
) -> RoleOut:
    role = await service.create_role(db, actor, body.name, body.scope, set(body.permissions))
    return await _out(db, role)


@router.get("/roles/{role_id}", response_model=RoleOut)
async def get_role(
    role_id: uuid.UUID, db: TenantDb, _: Annotated[CurrentUser, require("users.read")]
) -> RoleOut:
    return await _out(db, await service.get_role(db, role_id))


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: uuid.UUID,
    body: RolePatch,
    db: TenantDb,
    actor: Annotated[CurrentUser, require("roles.manage")],
) -> RoleOut:
    role = await service.get_role(db, role_id)
    codes = set(body.permissions) if body.permissions is not None else None
    role = await service.update_role(db, actor, role, body.name, body.scope, codes)
    return await _out(db, role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID, db: TenantDb, actor: Annotated[CurrentUser, require("roles.manage")]
) -> None:
    await service.delete_role(db, actor, await service.get_role(db, role_id))

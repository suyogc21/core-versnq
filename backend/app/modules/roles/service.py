import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound
from app.modules.audit.models import record
from app.modules.auth.deps import CurrentUser, effective_permissions
from app.modules.roles.models import Role, RolePermission
from app.modules.users.models import User


async def get_role(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise NotFound("Role not found")
    return role


def _check_grantable(actor: CurrentUser, codes: set[str]) -> None:
    missing = codes - actor.permissions
    if missing:
        raise Forbidden(f"You cannot grant permissions you do not have: {sorted(missing)}")


async def _set_permissions(db: AsyncSession, role: Role, codes: set[str]) -> None:
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    db.add_all(
        RolePermission(tenant_id=role.tenant_id, role_id=role.id, permission_code=c)
        for c in sorted(codes)
    )


def _snapshot(role: Role, codes: set[str]) -> dict:
    return {"name": role.name, "scope": role.scope, "permissions": sorted(codes)}


async def create_role(
    db: AsyncSession, actor: CurrentUser, name: str, scope: str, codes: set[str]
) -> Role:
    _check_grantable(actor, codes)
    role = Role(tenant_id=actor.user.tenant_id, name=name, scope=scope, is_system=False)
    db.add(role)
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict("A role with this name already exists") from None
    await _set_permissions(db, role, codes)
    await record(
        db,
        tenant_id=role.tenant_id,
        actor_id=actor.user.id,
        action="role.created",
        entity_type="role",
        entity_id=role.id,
        after=_snapshot(role, codes),
    )
    return role


async def update_role(
    db: AsyncSession,
    actor: CurrentUser,
    role: Role,
    name: str | None,
    scope: str | None,
    codes: set[str] | None,
) -> Role:
    if role.key == "owner":
        raise Forbidden("The Owner role cannot be changed")
    before = _snapshot(role, await effective_permissions(db, role))
    if name is not None and name != role.name:
        if role.is_system:
            raise Conflict("System roles cannot be renamed")
        role.name = name
    if scope is not None:
        role.scope = scope
    if codes is not None:
        _check_grantable(actor, codes)
        await _set_permissions(db, role, codes)
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict("A role with this name already exists") from None
    await record(
        db,
        tenant_id=role.tenant_id,
        actor_id=actor.user.id,
        action="role.updated",
        entity_type="role",
        entity_id=role.id,
        before=before,
        after=_snapshot(role, await effective_permissions(db, role)),
    )
    return role


async def delete_role(db: AsyncSession, actor: CurrentUser, role: Role) -> None:
    if role.is_system:
        raise Conflict("System roles cannot be deleted")
    in_use = await db.scalar(select(func.count()).where(User.role_id == role.id))
    if in_use:
        raise Conflict(f"{in_use} user(s) still have this role")
    before = _snapshot(role, await effective_permissions(db, role))
    await db.delete(role)
    await record(
        db,
        tenant_id=role.tenant_id,
        actor_id=actor.user.id,
        action="role.deleted",
        entity_type="role",
        entity_id=role.id,
        before=before,
    )

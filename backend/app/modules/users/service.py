"""User management inside one tenant, with the anti-escalation rules."""

import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.security import hash_password
from app.modules.audit.models import record
from app.modules.auth.deps import CurrentUser, effective_permissions
from app.modules.auth.service import INVITE_TTL, issue_link_token, revoke_all_sessions
from app.modules.roles.models import Role
from app.modules.teams.service import visible_user_ids
from app.modules.users.models import User


class LastOwner(Conflict):
    def __init__(self):
        super().__init__("A workspace must keep at least one active Owner")


def _snap(u: User) -> dict:
    return {
        "name": u.name,
        "email": u.email,
        "phone": u.phone,
        "status": u.status,
        "role_id": str(u.role_id),
        "must_change_password": u.must_change_password,
    }


async def _audit(db, actor: CurrentUser, action: str, target: User, before=None) -> None:
    await record(
        db,
        tenant_id=target.tenant_id,
        actor_id=actor.user.id,
        action=action,
        entity_type="user",
        entity_id=target.id,
        before=before,
        after=_snap(target),
    )


async def list_visible(db: AsyncSession, actor: CurrentUser) -> list[User]:
    visible = await visible_user_ids(db, actor.user.id, actor.role.scope)
    query = select(User).where(User.status != "integration").order_by(User.name)
    if visible is not None:
        query = query.where(User.id.in_(visible))
    return list((await db.scalars(query)).all())


async def get_visible(db: AsyncSession, actor: CurrentUser, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    visible = await visible_user_ids(db, actor.user.id, actor.role.scope)
    if (
        user is None
        or user.status == "integration"
        or (visible is not None and user.id not in visible)
    ):
        raise NotFound("User not found")
    return user


async def ensure_not_last_owner(db: AsyncSession, user_id: uuid.UUID) -> None:
    others = await db.scalar(
        select(func.count())
        .select_from(User)
        .join(Role, (Role.id == User.role_id) & (Role.tenant_id == User.tenant_id))
        .where(Role.key == "owner", User.status == "active", User.id != user_id)
    )
    if not others:
        raise LastOwner


async def _role_of(db: AsyncSession, user: User) -> Role:
    return await db.get(Role, user.role_id)


def _not_self(actor: CurrentUser, target: User) -> None:
    if target.id == actor.user.id:
        raise Forbidden("You cannot do this to your own account")


def _can_touch(actor: CurrentUser, target_role: Role) -> None:
    if target_role.key == "owner" and actor.role.key != "owner":
        raise Forbidden("Only an Owner can manage Owners")


async def _assignable_role(db: AsyncSession, actor: CurrentUser, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)  # RLS: another tenant's role is simply not found
    if role is None:
        raise Invalid("Role not found in this workspace")
    if role.key == "owner" and actor.role.key != "owner":
        raise Forbidden("Only an Owner can assign the Owner role")
    missing = await effective_permissions(db, role) - actor.permissions
    if missing:
        raise Forbidden("You cannot assign a role with permissions you do not have")
    return role


async def invite(
    db: AsyncSession, actor: CurrentUser, email: str, name: str, role_id: uuid.UUID
) -> tuple[User, str]:
    role = await _assignable_role(db, actor, role_id)
    user = User(
        tenant_id=actor.user.tenant_id, email=email, name=name, status="invited", role_id=role.id
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict("A user with this email already exists") from None
    plain = await issue_link_token(db, user.tenant_id, user.id, "invite", INVITE_TTL)
    await _audit(db, actor, "user.invited", user)
    return user, plain


async def update(db: AsyncSession, actor: CurrentUser, target: User, changes: dict) -> User:
    before = _snap(target)
    target_role = await _role_of(db, target)
    if target.id != actor.user.id:
        _can_touch(actor, target_role)
    if "role_id" in changes and changes["role_id"] != target.role_id:
        _not_self(actor, target)
        new_role = await _assignable_role(db, actor, changes["role_id"])
        if target_role.key == "owner" and new_role.key != "owner":
            await ensure_not_last_owner(db, target.id)
        target.role_id = new_role.id
    if changes.get("name"):
        target.name = changes["name"]
    if "phone" in changes:
        target.phone = changes["phone"]
    await _audit(db, actor, "user.updated", target, before)
    return target


async def set_status(db: AsyncSession, actor: CurrentUser, target: User, status: str) -> User:
    _not_self(actor, target)
    target_role = await _role_of(db, target)
    _can_touch(actor, target_role)
    if target.status == "invited":
        raise Conflict("This user has not accepted the invite yet")
    before = _snap(target)
    if status == "disabled":
        if target_role.key == "owner":
            await ensure_not_last_owner(db, target.id)
        await revoke_all_sessions(db, target.id)
    target.status = status
    await _audit(
        db, actor, f"user.{'disabled' if status == 'disabled' else 'enabled'}", target, before
    )
    return target


async def set_temporary_password(db: AsyncSession, actor: CurrentUser, target: User) -> str:
    _not_self(actor, target)
    _can_touch(actor, await _role_of(db, target))
    if target.status != "active":
        raise Conflict("Only active users can get a temporary password")
    before = _snap(target)
    temp = secrets.token_urlsafe(12)
    target.password_hash = hash_password(temp)
    target.must_change_password = True
    await revoke_all_sessions(db, target.id)
    await _audit(db, actor, "user.temporary_password_set", target, before)
    return temp


async def reset_two_factor(db: AsyncSession, actor: CurrentUser, target: User) -> None:
    """Lost phone (go-live G-4): the person's authenticator app and backup codes are removed and
    they are signed out everywhere; they sign in with the emailed code and can set it up again."""
    from app.modules.auth.service import clear_recovery_codes

    _not_self(actor, target)
    _can_touch(actor, await _role_of(db, target))
    if not target.totp_enabled:
        raise Conflict("This person doesn't use an authenticator app")
    target.totp_enabled, target.totp_secret_enc = False, None
    await clear_recovery_codes(db, target.id)
    await revoke_all_sessions(db, target.id)
    await _audit(db, actor, "user.2fa_reset", target, {"totp_enabled": True})


async def renew_invite(db: AsyncSession, actor: CurrentUser, target: User) -> str:
    _can_touch(actor, await _role_of(db, target))
    if target.status != "invited":
        raise Conflict("This user has already accepted the invite")
    plain = await issue_link_token(db, target.tenant_id, target.id, "invite", INVITE_TTL)
    await _audit(db, actor, "user.invite_resent", target)
    return plain

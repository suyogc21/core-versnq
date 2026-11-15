"""Dependencies for tenant routes: workspace session and the logged-in user."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import request_actor
from app.core.hosts import Workspace, get_workspace
from app.core.security import InvalidToken, decode_access_token
from app.core.tenancy import tenant_session
from app.modules.auth.service import restrictions
from app.modules.roles.models import Role, RolePermission
from app.modules.roles.permissions import ALL_CODES
from app.modules.users.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_tenant_db(
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AsyncIterator[AsyncSession]:
    async with tenant_session(workspace.id) as session:
        yield session


WorkspaceDep = Annotated[Workspace, Depends(get_workspace)]
TenantDb = Annotated[AsyncSession, Depends(get_tenant_db)]


async def effective_permissions(db: AsyncSession, role: Role) -> set[str]:
    """Owner holds every code (including future ones) except acting for other people, which only
    ACE's key gets (step O3); others hold their granted rows."""
    if role.key == "owner":
        return set(ALL_CODES - {"drafts.approve_for_users"})
    rows = await db.scalars(
        select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
    )
    return set(rows.all())


def has_permission(permissions: set[str], code: str) -> bool:
    """Deny by default: only an exact, known grant passes."""
    return code in ALL_CODES and code in permissions


@dataclass
class CurrentUser:
    user: User
    role: Role
    restrictions: list[str]
    permissions: set[str]


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


async def _key_user(request: Request, workspace: Workspace, db: AsyncSession, token: str):
    """An API key acts as its integration user (milestone 4). Its requests are logged."""
    from app.modules.integrations import keys

    found = await keys.authenticate(db, token)
    if found is None:
        raise _unauthorized()
    key, user = found
    request.state.api_key = (workspace.id, key.id)  # the API log middleware reads this
    request_actor.set((user.id, "integration"))
    role = await db.get(Role, user.role_id)
    return CurrentUser(
        user=user, role=role, restrictions=[], permissions=await effective_permissions(db, role)
    )


async def _extension_user(request: Request, db: AsyncSession, token: str):
    """The WhatsApp extension's token acts as its rep, and only on the extension's own
    endpoints (Decision log #41)."""
    from app.modules.engage import extension

    if not request.url.path.startswith("/api/v1/extension/"):
        raise _unauthorized()
    user = await extension.token_user(db, token, request.headers.get("x-versnq-extension"))
    if user is None:
        raise _unauthorized()
    request_actor.set((user.id, "user"))  # the rep, through their extension
    role = await db.get(Role, user.role_id)
    return CurrentUser(
        user=user,
        role=role,
        restrictions=restrictions(user, role),
        permissions=await effective_permissions(db, role),
    )


async def current_user_any(
    request: Request,
    workspace: WorkspaceDep,
    db: TenantDb,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """Logged-in user, even if they still must change password or set up 2FA. An API key
    (`vq_live_…`) signs in as its integration user."""
    if creds is None:
        raise _unauthorized()
    if creds.credentials.startswith("vq_live_"):
        return await _key_user(request, workspace, db, creds.credentials)
    if creds.credentials.startswith("vq_ext_"):  # the WhatsApp extension (step 10a)
        return await _extension_user(request, db, creds.credentials)
    try:
        claims = decode_access_token(creds.credentials, expected_typ="user")
    except InvalidToken:
        raise _unauthorized() from None
    if claims.tenant_id != workspace.id:  # token from another workspace
        raise _unauthorized()
    user = await db.get(User, claims.sub)
    if user is None or user.status != "active":
        raise _unauthorized()
    request_actor.set((user.id, "user"))
    role = await db.get(Role, user.role_id)
    return CurrentUser(
        user=user,
        role=role,
        restrictions=restrictions(user, role),
        permissions=await effective_permissions(db, role),
    )


async def current_user(
    current: Annotated[CurrentUser, Depends(current_user_any)],
) -> CurrentUser:
    """Logged-in user with no outstanding restriction."""
    if current.restrictions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, current.restrictions[0])
    return current


AnyUser = Annotated[CurrentUser, Depends(current_user_any)]
ActiveUser = Annotated[CurrentUser, Depends(current_user)]


def require(code: str):
    """Dependency: the active user must hold `code`."""

    async def check(current: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if not has_permission(current.permissions, code):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied")
        return current

    return Depends(check)

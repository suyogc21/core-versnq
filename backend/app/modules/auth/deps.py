"""Dependencies for tenant routes: workspace session and the logged-in user."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hosts import Workspace, get_workspace
from app.core.security import InvalidToken, decode_access_token
from app.core.tenancy import tenant_session
from app.modules.auth.service import restrictions
from app.modules.roles.models import Role
from app.modules.users.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_tenant_db(
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AsyncIterator[AsyncSession]:
    async with tenant_session(workspace.id) as session:
        yield session


WorkspaceDep = Annotated[Workspace, Depends(get_workspace)]
TenantDb = Annotated[AsyncSession, Depends(get_tenant_db)]


@dataclass
class CurrentUser:
    user: User
    role: Role
    restrictions: list[str]


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


async def current_user_any(
    workspace: WorkspaceDep,
    db: TenantDb,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """Logged-in user, even if they still must change password or set up 2FA."""
    if creds is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(creds.credentials, expected_typ="user")
    except InvalidToken:
        raise _unauthorized() from None
    if claims.tenant_id != workspace.id:  # token from another workspace
        raise _unauthorized()
    user = await db.get(User, claims.sub)
    if user is None or user.status != "active":
        raise _unauthorized()
    role = await db.get(Role, user.role_id)
    return CurrentUser(user=user, role=role, restrictions=restrictions(user, role))


async def current_user(
    current: Annotated[CurrentUser, Depends(current_user_any)],
) -> CurrentUser:
    """Logged-in user with no outstanding restriction."""
    if current.restrictions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, current.restrictions[0])
    return current


AnyUser = Annotated[CurrentUser, Depends(current_user_any)]
ActiveUser = Annotated[CurrentUser, Depends(current_user)]

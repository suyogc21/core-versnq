from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_platform_db
from app.core.security import (
    ACCESS_TOKEN_MINUTES,
    REFRESH_TOKEN_DAYS,
    InvalidToken,
    decode_access_token,
)
from app.platform.staff import service
from app.platform.staff.models import PlatformStaff
from app.platform.staff.schemas import LoginIn, StaffOut, TokenOut

router = APIRouter(prefix="/platform/auth", tags=["platform-auth"])

REFRESH_COOKIE = "staff_refresh"
_COOKIE_PATH = "/platform/auth"
_GENERIC_401 = "Invalid email or password"
_bearer = HTTPBearer(auto_error=False)

Db = Annotated[AsyncSession, Depends(get_platform_db)]


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


async def current_staff(
    db: Db, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> PlatformStaff:
    if creds is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(creds.credentials, expected_typ="staff")
    except InvalidToken:
        raise _unauthorized() from None
    staff = await db.get(PlatformStaff, claims.sub)
    if staff is None or not staff.is_active:
        raise _unauthorized()
    return staff


def _issue(response: Response, access: str, refresh_plain: str) -> TokenOut:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_plain,
        max_age=REFRESH_TOKEN_DAYS * 86400,
        path=_COOKIE_PATH,
        httponly=True,
        secure=get_settings().environment == "prod",
        samesite="strict",
    )
    return TokenOut(access_token=access, expires_in=ACCESS_TOKEN_MINUTES * 60)


def _client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None, request.headers.get("user-agent"))


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, db: Db) -> TokenOut:
    try:
        access, refresh_plain = await service.login(
            db, body.email, body.password, *_client(request)
        )
    except service.AuthError:
        raise _unauthorized(_GENERIC_401) from None
    return _issue(response, access, refresh_plain)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    request: Request,
    response: Response,
    db: Db,
    staff_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenOut:
    if not staff_refresh:
        raise _unauthorized()
    try:
        access, refresh_plain = await service.refresh(db, staff_refresh, *_client(request))
    except service.AuthError:
        raise _unauthorized() from None
    return _issue(response, access, refresh_plain)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response, db: Db, staff_refresh: Annotated[str | None, Cookie()] = None
) -> Response:
    if staff_refresh:
        await service.logout(db, staff_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=StaffOut)
async def me(staff: Annotated[PlatformStaff, Depends(current_staff)]) -> StaffOut:
    return StaffOut(id=staff.id, email=staff.email, name=staff.name)

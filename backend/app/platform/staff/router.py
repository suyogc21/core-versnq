from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.auth_schemas import (
    LoginOut,
    RecoveryCodesIn,
    RecoveryCodesOut,
    TwoFactorEnableIn,
    TwoFactorSetupOut,
    TwoFactorVerifyIn,
)
from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.deps import get_platform_db
from app.core.security import (
    ACCESS_TOKEN_MINUTES,
    MFA_CHALLENGE_MINUTES,
    REFRESH_TOKEN_DAYS,
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_token,
)
from app.core.twofactor import (
    decrypt_secret,
    encrypt_secret,
    new_secret,
    provisioning_uri,
    verify_code,
)
from app.platform.staff import service
from app.platform.staff.models import PlatformStaff
from app.platform.staff.schemas import ChangePasswordIn, LoginIn, StaffOut

router = APIRouter(prefix="/platform/auth", tags=["platform-auth"])

REFRESH_COOKIE = "staff_refresh"
_COOKIE_PATH = "/platform/auth"
_GENERIC_401 = "Invalid email or password"
LOGIN_PER_IP = (10, 60)
FAILS_PER_ACCOUNT = (5, 15 * 60)
MFA_TRIES = (5, MFA_CHALLENGE_MINUTES * 60)
_bearer = HTTPBearer(auto_error=False)

Db = Annotated[AsyncSession, Depends(get_platform_db)]


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


async def current_staff_any(
    db: Db, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> PlatformStaff:
    """Logged-in staff, even before 2FA is set up."""
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


async def current_staff(
    staff: Annotated[PlatformStaff, Depends(current_staff_any)],
) -> PlatformStaff:
    """Logged-in staff with no outstanding restriction (own password set, 2FA enabled)."""
    pending = service.restrictions(staff)
    if pending:
        raise HTTPException(status.HTTP_403_FORBIDDEN, pending[0])
    return staff


AnyStaff = Annotated[PlatformStaff, Depends(current_staff_any)]


def _ip(request: Request) -> str:
    return client_ip(request)


def _issue(response: Response, access: str, refresh_plain: str) -> LoginOut:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_plain,
        max_age=REFRESH_TOKEN_DAYS * 86400,
        path=_COOKIE_PATH,
        httponly=True,
        secure=get_settings().environment == "prod",
        samesite="strict",
    )
    return LoginOut(access_token=access, expires_in=ACCESS_TOKEN_MINUTES * 60)


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request, response: Response, db: Db) -> LoginOut:
    await ratelimit.enforce(f"rl:staff-login:ip:{_ip(request)}", *LOGIN_PER_IP)
    fail_key = f"rl:staff-login:fail:{body.email.lower()}"
    if await ratelimit.count(fail_key) >= FAILS_PER_ACCOUNT[0]:
        raise ratelimit.too_many()
    try:
        staff = await service.authenticate(db, body.email, body.password)
    except service.AuthError:
        await ratelimit.hit(fail_key, *FAILS_PER_ACCOUNT)
        raise _unauthorized(_GENERIC_401) from None
    await ratelimit.clear(fail_key)
    if staff.totp_enabled:
        challenge = create_access_token(staff.id, "staff_mfa", None, minutes=MFA_CHALLENGE_MINUTES)
        return LoginOut(two_factor_required=True, challenge_token=challenge)
    access, refresh_plain = await service.open_session(
        db, staff, _ip(request), request.headers.get("user-agent")
    )
    return _issue(response, access, refresh_plain)


@router.post("/2fa/verify", response_model=LoginOut)
async def verify_two_factor(
    body: TwoFactorVerifyIn, request: Request, response: Response, db: Db
) -> LoginOut:
    await ratelimit.enforce(f"rl:staff-mfa:{hash_token(body.challenge_token)}", *MFA_TRIES)
    try:
        claims = decode_access_token(body.challenge_token, expected_typ="staff_mfa")
    except InvalidToken:
        raise _unauthorized("Invalid code") from None
    staff = await db.get(PlatformStaff, claims.sub)
    if staff is None or not staff.is_active or not staff.totp_enabled:
        raise _unauthorized("Invalid code")
    from app.core import recovery as RC

    if RC.looks_like(body.code):  # a backup code (lost phone, go-live G-4)
        ok = await service.use_recovery_code(db, staff, body.code)
    else:
        ok = verify_code(decrypt_secret(staff.totp_secret_enc), body.code)
    if not ok:
        raise _unauthorized("Invalid code")
    access, refresh_plain = await service.open_session(
        db, staff, _ip(request), request.headers.get("user-agent")
    )
    return _issue(response, access, refresh_plain)


@router.post("/refresh", response_model=LoginOut)
async def refresh(
    request: Request,
    response: Response,
    db: Db,
    staff_refresh: Annotated[str | None, Cookie()] = None,
) -> LoginOut:
    if not staff_refresh:
        raise _unauthorized()
    try:
        access, refresh_plain = await service.refresh(
            db, staff_refresh, _ip(request), request.headers.get("user-agent")
        )
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
async def me(staff: AnyStaff, db: Db) -> StaffOut:
    left = await service.recovery_codes_left(db, staff.id) if staff.totp_enabled else 0
    return StaffOut(
        id=staff.id,
        email=staff.email,
        name=staff.name,
        restrictions=service.restrictions(staff),
        recovery_codes_left=left,
    )


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: ChangePasswordIn, staff: AnyStaff, db: Db) -> None:
    try:
        await service.change_password(db, staff, body.current_password, body.new_password)
    except service.AuthError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong") from None


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
async def setup_two_factor(staff: AnyStaff) -> TwoFactorSetupOut:
    if staff.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor is already enabled")
    secret = new_secret()
    staff.totp_secret_enc = encrypt_secret(secret)
    return TwoFactorSetupOut(secret=secret, otpauth_uri=provisioning_uri(secret, staff.email))


@router.post("/2fa/enable", response_model=RecoveryCodesOut)
async def enable_two_factor(body: TwoFactorEnableIn, staff: AnyStaff, db: Db) -> RecoveryCodesOut:
    """Turns the app on and returns 10 one-time backup codes, shown only now (G-4)."""
    if staff.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor is already enabled")
    if not staff.totp_secret_enc or not verify_code(
        decrypt_secret(staff.totp_secret_enc), body.code
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    staff.totp_enabled = True
    return RecoveryCodesOut(recovery_codes=await service.issue_recovery_codes(db, staff))


@router.post("/2fa/recovery-codes", response_model=RecoveryCodesOut)
async def new_recovery_codes(
    body: RecoveryCodesIn, request: Request, staff: AnyStaff, db: Db
) -> RecoveryCodesOut:
    """Ten new backup codes (the old ones stop working). Needs the password and the app. Audited."""
    from app.core.security import verify_password
    from app.platform import audit

    await ratelimit.enforce(f"rl:staff-2fa-codes:{staff.id}", *MFA_TRIES)
    if not staff.totp_enabled or not staff.totp_secret_enc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor is not enabled")
    if not verify_password(body.password, staff.password_hash) or not verify_code(
        decrypt_secret(staff.totp_secret_enc), body.code
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password or code is wrong")
    codes = await service.issue_recovery_codes(db, staff)
    await audit.record(
        db,
        staff_id=staff.id,
        action="staff.2fa_backup_codes_renewed",
        target_type="staff",
        target_id=staff.id,
        ip=_ip(request),
    )
    return RecoveryCodesOut(recovery_codes=codes)

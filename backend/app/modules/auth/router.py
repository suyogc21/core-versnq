import logging
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from app.core import ratelimit
from app.core.auth_schemas import (
    ChallengeIn,
    LoginOut,
    TwoFactorDisableIn,
    TwoFactorEnableIn,
    TwoFactorSetupOut,
    TwoFactorVerifyIn,
)
from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.mailer import Email, Mailer, get_mailer
from app.core.security import (
    ACCESS_TOKEN_MINUTES,
    MFA_CHALLENGE_MINUTES,
    REFRESH_TOKEN_DAYS,
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_token,
    verify_password,
)
from app.core.twofactor import (
    decrypt_secret,
    encrypt_secret,
    new_secret,
    provisioning_uri,
    verify_code,
)
from app.modules.audit.models import record
from app.modules.auth import email_code, service
from app.modules.auth.deps import AnyUser, TenantDb, WorkspaceDep
from app.modules.auth.schemas import (
    AcceptInviteIn,
    ChangePasswordIn,
    ForgotIn,
    LoginIn,
    MeOut,
    ResetIn,
    RoleOut,
    TenantRef,
)
from app.modules.users.models import User

log = logging.getLogger("versnq.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE = "user_refresh"
_COOKIE_PATH = "/api/v1/auth"
_GENERIC_401 = "Invalid email or password"
_BAD_LINK = "This link is invalid or has expired"
# Generous: a whole office may share one address. Guessing is stopped per account (below).
LOGIN_PER_IP = (60, 60)
FAILS_PER_ACCOUNT = (5, 15 * 60)
FORGOT_PER_IP = (5, 3600)
MFA_TRIES = (5, email_code.CODE_MINUTES * 60)
CODES_PER_USER = (10, 3600)  # emailed sign-in codes, so a known password can't flood an inbox
RESEND_GAP = (1, 60)

MailerDep = Annotated[Mailer, Depends(get_mailer)]


def _ip(request: Request) -> str:
    return client_ip(request)


def _remember_browser(response: Response, user: User) -> None:
    response.set_cookie(
        email_code.DEVICE_COOKIE,
        email_code.device_token(user),
        max_age=email_code.TRUST_DAYS * 86400,
        path=_COOKIE_PATH,
        httponly=True,
        secure=get_settings().environment == "prod",
        samesite="strict",
    )


async def _email_code(challenge: str, user: User, ws, mailer: Mailer) -> None:
    await ratelimit.enforce(f"rl:otp-send:{user.id}", *CODES_PER_USER)
    try:
        await email_code.send(challenge, user, ws.name, mailer)
    except Exception:
        log.exception("Sign-in code email to %s failed", user.email)


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


async def _audit_self(db, user: User, action: str, after: dict, request: Request) -> None:
    """A user's own security action. Never includes passwords, tokens or 2FA secrets."""
    await record(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=action,
        entity_type="user",
        entity_id=user.id,
        after=after,
        ip=_ip(request),
    )


async def _send(mailer: Mailer, email: Email) -> None:
    try:
        await mailer.send(email)
    except Exception:
        log.exception("Email to %s failed", email.to)


@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    ws: WorkspaceDep,
    db: TenantDb,
    mailer: MailerDep,
    user_device: Annotated[str | None, Cookie()] = None,
) -> LoginOut:
    await ratelimit.enforce(f"rl:login:ip:{_ip(request)}", *LOGIN_PER_IP)
    fail_key = f"rl:login:fail:{ws.id}:{body.email.lower()}"
    if await ratelimit.count(fail_key) >= FAILS_PER_ACCOUNT[0]:
        raise ratelimit.too_many()
    try:
        user = await service.authenticate(db, body.email, body.password)
    except service.AuthError:
        await ratelimit.hit(fail_key, *FAILS_PER_ACCOUNT)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_401) from None
    await ratelimit.clear(fail_key)
    if user.totp_enabled:
        challenge = create_access_token(user.id, "user_mfa", ws.id, minutes=MFA_CHALLENGE_MINUTES)
        return LoginOut(
            two_factor_required=True, challenge_token=challenge, two_factor_method="app"
        )
    if email_code.can_receive(user.email) and not email_code.trusted(user_device, user):
        challenge = create_access_token(user.id, "user_mfa", ws.id, minutes=email_code.CODE_MINUTES)
        await _email_code(challenge, user, ws, mailer)
        return LoginOut(
            two_factor_required=True, challenge_token=challenge, two_factor_method="email"
        )
    access, refresh_plain = await service.open_session(
        db, user, _ip(request), request.headers.get("user-agent")
    )
    return _issue(response, access, refresh_plain)


@router.post("/2fa/verify", response_model=LoginOut)
async def verify_two_factor(
    body: TwoFactorVerifyIn, request: Request, response: Response, ws: WorkspaceDep, db: TenantDb
) -> LoginOut:
    await ratelimit.enforce(f"rl:mfa:{hash_token(body.challenge_token)}", *MFA_TRIES)
    try:
        claims = decode_access_token(body.challenge_token, expected_typ="user_mfa")
    except InvalidToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code") from None
    user = await db.get(User, claims.sub)
    if claims.tenant_id != ws.id or user is None or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code")
    if user.totp_enabled:
        ok = verify_code(decrypt_secret(user.totp_secret_enc), body.code)
    else:
        ok = await email_code.check(body.challenge_token, body.code)
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code")
    if not user.totp_enabled:
        _remember_browser(response, user)
    access, refresh_plain = await service.open_session(
        db, user, _ip(request), request.headers.get("user-agent")
    )
    return _issue(response, access, refresh_plain)


@router.post("/2fa/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_code(body: ChallengeIn, ws: WorkspaceDep, db: TenantDb, mailer: MailerDep) -> dict:
    """Email a new sign-in code (the old one stops working). Once a minute at most."""
    try:
        claims = decode_access_token(body.challenge_token, expected_typ="user_mfa")
    except InvalidToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again") from None
    user = await db.get(User, claims.sub)
    if claims.tenant_id != ws.id or user is None or user.status != "active" or user.totp_enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again")
    await ratelimit.enforce(f"rl:otp-gap:{hash_token(body.challenge_token)}", *RESEND_GAP)
    await _email_code(body.challenge_token, user, ws, mailer)
    return {"detail": "A new code has been sent."}


@router.post("/refresh", response_model=LoginOut)
async def refresh(
    request: Request,
    response: Response,
    db: TenantDb,
    user_refresh: Annotated[str | None, Cookie()] = None,
) -> LoginOut:
    if not user_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        access, plain = await service.refresh(
            db, user_refresh, _ip(request), request.headers.get("user-agent")
        )
    except service.AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated") from None
    return _issue(response, access, plain)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response, db: TenantDb, user_refresh: Annotated[str | None, Cookie()] = None
) -> Response:
    if user_refresh:
        await service.logout(db, user_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(current: AnyUser, db: TenantDb) -> None:
    await service.revoke_all_sessions(db, current.user.id)


@router.get("/me", response_model=MeOut)
async def me(current: AnyUser, ws: WorkspaceDep) -> MeOut:
    u, r = current.user, current.role
    return MeOut(
        id=u.id,
        email=u.email,
        name=u.name,
        role=RoleOut(key=r.key, name=r.name, scope=r.scope),
        tenant=TenantRef(id=ws.id, name=ws.name, slug=ws.slug),
        restrictions=current.restrictions,
        permissions=sorted(current.permissions),
        two_factor_enabled=u.totp_enabled,
    )


@router.post("/invite/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invite(body: AcceptInviteIn, request: Request, db: TenantDb) -> None:
    try:
        user = await service.accept_invite(db, body.token, body.password)
    except service.InvalidLink:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _BAD_LINK) from None
    await _audit_self(db, user, "user.invite_accepted", {"status": user.status}, request)


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotIn, request: Request, ws: WorkspaceDep, db: TenantDb, mailer: MailerDep
) -> dict:
    await ratelimit.enforce(f"rl:forgot:ip:{_ip(request)}", *FORGOT_PER_IP)
    found = await service.request_reset(db, body.email)
    if found:
        user, plain = found
        await db.commit()  # the link must exist before it is emailed
        link = f"https://{ws.slug}.{get_settings().base_domain}/reset-password?token={plain}"
        await _send(
            mailer,
            Email(
                to=user.email,
                subject=f"Reset your {ws.name} password",
                body=f"Hi {user.name},\n\nReset your password (valid for 60 minutes):\n{link}\n\n"
                "If you did not ask for this, ignore this email.\n",
            ),
        )
    return {"detail": "If that account exists, a reset link has been sent."}


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: ResetIn, request: Request, db: TenantDb) -> None:
    try:
        user = await service.reset_password(db, body.token, body.password)
    except service.InvalidLink:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _BAD_LINK) from None
    await _audit_self(db, user, "user.password_reset", {"sessions_revoked": True}, request)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordIn, request: Request, current: AnyUser, db: TenantDb
) -> None:
    try:
        await service.change_password(db, current.user, body.current_password, body.new_password)
    except service.AuthError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong") from None
    await _audit_self(
        db, current.user, "user.password_changed", {"sessions_revoked": True}, request
    )


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
async def setup_two_factor(current: AnyUser) -> TwoFactorSetupOut:
    if current.user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor is already enabled")
    secret = new_secret()
    current.user.totp_secret_enc = encrypt_secret(secret)
    return TwoFactorSetupOut(
        secret=secret, otpauth_uri=provisioning_uri(secret, current.user.email)
    )


@router.post("/2fa/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_two_factor(
    body: TwoFactorEnableIn, request: Request, current: AnyUser, db: TenantDb
) -> None:
    u = current.user
    if u.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor is already enabled")
    if not u.totp_secret_enc or not verify_code(decrypt_secret(u.totp_secret_enc), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    u.totp_enabled = True
    await _audit_self(db, u, "user.2fa_enabled", {"totp_enabled": True}, request)


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_two_factor(
    body: TwoFactorDisableIn, request: Request, current: AnyUser, db: TenantDb
) -> None:
    """Turn off 2FA (e.g. before moving to a new phone). Needs the password and a current code.
    Sign-in then asks for an emailed code instead."""
    u = current.user
    await ratelimit.enforce(f"rl:2fa-off:{u.id}", *MFA_TRIES)
    if not u.totp_enabled or not u.totp_secret_enc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor is not enabled")
    if not u.password_hash or not verify_password(body.password, u.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password or code is wrong")
    if not verify_code(decrypt_secret(u.totp_secret_enc), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password or code is wrong")
    u.totp_enabled, u.totp_secret_enc = False, None
    await _audit_self(db, u, "user.2fa_disabled", {"totp_enabled": False}, request)

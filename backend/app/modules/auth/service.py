"""User authentication inside one tenant. Every function runs in a tenant session."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    ACCESS_TOKEN_MINUTES,
    DUMMY_PASSWORD_HASH,
    REFRESH_TOKEN_DAYS,
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.modules.auth.models import AuthToken, UserSession
from app.modules.roles.models import Role
from app.modules.users.models import User

RESET_TTL = timedelta(minutes=60)
INVITE_TTL = timedelta(hours=72)


class AuthError(Exception):
    """Refused. Callers answer with one generic message."""


class InvalidLink(Exception):
    """Invite or reset link is unknown, used, expired, or for an inactive account."""


def _now() -> datetime:
    return datetime.now(UTC)


async def find_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(func.lower(User.email) == email.lower()))


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await find_by_email(db, email)
    if user is None or user.password_hash is None:
        verify_password(password, DUMMY_PASSWORD_HASH)  # same timing either way
        raise AuthError
    if not verify_password(password, user.password_hash) or user.status != "active":
        raise AuthError
    return user


async def open_session(
    db: AsyncSession, user: User, ip: str | None, ua: str | None
) -> tuple[str, str]:
    plain, hashed = new_refresh_token()
    db.add(
        UserSession(
            tenant_id=user.tenant_id,
            user_id=user.id,
            refresh_token_hash=hashed,
            expires_at=_now() + timedelta(days=REFRESH_TOKEN_DAYS),
            ip=ip,
            user_agent=(ua or "")[:400] or None,
        )
    )
    user.last_login_at = _now()
    return create_access_token(user.id, "user", user.tenant_id), plain


SIGNED_OUT_KEY = "auth:signed-out:{}"  # tokens issued before this time stop working at once


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    # Access tokens live 15 minutes; this makes "sign out everywhere" immediate (batch 1).
    from app.core.ratelimit import get_redis

    stamp = int(_now().timestamp())
    await get_redis().set(SIGNED_OUT_KEY.format(user_id), stamp, ex=ACCESS_TOKEN_MINUTES * 60 + 60)


async def signed_out_after(user_id: uuid.UUID, issued_at: int) -> bool:
    from app.core.ratelimit import get_redis

    stamp = await get_redis().get(SIGNED_OUT_KEY.format(user_id))
    return stamp is not None and issued_at < int(stamp)


async def refresh(
    db: AsyncSession, plain_token: str, ip: str | None, ua: str | None
) -> tuple[str, str]:
    row = await db.scalar(
        select(UserSession)
        .where(UserSession.refresh_token_hash == hash_token(plain_token))
        .with_for_update()
    )
    if row is None:
        raise AuthError
    if row.revoked_at is not None:
        # Replay of a rotated token: assume theft, end every session of this user.
        await revoke_all_sessions(db, row.user_id)
        await db.commit()  # must survive the error response that follows
        raise AuthError
    user = await db.get(User, row.user_id)
    if row.expires_at <= _now() or user is None or user.status != "active":
        raise AuthError
    from app.modules.security import service as SEC

    sec = await SEC.settings_of(db, row.tenant_id)
    idle = int(sec.get("idle_minutes") or 0)
    # The page renews its sign-in every 15 minutes while it's used, so a session not renewed
    # for the company's idle time means nobody used it: it ends (finishing plan, batch 1).
    if (idle and _now() - row.created_at > timedelta(minutes=idle)) or not SEC.ip_allowed(sec, ip):
        row.revoked_at = _now()
        await db.commit()
        raise AuthError
    row.revoked_at = _now()
    return await open_session(db, user, ip, ua)


async def logout(db: AsyncSession, plain_token: str) -> None:
    await db.execute(
        update(UserSession)
        .where(UserSession.refresh_token_hash == hash_token(plain_token))
        .where(UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def issue_link_token(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, kind: str, ttl: timedelta
) -> str:
    """New single-use link; any older unused link of the same kind stops working."""
    await db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.kind == kind)
        .where(AuthToken.used_at.is_(None))
        .values(used_at=_now())
    )
    plain, hashed = new_refresh_token()
    db.add(
        AuthToken(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            token_hash=hashed,
            expires_at=_now() + ttl,
        )
    )
    return plain


async def _consume(db: AsyncSession, plain: str, kind: str, user_status: str) -> User:
    token = await db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == hash_token(plain), AuthToken.kind == kind)
        .with_for_update()
    )
    if token is None or token.used_at is not None or token.expires_at <= _now():
        raise InvalidLink
    user = await db.get(User, token.user_id)
    if user is None or user.status != user_status:
        raise InvalidLink
    token.used_at = _now()
    return user


async def accept_invite(db: AsyncSession, plain: str, password: str) -> User:
    user = await _consume(db, plain, "invite", user_status="invited")
    user.password_hash = hash_password(password)
    user.status = "active"
    return user


async def request_reset(db: AsyncSession, email: str) -> tuple[User, str] | None:
    user = await find_by_email(db, email)
    if user is None or user.status != "active":
        return None
    return user, await issue_link_token(db, user.tenant_id, user.id, "reset", RESET_TTL)


async def reset_password(db: AsyncSession, plain: str, password: str) -> User:
    user = await _consume(db, plain, "reset", user_status="active")
    user.password_hash = hash_password(password)
    user.must_change_password = False
    await revoke_all_sessions(db, user.id)
    return user


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> None:
    if user.password_hash is None or not verify_password(current, user.password_hash):
        raise AuthError
    user.password_hash = hash_password(new)
    user.must_change_password = False
    await revoke_all_sessions(db, user.id)


def restrictions(user: User, role: Role) -> list[str]:
    """What the user must do before using the rest of Core. The authenticator app is optional
    (Decision log #45): without it, sign-in asks for an emailed code instead."""
    found = []
    if user.must_change_password:
        found.append("password_change_required")
    return found


# ---------- backup codes for the authenticator app (go-live G-4) ----------
async def issue_recovery_codes(db: AsyncSession, user: User) -> list[str]:
    """Ten new codes; the old ones stop working. The plain codes are shown once."""
    from app.core import recovery as RC
    from app.modules.auth.models import UserRecoveryCode

    await clear_recovery_codes(db, user.id)
    codes = RC.new_codes()
    db.add_all(
        UserRecoveryCode(tenant_id=user.tenant_id, user_id=user.id, code_hash=RC.code_hash(c))
        for c in codes
    )
    await db.flush()
    return codes


async def use_recovery_code(db: AsyncSession, user: User, code: str) -> bool:
    from app.core import recovery as RC
    from app.modules.auth.models import UserRecoveryCode

    row = await db.scalar(
        select(UserRecoveryCode).where(
            UserRecoveryCode.user_id == user.id,
            UserRecoveryCode.code_hash == RC.code_hash(code),
            UserRecoveryCode.used_at.is_(None),
        )
    )
    if row is None:
        return False
    row.used_at = _now()
    return True


async def recovery_codes_left(db: AsyncSession, user_id: uuid.UUID) -> int:
    from app.modules.auth.models import UserRecoveryCode

    return (
        await db.scalar(
            select(func.count())
            .select_from(UserRecoveryCode)
            .where(UserRecoveryCode.user_id == user_id, UserRecoveryCode.used_at.is_(None))
        )
        or 0
    )


async def clear_recovery_codes(db: AsyncSession, user_id: uuid.UUID) -> None:
    from sqlalchemy import delete

    from app.modules.auth.models import UserRecoveryCode

    await db.execute(delete(UserRecoveryCode).where(UserRecoveryCode.user_id == user_id))

"""Staff authentication: login, refresh-token rotation with reuse detection, logout."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    DUMMY_PASSWORD_HASH,
    REFRESH_TOKEN_DAYS,
    create_access_token,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.platform.staff.models import PlatformStaff, PlatformStaffSession


class AuthError(Exception):
    """Login or refresh refused. The caller shows one generic message."""


def _now() -> datetime:
    return datetime.now(UTC)


async def _open_session(db: AsyncSession, staff: PlatformStaff, ip: str | None, ua: str | None):
    plain, hashed = new_refresh_token()
    db.add(
        PlatformStaffSession(
            staff_id=staff.id,
            refresh_token_hash=hashed,
            expires_at=_now() + timedelta(days=REFRESH_TOKEN_DAYS),
            ip=ip,
            user_agent=(ua or "")[:400] or None,
        )
    )
    return create_access_token(staff.id, "staff", None), plain


async def login(
    db: AsyncSession, email: str, password: str, ip: str | None, ua: str | None
) -> tuple[str, str]:
    staff = await db.scalar(
        select(PlatformStaff).where(func.lower(PlatformStaff.email) == email.lower())
    )
    if staff is None:
        verify_password(password, DUMMY_PASSWORD_HASH)  # same timing as a real check
        raise AuthError
    if not verify_password(password, staff.password_hash) or not staff.is_active:
        raise AuthError
    staff.last_login_at = _now()
    return await _open_session(db, staff, ip, ua)


async def refresh(
    db: AsyncSession, plain_token: str, ip: str | None, ua: str | None
) -> tuple[str, str]:
    row = await db.scalar(
        select(PlatformStaffSession)
        .where(PlatformStaffSession.refresh_token_hash == hash_token(plain_token))
        .with_for_update()
    )
    if row is None:
        raise AuthError
    if row.revoked_at is not None:
        # A rotated token was replayed: assume theft and end every session of this account.
        await db.execute(
            update(PlatformStaffSession)
            .where(PlatformStaffSession.staff_id == row.staff_id)
            .where(PlatformStaffSession.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await db.commit()  # must survive the error response that follows
        raise AuthError
    staff = await db.get(PlatformStaff, row.staff_id)
    if row.expires_at <= _now() or staff is None or not staff.is_active:
        raise AuthError
    row.revoked_at = _now()
    return await _open_session(db, staff, ip, ua)


async def logout(db: AsyncSession, plain_token: str) -> None:
    await db.execute(
        update(PlatformStaffSession)
        .where(PlatformStaffSession.refresh_token_hash == hash_token(plain_token))
        .where(PlatformStaffSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )

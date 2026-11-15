"""Staff authentication: login, refresh-token rotation with reuse detection, logout."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import skips_2fa_for_demo
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    REFRESH_TOKEN_DAYS,
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.platform.staff.models import PlatformStaff, PlatformStaffSession


class AuthError(Exception):
    """Login or refresh refused. The caller shows one generic message."""


def _now() -> datetime:
    return datetime.now(UTC)


async def open_session(
    db: AsyncSession, staff: PlatformStaff, ip: str | None, ua: str | None
) -> tuple[str, str]:
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
    staff.last_login_at = _now()
    return create_access_token(staff.id, "staff", None), plain


async def authenticate(db: AsyncSession, email: str, password: str) -> PlatformStaff:
    staff = await db.scalar(
        select(PlatformStaff).where(func.lower(PlatformStaff.email) == email.lower())
    )
    if staff is None:
        verify_password(password, DUMMY_PASSWORD_HASH)  # same timing as a real check
        raise AuthError
    if not verify_password(password, staff.password_hash) or not staff.is_active:
        raise AuthError
    return staff


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
    return await open_session(db, staff, ip, ua)


async def logout(db: AsyncSession, plain_token: str) -> None:
    await db.execute(
        update(PlatformStaffSession)
        .where(PlatformStaffSession.refresh_token_hash == hash_token(plain_token))
        .where(PlatformStaffSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def revoke_all_sessions(db: AsyncSession, staff_id) -> None:
    await db.execute(
        update(PlatformStaffSession)
        .where(PlatformStaffSession.staff_id == staff_id)
        .where(PlatformStaffSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def change_password(db: AsyncSession, staff: PlatformStaff, current: str, new: str) -> None:
    if not verify_password(current, staff.password_hash):
        raise AuthError
    staff.password_hash = hash_password(new)
    staff.must_change_password = False
    await revoke_all_sessions(db, staff.id)


def restrictions(staff: PlatformStaff) -> list[str]:
    """What a staff member must do before any staff action. 2FA is always required."""
    found = []
    if staff.must_change_password:
        found.append("password_change_required")
    if not staff.totp_enabled and not skips_2fa_for_demo(staff.email):
        found.append("two_factor_setup_required")
    return found


# ---------- backup codes for the authenticator app (go-live G-4) ----------
async def issue_recovery_codes(db: AsyncSession, staff: PlatformStaff) -> list[str]:
    from sqlalchemy import delete

    from app.core import recovery as RC
    from app.platform.staff.models import StaffRecoveryCode

    await db.execute(delete(StaffRecoveryCode).where(StaffRecoveryCode.staff_id == staff.id))
    codes = RC.new_codes()
    db.add_all(StaffRecoveryCode(staff_id=staff.id, code_hash=RC.code_hash(c)) for c in codes)
    await db.flush()
    return codes


async def use_recovery_code(db: AsyncSession, staff: PlatformStaff, code: str) -> bool:
    from datetime import UTC, datetime

    from app.core import recovery as RC
    from app.platform.staff.models import StaffRecoveryCode

    row = await db.scalar(
        select(StaffRecoveryCode).where(
            StaffRecoveryCode.staff_id == staff.id,
            StaffRecoveryCode.code_hash == RC.code_hash(code),
            StaffRecoveryCode.used_at.is_(None),
        )
    )
    if row is None:
        return False
    row.used_at = datetime.now(UTC)
    return True

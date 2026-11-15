"""Versnq staff accounts (platform level, no tenant_id)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import IdMixin, TimestampMixin


class PlatformStaff(IdMixin, TimestampMixin, Base):
    __tablename__ = "platform_staff"
    __table_args__ = (Index("uq_platform_staff_email", text("lower(email)"), unique=True),)

    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformStaffSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "platform_staff_sessions"

    staff_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("platform_staff.id"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))


class StaffRecoveryCode(IdMixin, Base):
    """One backup code for a staff member's authenticator app (go-live G-4); works once."""

    __tablename__ = "staff_recovery_codes"

    staff_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("platform_staff.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

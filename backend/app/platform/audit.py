"""Append-only log of Versnq staff actions."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import IdMixin


class PlatformAuditLog(IdMixin, Base):
    __tablename__ = "platform_audit_log"

    staff_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("platform_staff.id"))
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    tenant_slug_snapshot: Mapped[str | None] = mapped_column(String(30))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


async def record(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None,
    tenant_slug: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        PlatformAuditLog(
            staff_id=staff_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            tenant_slug_snapshot=tenant_slug,
            before=before,
            after=after,
            ip=ip,
        )
    )


async def list_entries(
    db: AsyncSession, target_id: uuid.UUID | None, limit: int
) -> list[PlatformAuditLog]:
    q = select(PlatformAuditLog).order_by(PlatformAuditLog.created_at.desc()).limit(limit)
    if target_id:
        q = q.where(PlatformAuditLog.target_id == target_id)
    return list((await db.scalars(q)).all())

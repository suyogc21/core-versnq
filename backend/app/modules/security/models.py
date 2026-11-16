"""Security (finishing plan, batch 1): sign-in history and data exports."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.crm.models import TenantScoped


class SignIn(TenantScoped, Base):
    """One sign-in attempt to this company: who, success or why not, how, from where."""

    __tablename__ = "sign_ins"

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    email: Mapped[str] = mapped_column(String(320))
    success: Mapped[bool] = mapped_column(Boolean)
    method: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(40))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataExport(TenantScoped, Base):
    """A company's "export everything" zip, built by the worker and kept 7 days."""

    __tablename__ = "data_exports"

    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10))
    path: Mapped[str | None] = mapped_column(String(300))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

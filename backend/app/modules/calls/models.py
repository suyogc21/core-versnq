"""Calls (step C1, docs/plans/calls-plan.md): one row per call, whatever reported it."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.crm.models import TenantScoped

CALL_DEFAULTS = {"record": True, "keep_days": 30, "new_leads": False}


class Call(TenantScoped, Base):
    __tablename__ = "calls"

    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # the rep
    direction: Mapped[str] = mapped_column(String(3))  # in / out
    status: Mapped[str] = mapped_column(String(10))  # answered, missed, no_answer, busy, failed
    number: Mapped[str] = mapped_column(String(32))  # the other side, E.164
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(10))  # app, twilio, exotel
    external_id: Mapped[str] = mapped_column(String(100))  # the source's own id: repeats match
    activity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    recording_path: Mapped[str | None] = mapped_column(String(300))
    recording_type: Mapped[str | None] = mapped_column(String(60))
    recording_bytes: Mapped[int | None] = mapped_column(BigInteger)
    recording_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

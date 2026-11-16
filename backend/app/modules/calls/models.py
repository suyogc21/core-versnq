"""Calls (step C1, docs/plans/calls-plan.md): one row per call, whatever reported it."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
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
    recording_pending_url: Mapped[str | None] = mapped_column(String(500))  # to fetch (C3)
    summary: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CallingAccount(TenantScoped, TimestampMixin, Base):
    """The company's own calling account (C3): Twilio now, Exotel later the same way."""

    __tablename__ = "calling_accounts"

    provider: Mapped[str] = mapped_column(String(10))
    account_sid: Mapped[str] = mapped_column(String(64))
    auth_token_enc: Mapped[str] = mapped_column(Text)
    numbers: Mapped[list] = mapped_column(JSONB, default=list)  # the company's numbers, E.164
    forward_to: Mapped[str | None] = mapped_column(String(32))  # unanswered incoming calls


class PhoneDevice(TenantScoped, Base):
    """A rep's phone with the Versnq Android app (C4.2). Its token (`vq_app_…`) only reports
    the rep's calls and uploads their recordings; it can't read anything else."""

    __tablename__ = "phone_devices"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    token_hash: Mapped[str | None] = mapped_column(String(64))
    install_id: Mapped[str] = mapped_column(String(64))  # the app install: reconnecting replaces
    device: Mapped[str | None] = mapped_column(String(120))  # e.g. "samsung SM-A155F"
    version: Mapped[str | None] = mapped_column(String(20))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

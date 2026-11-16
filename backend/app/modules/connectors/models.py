"""Connect any CRM (docs/plans/crm-connectors-plan.md): the company's connected CRM and every
call or WhatsApp message sent to it."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped


class CrmConnection(TenantScoped, TimestampMixin, Base):
    """One per company. secret_enc: LeadSquared's keys (JSON) or the Custom CRM signing secret."""

    __tablename__ = "crm_connections"

    provider: Mapped[str] = mapped_column(String(20))  # custom / leadsquared
    host: Mapped[str | None] = mapped_column(String(200))
    secret_enc: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cursor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))


class CrmSync(TenantScoped, Base):
    """One call or WhatsApp message sent to the connected CRM; the event id keeps it to once."""

    __tablename__ = "crm_syncs"

    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(10))  # call / whatsapp
    ref_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    external_lead_id: Mapped[str | None] = mapped_column(String(100))
    external_activity_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10))  # pending / sent / skipped / failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_try_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

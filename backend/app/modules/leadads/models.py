"""Lead ads (finishing plan, batch 5d): Facebook/Instagram lead forms and Google Ads lead forms."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped


class LeadAdSource(TenantScoped, TimestampMixin, Base):
    """A connected Facebook/Instagram Page, or a Google Ads lead form webhook."""

    __tablename__ = "lead_ad_sources"

    provider: Mapped[str] = mapped_column(String(10))  # facebook / google
    name: Mapped[str] = mapped_column(String(120))
    page_id: Mapped[str | None] = mapped_column(String(40))
    page_token_enc: Mapped[str | None] = mapped_column(Text)
    app_secret_enc: Mapped[str | None] = mapped_column(Text)
    verify_token: Mapped[str | None] = mapped_column(String(64))
    key_hash: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_lead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LeadAdLead(TenantScoped, Base):
    """One lead an ad network sent: its own id makes repeats harmless; pending ones retry."""

    __tablename__ = "lead_ad_leads"

    ad_source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(10))
    provider_lead_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10))  # pending / done / failed
    tries: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

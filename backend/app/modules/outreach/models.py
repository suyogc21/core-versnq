"""Outreach (step O2, migration 0030): cold contacts and campaigns, kept apart from leads.
Company-scoped, forced row security."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped, _fk


class Contact(TenantScoped, TimestampMixin, Base):
    __tablename__ = "contacts"

    email: Mapped[str] = mapped_column(String(320))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    company: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(300))
    variables: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="active")
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[str | None] = mapped_column(String(200))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p) or self.email


class Campaign(TenantScoped, TimestampMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(10), default="draft")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    mailbox_ids: Mapped[list] = mapped_column(JSONB, default=list)  # empty: the whole pool
    schedule: Mapped[dict] = mapped_column(JSONB, default=dict)
    daily_cap: Mapped[int] = mapped_column(Integer, default=500)
    track_opens: Mapped[bool] = mapped_column(Boolean, default=False)
    track_clicks: Mapped[bool] = mapped_column(Boolean, default=False)
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class CampaignStep(TenantScoped, TimestampMixin, Base):
    __tablename__ = "campaign_steps"
    __table_args__ = (
        _fk("campaign_id", "campaigns", "fk_campaign_steps_campaign_same_tenant", "CASCADE"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    wait_days: Mapped[int] = mapped_column(Integer, default=0)
    variants: Mapped[list] = mapped_column(JSONB, default=list)  # [{subject, body}]


class CampaignContact(TenantScoped, TimestampMixin, Base):
    """A contact's place in a campaign."""

    __tablename__ = "campaign_contacts"
    __table_args__ = (
        _fk("campaign_id", "campaigns", "fk_campaign_contacts_campaign_same_tenant", "CASCADE"),
        _fk("contact_id", "contacts", "fk_campaign_contacts_contact_same_tenant", "CASCADE"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    position: Mapped[int] = mapped_column(Integer, default=1)  # the next step to send
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    variant: Mapped[int] = mapped_column(Integer, default=0)
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # always the same inbox
    ended_reason: Mapped[str | None] = mapped_column(String(40))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

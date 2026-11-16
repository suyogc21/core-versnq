"""SMS (finishing plan, batch 5d): the company's provider, its texts, every SMS in and out."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped


class SmsAccount(TenantScoped, TimestampMixin, Base):
    __tablename__ = "sms_accounts"

    provider: Mapped[str] = mapped_column(String(10))  # msg91 / twilio / test
    sender: Mapped[str] = mapped_column(String(40))  # DLT header (India) or a Twilio number
    account_sid: Mapped[str | None] = mapped_column(String(64))
    auth_enc: Mapped[str | None] = mapped_column(Text)
    webhook_token: Mapped[str] = mapped_column(String(64))


class SmsTemplate(TenantScoped, TimestampMixin, Base):
    __tablename__ = "sms_templates"

    name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(1000))
    dlt_template_id: Mapped[str | None] = mapped_column(String(40))
    provider_template_id: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SmsMessage(TenantScoped, Base):
    __tablename__ = "sms_messages"

    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    direction: Mapped[str] = mapped_column(String(3))
    number: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(String(1600))
    status: Mapped[str] = mapped_column(String(10))
    provider: Mapped[str] = mapped_column(String(10))
    provider_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(String(300))
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    enrolment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    step_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""API keys, webhook endpoints and deliveries, the API request log (milestone 4, migration 0021).
Every table is company-scoped (forced RLS)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped, _fk


class ApiKey(TenantScoped, TimestampMixin, Base):
    """A secret another system sends as `Authorization: Bearer vq_live_…`. It acts as its
    integration user, whose role decides what the key may do."""

    __tablename__ = "api_keys"
    __table_args__ = (_fk("user_id", "users", "fk_api_keys_user_same_tenant"),)

    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEndpoint(TenantScoped, TimestampMixin, Base):
    __tablename__ = "webhook_endpoints"

    name: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[list] = mapped_column(JSONB)  # event types, or ["*"]
    secret_enc: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    switched_off_reason: Mapped[str | None] = mapped_column(String(200))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class WebhookDelivery(TenantScoped, TimestampMixin, Base):
    """One event sent to one endpoint, with its retries. Together they are the webhook log."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "endpoint_id"],
            ["webhook_endpoints.tenant_id", "webhook_endpoints.id"],
            name="fk_webhook_deliveries_endpoint_same_tenant",
            ondelete="CASCADE",
        ),
    )

    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(60))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), default="pending")  # pending / ok / failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_try_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(300))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    response_snippet: Mapped[str | None] = mapped_column(String(500))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiRequestLog(TenantScoped, Base):
    __tablename__ = "api_request_log"

    key_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(500))
    status: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

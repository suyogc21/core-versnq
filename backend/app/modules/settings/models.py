import uuid

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin


class TenantSettings(TimestampMixin, Base):
    """One row per tenant: labels, locale and defaults."""

    __tablename__ = "tenant_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), primary_key=True)
    labels: Mapped[dict] = mapped_column(JSONB)
    timezone: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(10), default="en")
    default_country: Mapped[str] = mapped_column(String(2))  # ISO 3166, for phone normalization
    branding: Mapped[dict] = mapped_column(JSONB, default=dict)

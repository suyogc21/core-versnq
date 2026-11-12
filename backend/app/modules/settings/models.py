import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Uuid
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
    default_currency: Mapped[str] = mapped_column(
        String(3), default="USD"
    )  # ISO 4217, new pipelines
    branding: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Anti-leakage rule: open leads must get a next follow-up when worked (Decision log #21).
    follow_up_required: Mapped[bool] = mapped_column(Boolean, default=True)
    # Duplicates on automatic capture (R5): update the existing lead / flag / always create.
    duplicate_policy: Mapped[str] = mapped_column(String(12), default="update")
    org_grouping: Mapped[str] = mapped_column(String(10), default="off")  # off / suggest / auto
    leakage_hours: Mapped[int | None] = mapped_column(Integer)  # None = leakage guard off
    leakage_action: Mapped[str] = mapped_column(String(14), default="alert")  # alert / reassign
    # Lead scoring (step 4): engagement counts activities of the last N days; bands by score.
    engagement_days: Mapped[int] = mapped_column(Integer, default=30)
    hot_score: Mapped[int] = mapped_column(Integer, default=50)
    warm_score: Mapped[int] = mapped_column(Integer, default=20)
    # Customers and documents (step 5, Decision log #32).
    customer_prefix: Mapped[str] = mapped_column(String(10), default="C-")
    next_customer_number: Mapped[int] = mapped_column(Integer, default=1)
    document_reminder_days: Mapped[int] = mapped_column(Integer, default=3)
    storage_quota_bytes: Mapped[int] = mapped_column(BigInteger, default=2 * 1024**3)

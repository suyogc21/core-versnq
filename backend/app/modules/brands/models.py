"""Several brands in one company (finish plan, batch 4)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped, _fk


class Brand(TenantScoped, TimestampMixin, Base):
    """One of the company's brands. Never deleted, only switched off (is_active)."""

    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_brands_tenant_id_id"),
        _fk("billing_entity_id", "billing_entities", "fk_brands_entity_same_tenant"),
    )

    name: Mapped[str] = mapped_column(String(80))
    colour: Mapped[str | None] = mapped_column(String(7))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    website: Mapped[str | None] = mapped_column(String(300))
    billing_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # its invoices' header
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class UserBrand(TenantScoped, Base):
    """A brand a person is limited to. A person with none listed sees every brand."""

    __tablename__ = "user_brands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "brand_id", name="uq_user_brands"),
        _fk("user_id", "users", "fk_user_brands_user_same_tenant", "CASCADE"),
        _fk("brand_id", "brands", "fk_user_brands_brand_same_tenant", "CASCADE"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    brand_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

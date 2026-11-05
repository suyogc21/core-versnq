"""Platform tables: no tenant_id, managed by Versnq staff."""

import uuid

from sqlalchemy import CheckConstraint, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import IdMixin, TimestampMixin


class Tenant(IdMixin, TimestampMixin, Base):
    """A client company. Its users reach Core at <slug>.<BASE_DOMAIN>."""

    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint("status IN ('active', 'suspended')", name="status_valid"),)

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(30), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    industry_pack: Mapped[str] = mapped_column(String(40))
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

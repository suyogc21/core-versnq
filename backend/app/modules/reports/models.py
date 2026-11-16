"""Saved custom reports (finishing plan, batch 5c)."""

import uuid

from sqlalchemy import String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped


class SavedReport(TenantScoped, TimestampMixin, Base):
    """A report someone saved: its definition (reports.custom.Definition), private or shared
    with roles. Whoever opens it sees only what they may see themselves."""

    __tablename__ = "saved_reports"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict] = mapped_column(JSONB)
    shared_role_ids: Mapped[list] = mapped_column(JSONB, default=list)  # empty = private

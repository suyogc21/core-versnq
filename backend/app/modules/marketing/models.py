"""Marketing (finishing plan, batch 5): landing pages."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped


class LandingPage(TenantScoped, TimestampMixin, Base):
    """A page at /p/<slug> on the company's address, made of blocks (see marketing.pages)."""

    __tablename__ = "landing_pages"

    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    blocks: Mapped[list] = mapped_column(JSONB, default=list)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    seo_title: Mapped[str | None] = mapped_column(String(200))
    seo_description: Mapped[str | None] = mapped_column(String(300))
    visits: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

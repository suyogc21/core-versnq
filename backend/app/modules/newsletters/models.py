"""Newsletters (finishing plan, batch 5b): one email to many people, sent in batches by the
worker, through the company's own inboxes (capped) or Postmark's broadcast stream."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped


class Newsletter(TenantScoped, TimestampMixin, Base):
    __tablename__ = "newsletters"

    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(300))
    preheader: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    # mailboxes: the company's own inboxes (the pool, one chosen inbox, or the company
    # mailbox), within their daily limits; postmark: Postmark's broadcast stream
    path: Mapped[str] = mapped_column(String(10), default="mailboxes")
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    from_name: Mapped[str | None] = mapped_column(String(120))
    from_email: Mapped[str | None] = mapped_column(String(254))  # Postmark: a verified sender
    # {"view_id": uuid | None, "filter": LeadFilter fields, "customers_only": bool}
    audience: Mapped[dict] = mapped_column(JSONB, default=dict)
    # draft / scheduled / sending / sent / cancelled
    status: Mapped[str] = mapped_column(String(10), default="draft")
    send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class NewsletterSend(TenantScoped, Base):
    """One person's copy. Opens, clicks, unsubscribes and bounces are on its message (the same
    tracking and unsubscribe link as every other email)."""

    __tablename__ = "newsletter_sends"
    __table_args__ = (
        UniqueConstraint("newsletter_id", "lead_id", name="uq_newsletter_sends_lead"),
    )

    newsletter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("newsletters.id", ondelete="CASCADE")
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    email: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued/sent/failed/skipped
    reason: Mapped[str | None] = mapped_column(String(300))
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

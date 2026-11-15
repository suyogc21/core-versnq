"""Reply categories, rules, sortings and drafts (step O3, migration 0031). Company-scoped,
forced row security."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped, _fk


class ReplyCategory(TenantScoped, TimestampMixin, Base):
    __tablename__ = "reply_categories"

    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(500))
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_send_allowed: Mapped[bool] = mapped_column(Boolean, default=False)  # ACE step ④
    position: Mapped[int] = mapped_column(Integer, default=0)


class ReplyRule(TenantScoped, TimestampMixin, Base):
    __tablename__ = "reply_rules"
    __table_args__ = (_fk("category_id", "reply_categories", "fk_reply_rules_category", "CASCADE"),)

    category_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(12))  # convert / draft / stop / unsubscribe / notify
    instructions: Mapped[str | None] = mapped_column(String(1000))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MessageClassification(TenantScoped, Base):
    __tablename__ = "message_classifications"
    __table_args__ = (
        _fk("message_id", "messages", "fk_message_classifications_message", "CASCADE"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    category_key: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(String(500))
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    language: Mapped[str | None] = mapped_column(String(20))
    prompt_version: Mapped[str | None] = mapped_column(String(60))
    by: Mapped[str] = mapped_column(String(6))  # ace / person
    by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    rules_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rules_run: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DraftRequest(TenantScoped, Base):
    """Core asks ACE for a draft (event draft.requested); the id is the request_id ACE sends
    back, so a retry never makes a second draft."""

    __tablename__ = "draft_requests"
    __table_args__ = (
        _fk("message_id", "messages", "fk_draft_requests_message", "CASCADE"),
        _fk("conversation_id", "conversations", "fk_draft_requests_conversation", "CASCADE"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    category_key: Mapped[str] = mapped_column(String(40))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    instructions: Mapped[str | None] = mapped_column(String(1000))
    draft_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Draft(TenantScoped, TimestampMixin, Base):
    __tablename__ = "drafts"
    __table_args__ = (
        _fk("conversation_id", "conversations", "fk_drafts_conversation", "CASCADE"),
        _fk("reply_to_message_id", "messages", "fk_drafts_reply_to", "CASCADE"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    reply_to_message_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    language: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    via: Mapped[str | None] = mapped_column(String(6))
    body_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    superseded_by_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error: Mapped[str | None] = mapped_column(String(300))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

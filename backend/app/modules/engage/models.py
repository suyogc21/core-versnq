"""Sequences, templates and messages (step 9a, migration 0023). Company-scoped, forced RLS."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped, _fk


class MessageTemplate(TenantScoped, TimestampMixin, Base):
    __tablename__ = "message_templates"

    name: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(10))  # email / whatsapp
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Sequence(TenantScoped, TimestampMixin, Base):
    __tablename__ = "sequences"

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_with_others: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_on: Mapped[list] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class SequenceStep(TenantScoped, TimestampMixin, Base):
    __tablename__ = "sequence_steps"
    __table_args__ = (
        _fk("sequence_id", "sequences", "fk_sequence_steps_sequence_same_tenant", "CASCADE"),
    )

    sequence_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # email / whatsapp / task / wait / check
    config: Mapped[dict] = mapped_column(JSONB)


class Enrolment(TenantScoped, TimestampMixin, Base):
    __tablename__ = "enrolments"
    __table_args__ = (
        _fk("sequence_id", "sequences", "fk_enrolments_sequence_same_tenant", "CASCADE"),
        _fk("lead_id", "leads", "fk_enrolments_lead_same_tenant", "CASCADE"),
    )

    sequence_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10))  # active / completed / stopped
    position: Mapped[int] = mapped_column(Integer, default=1)  # the next step to run
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_reason: Mapped[str | None] = mapped_column(String(40))
    enrolled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(TenantScoped, TimestampMixin, Base):
    """Every email (and later WhatsApp) in or out, with its tracking."""

    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"], ["leads.tenant_id", "leads.id"],
            name="fk_messages_lead_same_tenant", ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "enrolment_id"], ["enrolments.tenant_id", "enrolments.id"],
            name="fk_messages_enrolment_same_tenant", ondelete="SET NULL",
        ),
    )  # fmt: skip

    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(10))
    direction: Mapped[str] = mapped_column(String(3))  # out / in
    enrolment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    step_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_address: Mapped[str] = mapped_column(String(320))
    from_address: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    links: Mapped[list] = mapped_column(JSONB, default=list)  # tracked link targets, by index
    token: Mapped[str] = mapped_column(String(48), unique=True)
    status: Mapped[str] = mapped_column(String(10))
    provider_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(String(300))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # threads (step 9b): the email's own Message-ID, what it answers, and who was copied
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    message_id_header: Mapped[str | None] = mapped_column(String(300))
    in_reply_to: Mapped[str | None] = mapped_column(String(300))
    references: Mapped[str | None] = mapped_column(Text)
    cc: Mapped[list] = mapped_column(JSONB, default=list)
    # step 9b-3: the user's own mailbox it was synced from or sent through
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # step 10a: WhatsApp's own message id (from the extension), so nothing is logged twice
    external_id: Mapped[str | None] = mapped_column(String(200))
    # step 10b: the official number's template, and Meta's delivery receipts
    whatsapp_template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageEvent(TenantScoped, Base):
    __tablename__ = "message_events"
    __table_args__ = (
        _fk("message_id", "messages", "fk_message_events_message_same_tenant", "CASCADE"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    type: Mapped[str] = mapped_column(String(12))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(TenantScoped, TimestampMixin, Base):
    """A thread with one lead (step 9b). Follows the lead's owner unless taken over."""

    __tablename__ = "conversations"
    __table_args__ = (_fk("lead_id", "leads", "fk_conversations_lead_same_tenant", "CASCADE"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(10))
    subject: Mapped[str | None] = mapped_column(String(300))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(8), default="open")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    private_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    enrolment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_direction: Mapped[str | None] = mapped_column(String(3))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # step 10b: the official number this WhatsApp conversation is on (empty: logged by the
    # reps' extension from their own WhatsApp)
    whatsapp_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ConversationMember(TenantScoped, Base):
    __tablename__ = "conversation_members"
    __table_args__ = (
        _fk(
            "conversation_id",
            "conversations",
            "fk_conversation_members_conv_same_tenant",
            "CASCADE",
        ),
        _fk("user_id", "users", "fk_conversation_members_user_same_tenant", "CASCADE"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationNote(TenantScoped, Base):
    """Internal: seen by the team, never emailed."""

    __tablename__ = "conversation_notes"
    __table_args__ = (
        _fk(
            "conversation_id", "conversations", "fk_conversation_notes_conv_same_tenant", "CASCADE"
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationRead(TenantScoped, Base):
    __tablename__ = "conversation_reads"
    __table_args__ = (
        _fk(
            "conversation_id", "conversations", "fk_conversation_reads_conv_same_tenant", "CASCADE"
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageAttachment(TenantScoped, Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        _fk("message_id", "messages", "fk_message_attachments_message_same_tenant", "CASCADE"),
        _fk("file_id", "files", "fk_message_attachments_file_same_tenant", "CASCADE"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    file_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class CannedReply(TenantScoped, TimestampMixin, Base):
    __tablename__ = "canned_replies"

    name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Mailbox(TenantScoped, TimestampMixin, Base):
    """An inbox connected by IMAP + SMTP with an app password (step 9b-3). `personal`: a user's
    own "My mailbox" (one each). `in_pool`: the company may send sequences and campaigns from it,
    within its daily limit and gap (step O1, Decision log #44). user_id: whose inbox it is
    (optional for pool inboxes such as sales@)."""

    __tablename__ = "mailboxes"
    __table_args__ = (_fk("user_id", "users", "fk_mailboxes_user_same_tenant", "CASCADE"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    personal: Mapped[bool] = mapped_column(Boolean, default=True)
    in_pool: Mapped[bool] = mapped_column(Boolean, default=False)
    from_name: Mapped[str | None] = mapped_column(String(120))
    signature: Mapped[str | None] = mapped_column(Text)
    daily_limit: Mapped[int] = mapped_column(Integer, default=30)
    min_gap_minutes: Mapped[int] = mapped_column(Integer, default=6)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_reason: Mapped[str | None] = mapped_column(String(200))
    email_address: Mapped[str] = mapped_column(String(254))
    username: Mapped[str] = mapped_column(String(254))
    password_enc: Mapped[str | None] = mapped_column(Text)
    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer)
    smtp_host: Mapped[str] = mapped_column(String(255))
    smtp_port: Mapped[int] = mapped_column(Integer)
    smtp_security: Mapped[str] = mapped_column(String(8))  # ssl / starttls
    status: Mapped[str] = mapped_column(String(8), default="active")  # active/error/off/paused
    last_error: Mapped[str | None] = mapped_column(String(500))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    # per folder: {"INBOX": {"v": uidvalidity, "last": highest uid seen}}
    sync_state: Mapped[dict] = mapped_column(JSONB, default=dict)


class CopyInAddress(TenantScoped, Base):
    """A secret address to CC / BCC or forward emails to (step 9b-2). user_id empty: the
    company's own; otherwise one user's (emails logged as theirs)."""

    __tablename__ = "copy_in_addresses"
    __table_args__ = (_fk("user_id", "users", "fk_copy_in_addresses_user_same_tenant", "CASCADE"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    token: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtensionToken(TenantScoped, Base):
    """One browser with the Versnq WhatsApp extension (step 10a): a one-time connect code,
    then a token that works only on /api/v1/extension/*."""

    __tablename__ = "extension_tokens"
    __table_args__ = (_fk("user_id", "users", "fk_extension_tokens_user_same_tenant", "CASCADE"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    code_hash: Mapped[str | None] = mapped_column(String(64))
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str | None] = mapped_column(String(64))
    device: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[str | None] = mapped_column(String(20))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhatsAppChatLink(TenantScoped, Base):
    """A WhatsApp Web chat with no visible number, linked to a lead once by the rep."""

    __tablename__ = "whatsapp_chat_links"
    __table_args__ = (
        _fk("user_id", "users", "fk_whatsapp_chat_links_user_same_tenant", "CASCADE"),
        _fk("lead_id", "leads", "fk_whatsapp_chat_links_lead_same_tenant", "CASCADE"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    chat_key: Mapped[str] = mapped_column(String(200))
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhatsAppAccount(TenantScoped, TimestampMixin, Base):
    """The company's official WhatsApp number on Meta's Cloud API (step 10b). One per company."""

    __tablename__ = "whatsapp_accounts"

    phone_number_id: Mapped[str] = mapped_column(String(40))
    waba_id: Mapped[str] = mapped_column(String(40))
    display_number: Mapped[str | None] = mapped_column(String(40))
    verified_name: Mapped[str | None] = mapped_column(String(200))
    access_token_enc: Mapped[str] = mapped_column(Text)
    app_secret_enc: Mapped[str] = mapped_column(Text)
    verify_token: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8), default="active")
    last_error: Mapped[str | None] = mapped_column(String(500))
    quality_rating: Mapped[str | None] = mapped_column(String(20))
    messaging_limit: Mapped[str | None] = mapped_column(String(40))
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppTemplate(TenantScoped, TimestampMixin, Base):
    """A message template on the official number: written with our variables, approved by Meta."""

    __tablename__ = "whatsapp_templates"

    name: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(14))  # marketing / utility
    body: Mapped[str] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSONB, default=list)  # {{1}}, {{2}}… in order
    footer: Mapped[str | None] = mapped_column(String(60))
    meta_id: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

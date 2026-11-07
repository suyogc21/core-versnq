"""CRM records: stages, sources, custom field definitions, activity types, leads, identities,
activities and tasks. Every table is company-scoped (forced RLS, migration 0010)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import IdMixin, TimestampMixin
from app.modules.teams import models as _teams  # noqa: F401  (FK targets)
from app.modules.users import models as _users  # noqa: F401


def _fk(col: str, ref: str, name: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", col], [f"{ref}.tenant_id", f"{ref}.id"], name=name, ondelete=ondelete
    )


class TenantScoped(IdMixin):
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))


class LeadStage(TenantScoped, TimestampMixin, Base):
    __tablename__ = "lead_stages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_lead_stages_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_lead_stages_tenant_name"),
    )

    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    is_open: Mapped[bool] = mapped_column(Boolean)
    is_unqualified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_converted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # the Invalid stage
    colour: Mapped[str | None] = mapped_column(String(7))
    required_fields: Mapped[list] = mapped_column(JSONB, default=list)


class LeadSource(TenantScoped, TimestampMixin, Base):
    __tablename__ = "lead_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_lead_sources_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_lead_sources_tenant_name"),
    )

    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CustomFieldDefinition(TenantScoped, TimestampMixin, Base):
    """key never changes (API, imports, automations use it); label can be renamed (#15)."""

    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_custom_field_definitions_tenant_id_id"),
        UniqueConstraint("tenant_id", "entity", "key", name="uq_custom_fields_tenant_entity_key"),
    )

    entity: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(20))
    # [{"value": "...", "label": "...", "parent": "<parent option value>"?}]
    options: Mapped[list] = mapped_column(JSONB, default=list)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False)
    depends_on: Mapped[str | None] = mapped_column(String(60))
    group_name: Mapped[str | None] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)


class CustomFieldUniqueValue(TenantScoped, Base):
    """One row per (field, value) so the database itself refuses a duplicate unique value."""

    __tablename__ = "custom_field_unique_values"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_custom_field_unique_values_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "entity", "field_key", "value_normalized", name="uq_custom_field_value"
        ),
    )

    entity: Mapped[str] = mapped_column(String(20))
    field_key: Mapped[str] = mapped_column(String(60))
    value_normalized: Mapped[str] = mapped_column(String(500))
    record_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)


class ActivityType(TenantScoped, TimestampMixin, Base):
    __tablename__ = "activity_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_activity_types_tenant_id_id"),
        UniqueConstraint("tenant_id", "key", name="uq_activity_types_tenant_key"),
    )

    key: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(80))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_loggable: Mapped[bool] = mapped_column(Boolean, default=True)  # reps can log it by hand
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    fields: Mapped[list] = mapped_column(JSONB, default=list)  # same shape as custom fields
    icon: Mapped[str | None] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)


class Lead(TenantScoped, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_leads_tenant_id_id"),
        _fk("stage_id", "lead_stages", "fk_leads_stage_same_tenant"),
        _fk("source_id", "lead_sources", "fk_leads_source_same_tenant"),
        _fk("owner_user_id", "users", "fk_leads_owner_same_tenant"),
        _fk("created_by_user_id", "users", "fk_leads_creator_same_tenant"),
    )

    kind: Mapped[str] = mapped_column(String(12))
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    org_name: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(300))
    industry: Mapped[str | None] = mapped_column(String(120))
    employee_range: Mapped[str | None] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(320))
    primary_email: Mapped[str | None] = mapped_column(String(320))
    primary_phone: Mapped[str | None] = mapped_column(String(20))
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    stage_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_open: Mapped[bool] = mapped_column(Boolean)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_disposition: Mapped[str | None] = mapped_column(String(80))
    score: Mapped[int] = mapped_column(Integer, default=0)
    intent: Mapped[str | None] = mapped_column(String(20))
    intent_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_via: Mapped[str] = mapped_column(String(12))
    campaign: Mapped[str | None] = mapped_column(String(200))
    utm_source: Mapped[str | None] = mapped_column(String(200))
    utm_medium: Mapped[str | None] = mapped_column(String(200))
    utm_campaign: Mapped[str | None] = mapped_column(String(200))
    utm_term: Mapped[str | None] = mapped_column(String(200))
    utm_content: Mapped[str | None] = mapped_column(String(200))
    attribution: Mapped[dict] = mapped_column(JSONB, default=dict)
    preferred_language: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str | None] = mapped_column(String(2))
    custom_fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    unqualified_reason: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, default=1)


class LeadIdentity(TenantScoped, TimestampMixin, Base):
    __tablename__ = "lead_identities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_lead_identities_tenant_id_id"),
        _fk("lead_id", "leads", "fk_lead_identities_lead_same_tenant", "CASCADE"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    type: Mapped[str] = mapped_column(String(10))  # email / phone / linkedin
    value: Mapped[str] = mapped_column(String(320))
    value_normalized: Mapped[str] = mapped_column(String(320))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str | None] = mapped_column(String(40))
    is_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)


class Activity(TenantScoped, TimestampMixin, Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_activities_tenant_id_id"),
        _fk("lead_id", "leads", "fk_activities_lead_same_tenant", "CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "type_key"],
            ["activity_types.tenant_id", "activity_types.key"],
            name="fk_activities_type_same_tenant",
        ),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    type_key: Mapped[str] = mapped_column(String(60))
    actor_type: Mapped[str] = mapped_column(String(10))  # user / system / api / ace
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    disposition: Mapped[str | None] = mapped_column(String(80))


class Task(TenantScoped, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tasks_tenant_id_id"),
        _fk("lead_id", "leads", "fk_tasks_lead_same_tenant", "CASCADE"),
        _fk("owner_user_id", "users", "fk_tasks_owner_same_tenant"),
    )

    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(12), default="open")
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    is_follow_up: Mapped[bool] = mapped_column(Boolean, default=False)  # the lead's next follow-up
    created_from: Mapped[str] = mapped_column(String(12), default="manual")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

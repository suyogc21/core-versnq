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
    func,
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

    entity: Mapped[str] = mapped_column(String(50))  # "lead" or "rt:<record type key>"
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

    entity: Mapped[str] = mapped_column(String(50))
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
    possible_duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    email_consent: Mapped[str | None] = mapped_column(String(10))  # opted_in / opted_out
    whatsapp_consent: Mapped[str | None] = mapped_column(String(10))
    leak_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    org_suggestions_dismissed: Mapped[list] = mapped_column(JSONB, default=list)


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
        _fk("record_id", "records", "fk_activities_record_same_tenant", "CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "type_key"],
            ["activity_types.tenant_id", "activity_types.key"],
            name="fk_activities_type_same_tenant",
        ),
    )

    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # a lead's or a record's timeline
    record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
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
        _fk("record_id", "records", "fk_tasks_record_same_tenant", "CASCADE"),
        _fk("owner_user_id", "users", "fk_tasks_owner_same_tenant"),
    )

    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
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


# ---------- step 1: capture and routing (migration 0011) ----------
class CaptureSource(TenantScoped, TimestampMixin, Base):
    """A web form / webhook endpoint. Websites post to /api/v1/capture/<key>."""

    __tablename__ = "capture_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_capture_sources_tenant_id_id"),
        _fk("source_id", "lead_sources", "fk_capture_sources_source_same_tenant"),
        _fk("stage_id", "lead_stages", "fk_capture_sources_stage_same_tenant"),
    )

    name: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_hint: Mapped[str] = mapped_column(String(12))
    field_map: Mapped[dict] = mapped_column(JSONB, default=dict)  # incoming name -> field key
    consent_text: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Import(TenantScoped, TimestampMixin, Base):
    __tablename__ = "imports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_imports_tenant_id_id"),
        _fk("created_by_user_id", "users", "fk_imports_creator_same_tenant"),
    )

    file_name: Mapped[str] = mapped_column(String(200))
    headers: Mapped[list] = mapped_column(JSONB)
    row_count: Mapped[int] = mapped_column(Integer)
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict)  # column -> field key
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="uploaded")
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(TenantScoped, Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_import_rows_tenant_id_id"),
        UniqueConstraint("import_id", "row_number", name="uq_import_rows_number"),
        _fk("import_id", "imports", "fk_import_rows_import_same_tenant", "CASCADE"),
    )

    import_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    row_number: Mapped[int] = mapped_column(Integer)
    data: Mapped[list] = mapped_column(JSONB)  # cell values in header order
    status: Mapped[str] = mapped_column(String(10), default="pending")
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    message: Mapped[str | None] = mapped_column(String(500))


class LeadMerge(TenantScoped, Base):
    __tablename__ = "lead_merges"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_lead_merges_tenant_id_id"),
        _fk("survivor_id", "leads", "fk_lead_merges_survivor_same_tenant", "CASCADE"),
    )

    survivor_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    merged_lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    merged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class Consent(TenantScoped, Base):
    """Full history; the latest row per channel is the current state (copied onto the lead)."""

    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_consents_tenant_id_id"),
        _fk("lead_id", "leads", "fk_consents_lead_same_tenant", "CASCADE"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(10))
    wording: Mapped[str | None] = mapped_column(String(500))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Suppression(TenantScoped, Base):
    """Identifiers never to be messaged. Not linked to a lead, so it survives deletion (#18)."""

    __tablename__ = "suppression_list"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_suppression_list_tenant_id_id"),
        UniqueConstraint("tenant_id", "channel", "value_normalized", name="uq_suppression_value"),
    )

    channel: Mapped[str] = mapped_column(String(10))
    value_normalized: Mapped[str] = mapped_column(String(320))
    reason: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class ExternalRef(TenantScoped, TimestampMixin, Base):
    __tablename__ = "external_refs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_external_refs_tenant_id_id"),
        UniqueConstraint("tenant_id", "system", "external_id", name="uq_external_ref"),
        _fk("lead_id", "leads", "fk_external_refs_lead_same_tenant", "CASCADE"),
    )

    system: Mapped[str] = mapped_column(String(60))
    external_id: Mapped[str] = mapped_column(String(200))
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class AssignmentRule(TenantScoped, TimestampMixin, Base):
    __tablename__ = "assignment_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_assignment_rules_tenant_id_id"),)

    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    conditions: Mapped[list] = mapped_column(JSONB, default=list)
    strategy: Mapped[str] = mapped_column(String(12))  # round_robin / user / unassigned
    user_ids: Mapped[list] = mapped_column(JSONB, default=list)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SlaRule(TenantScoped, TimestampMixin, Base):
    __tablename__ = "sla_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sla_rules_tenant_id_id"),
        _fk("stage_id", "lead_stages", "fk_sla_rules_stage_same_tenant", "CASCADE"),
    )

    name: Mapped[str] = mapped_column(String(80))
    trigger: Mapped[str] = mapped_column(String(14))  # lead_created / stage_entered
    stage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    within_minutes: Mapped[int] = mapped_column(Integer)
    create_task: Mapped[bool] = mapped_column(Boolean, default=True)
    task_title: Mapped[str | None] = mapped_column(String(200))
    on_breach: Mapped[str] = mapped_column(String(14), default="alert")  # none / alert / reassign
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class LeadSla(TenantScoped, Base):
    """One running SLA clock on one lead."""

    __tablename__ = "lead_slas"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_lead_slas_tenant_id_id"),
        _fk("lead_id", "leads", "fk_lead_slas_lead_same_tenant", "CASCADE"),
        _fk("rule_id", "sla_rules", "fk_lead_slas_rule_same_tenant", "CASCADE"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    met_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Notification(TenantScoped, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_notifications_tenant_id_id"),
        _fk("user_id", "users", "fk_notifications_user_same_tenant", "CASCADE"),
        _fk("lead_id", "leads", "fk_notifications_lead_same_tenant", "CASCADE"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


# ---------- step 2: records and links (migration 0012) ----------
class RecordType(TenantScoped, TimestampMixin, Base):
    """A company-defined kind of record (Property, Batch, Vehicle...). Configuration only."""

    __tablename__ = "record_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_record_types_tenant_id_id"),
        UniqueConstraint("tenant_id", "key", name="uq_record_types_tenant_key"),
        UniqueConstraint("tenant_id", "singular", name="uq_record_types_tenant_singular"),
    )

    key: Mapped[str] = mapped_column(String(40))  # fixed; fields use entity "rt:<key>"
    singular: Mapped[str] = mapped_column(String(60))
    plural: Mapped[str] = mapped_column(String(60))
    icon: Mapped[str | None] = mapped_column(String(40))
    has_owner: Mapped[bool] = mapped_column(Boolean, default=True)
    has_stages: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer)

    @property
    def entity(self) -> str:
        return f"rt:{self.key}"


class RecordTypeStage(TenantScoped, TimestampMixin, Base):
    __tablename__ = "record_type_stages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_record_type_stages_tenant_id_id"),
        UniqueConstraint("record_type_id", "name", name="uq_record_type_stages_name"),
        _fk("record_type_id", "record_types", "fk_record_type_stages_type_same_tenant", "CASCADE"),
    )

    record_type_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    colour: Mapped[str | None] = mapped_column(String(7))
    required_fields: Mapped[list] = mapped_column(JSONB, default=list)


class Record(TenantScoped, TimestampMixin, Base):
    __tablename__ = "records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_records_tenant_id_id"),
        _fk("record_type_id", "record_types", "fk_records_type_same_tenant"),
        _fk("owner_user_id", "users", "fk_records_owner_same_tenant"),
        _fk("stage_id", "record_type_stages", "fk_records_stage_same_tenant"),
        _fk("created_by_user_id", "users", "fk_records_creator_same_tenant"),
    )

    record_type_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(300))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    custom_fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, default=1)


class LinkType(TenantScoped, TimestampMixin, Base):
    """An allowed link between two kinds (None = leads), named both ways."""

    __tablename__ = "link_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_link_types_tenant_id_id"),
        _fk("from_type_id", "record_types", "fk_link_types_from_same_tenant", "CASCADE"),
        _fk("to_type_id", "record_types", "fk_link_types_to_same_tenant", "CASCADE"),
    )

    from_type_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_type_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(String(80))
    inverse_label: Mapped[str] = mapped_column(String(80))
    many_to: Mapped[bool] = mapped_column(Boolean, default=True)  # a "from" has many "to"s
    many_from: Mapped[bool] = mapped_column(Boolean, default=True)  # a "to" has many "from"s
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer)


class Link(TenantScoped, Base):
    __tablename__ = "links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_links_tenant_id_id"),
        _fk("link_type_id", "link_types", "fk_links_type_same_tenant", "CASCADE"),
        _fk("from_lead_id", "leads", "fk_links_from_lead_same_tenant", "CASCADE"),
        _fk("from_record_id", "records", "fk_links_from_record_same_tenant", "CASCADE"),
        _fk("to_lead_id", "leads", "fk_links_to_lead_same_tenant", "CASCADE"),
        _fk("to_record_id", "records", "fk_links_to_record_same_tenant", "CASCADE"),
    )

    link_type_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    from_lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    from_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class RecordTypeAccess(TenantScoped, TimestampMixin, Base):
    """What one role may do with one record type (the Owner role may always do everything)."""

    __tablename__ = "record_type_access"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_record_type_access_tenant_id_id"),
        UniqueConstraint("role_id", "record_type_id", name="uq_record_type_access"),
        _fk("role_id", "roles", "fk_record_type_access_role_same_tenant", "CASCADE"),
        _fk("record_type_id", "record_types", "fk_record_type_access_type_same_tenant", "CASCADE"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    record_type_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    can_view: Mapped[bool] = mapped_column(Boolean, default=False)
    can_create: Mapped[bool] = mapped_column(Boolean, default=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    scope: Mapped[str] = mapped_column(String(4), default="own")

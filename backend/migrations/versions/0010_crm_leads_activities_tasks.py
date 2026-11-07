"""CRM slice A: stages, sources, custom fields, activity types, leads, identities,
activities, tasks; lead permissions; follow-up rule setting

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "lead_stages",
    "lead_sources",
    "custom_field_definitions",
    "custom_field_unique_values",
    "activity_types",
    "leads",
    "lead_identities",
    "activities",
    "tasks",
)

# Frozen copy for this migration (app/modules/roles/permissions.py is the live catalogue).
PERMISSIONS = [
    ("leads.create", "crm", "Add leads"),
    ("leads.edit", "crm", "Edit visible leads, log activities and manage tasks"),
    ("leads.assign", "crm", "Change a lead's owner"),
    ("leads.delete", "crm", "Permanently delete leads"),
    ("crm.configure", "crm", "Set up stages, sources, custom fields and activity types"),
]
DEFAULT_GRANTS = {
    "admin": [c for c, _, _ in PERMISSIONS],
    "sales_manager": ["leads.create", "leads.edit", "leads.assign"],
    "sales_user": ["leads.create", "leads.edit"],
}


def _ts() -> list[sa.Column]:
    now = sa.func.now()
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def _base(table: str) -> list:
    return [
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id_id"),
    ]


def _same_tenant(col: str, ref: str, name: str, ondelete: str | None = None):
    """Composite FK so a row can only point at a row of the same company."""
    return sa.ForeignKeyConstraint(
        ["tenant_id", col], [f"{ref}.tenant_id", f"{ref}.id"], name=name, ondelete=ondelete
    )


def _set_null_fk(table: str, col: str, ref: str, name: str) -> None:
    """Same-company FK that clears only `col` on delete (Postgres 15+ syntax, raw SQL)."""
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {col}) "
        f"REFERENCES {ref} (tenant_id, id) ON DELETE SET NULL ({col})"
    )


def upgrade() -> None:
    permissions = sa.table(
        "permissions", sa.column("code"), sa.column("module"), sa.column("description")
    )
    op.bulk_insert(
        permissions, [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS]
    )

    op.add_column(
        "tenant_settings",
        sa.Column("follow_up_required", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "lead_stages",
        *_base("lead_stages"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("is_open", sa.Boolean, nullable=False),
        sa.Column("is_unqualified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_converted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("colour", sa.String(7)),
        sa.Column("required_fields", JSONB, nullable=False, server_default="[]"),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_lead_stages_tenant_name"),
    )

    op.create_table(
        "lead_sources",
        *_base("lead_sources"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_lead_sources_tenant_name"),
    )

    op.create_table(
        "custom_field_definitions",
        *_base("custom_field_definitions"),
        sa.Column("entity", sa.String(20), nullable=False),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("options", JSONB, nullable=False, server_default="[]"),
        sa.Column("required", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_unique", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("depends_on", sa.String(60)),
        sa.Column("group_name", sa.String(80)),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "tenant_id", "entity", "key", name="uq_custom_fields_tenant_entity_key"
        ),
    )

    op.create_table(
        "custom_field_unique_values",
        *_base("custom_field_unique_values"),
        sa.Column("entity", sa.String(20), nullable=False),
        sa.Column("field_key", sa.String(60), nullable=False),
        sa.Column("value_normalized", sa.String(500), nullable=False),
        sa.Column("record_id", sa.Uuid, nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "entity", "field_key", "value_normalized", name="uq_custom_field_value"
        ),
    )
    op.create_index(
        "ix_custom_field_unique_values_record", "custom_field_unique_values", ["record_id"]
    )

    op.create_table(
        "activity_types",
        *_base("activity_types"),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_loggable", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("fields", JSONB, nullable=False, server_default="[]"),
        sa.Column("icon", sa.String(40)),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "key", name="uq_activity_types_tenant_key"),
    )

    op.create_table(
        "leads",
        *_base("leads"),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("first_name", sa.String(120)),
        sa.Column("last_name", sa.String(120)),
        sa.Column("org_name", sa.String(200)),
        sa.Column("website", sa.String(300)),
        sa.Column("industry", sa.String(120)),
        sa.Column("employee_range", sa.String(40)),
        sa.Column("display_name", sa.String(320), nullable=False),
        sa.Column("primary_email", sa.String(320)),
        sa.Column("primary_phone", sa.String(20)),
        sa.Column("organisation_id", sa.Uuid),
        sa.Column("owner_user_id", sa.Uuid),
        sa.Column("team_id", sa.Uuid),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("stage_id", sa.Uuid, nullable=False),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_open", sa.Boolean, nullable=False),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True)),
        sa.Column("last_activity_at", sa.DateTime(timezone=True)),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True)),
        sa.Column("first_response_at", sa.DateTime(timezone=True)),
        sa.Column("last_disposition", sa.String(80)),
        sa.Column("score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("intent", sa.String(20)),
        sa.Column("intent_updated_at", sa.DateTime(timezone=True)),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Uuid, nullable=False),
        sa.Column("created_via", sa.String(12), nullable=False),
        sa.Column("campaign", sa.String(200)),
        sa.Column("utm_source", sa.String(200)),
        sa.Column("utm_medium", sa.String(200)),
        sa.Column("utm_campaign", sa.String(200)),
        sa.Column("utm_term", sa.String(200)),
        sa.Column("utm_content", sa.String(200)),
        sa.Column("attribution", JSONB, nullable=False, server_default="{}"),
        sa.Column("preferred_language", sa.String(10)),
        sa.Column("city", sa.String(120)),
        sa.Column("region", sa.String(120)),
        sa.Column("country_code", sa.String(2)),
        sa.Column("custom_fields", JSONB, nullable=False, server_default="{}"),
        sa.Column("unqualified_reason", sa.String(300)),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        *_ts(),
        sa.CheckConstraint("kind IN ('person', 'organisation')", name="kind_valid"),
        sa.CheckConstraint("origin IN ('inbound', 'outbound_ace', 'outside')", name="origin_valid"),
        _same_tenant("stage_id", "lead_stages", "fk_leads_stage_same_tenant"),
        _same_tenant("source_id", "lead_sources", "fk_leads_source_same_tenant"),
        _same_tenant("owner_user_id", "users", "fk_leads_owner_same_tenant"),
        _same_tenant("created_by_user_id", "users", "fk_leads_creator_same_tenant"),
    )
    _set_null_fk("leads", "team_id", "teams", "fk_leads_team_same_tenant")
    _set_null_fk("leads", "organisation_id", "leads", "fk_leads_organisation_same_tenant")
    for col in ("owner_user_id", "stage_id", "next_follow_up_at", "created_at"):
        op.create_index(f"ix_leads_{col}", "leads", ["tenant_id", col])

    op.create_table(
        "lead_identities",
        *_base("lead_identities"),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("value", sa.String(320), nullable=False),
        sa.Column("value_normalized", sa.String(320), nullable=False),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("label", sa.String(40)),
        sa.Column("is_whatsapp", sa.Boolean, nullable=False, server_default=sa.false()),
        *_ts(),
        sa.CheckConstraint("type IN ('email', 'phone', 'linkedin')", name="type_valid"),
        _same_tenant("lead_id", "leads", "fk_lead_identities_lead_same_tenant", "CASCADE"),
    )
    op.create_index(
        "ix_lead_identities_lookup", "lead_identities", ["tenant_id", "type", "value_normalized"]
    )
    op.create_index("ix_lead_identities_lead_id", "lead_identities", ["lead_id"])

    op.create_table(
        "activities",
        *_base("activities"),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("type_key", sa.String(60), nullable=False),
        sa.Column("actor_type", sa.String(10), nullable=False),
        sa.Column("actor_id", sa.Uuid),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("data", JSONB, nullable=False, server_default="{}"),
        sa.Column("disposition", sa.String(80)),
        *_ts(),
        _same_tenant("lead_id", "leads", "fk_activities_lead_same_tenant", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type_key"],
            ["activity_types.tenant_id", "activity_types.key"],
            name="fk_activities_type_same_tenant",
        ),
    )
    op.create_index("ix_activities_lead_time", "activities", ["lead_id", "occurred_at"])

    op.create_table(
        "tasks",
        *_base("tasks"),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_user_id", sa.Uuid, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(10), nullable=False, server_default="normal"),
        sa.Column("is_follow_up", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_from", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("due_notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint("status IN ('open', 'done', 'cancelled')", name="status_valid"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high')", name="priority_valid"),
        _same_tenant("lead_id", "leads", "fk_tasks_lead_same_tenant", "CASCADE"),
        _same_tenant("owner_user_id", "users", "fk_tasks_owner_same_tenant"),
    )
    op.create_index(
        "ix_tasks_owner_status_due", "tasks", ["tenant_id", "owner_user_id", "status", "due_at"]
    )
    op.create_index("ix_tasks_lead_id", "tasks", ["lead_id"])

    for table in TENANT_TABLES:
        enable_tenant_rls(table)

    # Default grants for companies created before this migration. Their CRM setup
    # (stages, sources, activity types) is seeded by the app on first use.
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for key, codes in DEFAULT_GRANTS.items():
            for code in codes:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                        "SELECT tenant_id, id, :code FROM roles WHERE key = :key "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"code": code, "key": key},
                )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
    op.drop_column("tenant_settings", "follow_up_required")
    codes = [c for c, _, _ in PERMISSIONS]
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:codes)"),
            {"codes": codes},
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})

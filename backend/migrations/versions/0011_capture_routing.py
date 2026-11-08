"""Step 1 — capture and routing: capture sources, CSV imports, merges, consent, suppression,
external references, assignment rules, SLA rules, notifications; lead and settings columns;
leads.import and leads.merge permissions

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "capture_sources",
    "imports",
    "import_rows",
    "lead_merges",
    "consents",
    "suppression_list",
    "external_refs",
    "assignment_rules",
    "sla_rules",
    "lead_slas",
    "notifications",
)

PERMISSIONS = [
    ("leads.import", "crm", "Import leads from a CSV file"),
    ("leads.merge", "crm", "Merge duplicate leads"),
]
# Frozen copy of app/modules/crm/setup.py STEP1_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("re_enquiry", "Enquired again", "repeat"),
    ("lead_merged", "Leads merged", "merge"),
    ("consent_changed", "Consent changed", "shield-check"),
    ("organisation_linked", "Organisation linked", "building"),
    ("sla_missed", "Response time missed", "alarm-clock"),
]
DEFAULT_GRANTS = {
    "admin": ["leads.import", "leads.merge"],
    "sales_manager": ["leads.import", "leads.merge"],
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
    return sa.ForeignKeyConstraint(
        ["tenant_id", col], [f"{ref}.tenant_id", f"{ref}.id"], name=name, ondelete=ondelete
    )


def _set_null_fk(table: str, col: str, ref: str, name: str) -> None:
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

    # ---- settings ----
    op.add_column(
        "tenant_settings",
        sa.Column("duplicate_policy", sa.String(12), nullable=False, server_default="update"),
    )
    op.add_column(
        "tenant_settings",
        sa.Column("org_grouping", sa.String(10), nullable=False, server_default="off"),
    )
    op.add_column("tenant_settings", sa.Column("leakage_hours", sa.Integer))
    op.add_column(
        "tenant_settings",
        sa.Column("leakage_action", sa.String(14), nullable=False, server_default="alert"),
    )
    op.create_check_constraint(
        "duplicate_policy_valid",
        "tenant_settings",
        "duplicate_policy IN ('update', 'flag', 'create')",
    )
    op.create_check_constraint(
        "org_grouping_valid", "tenant_settings", "org_grouping IN ('off', 'suggest', 'auto')"
    )
    op.create_check_constraint(
        "leakage_valid",
        "tenant_settings",
        "leakage_action IN ('alert', 'reassign') AND (leakage_hours IS NULL OR leakage_hours > 0)",
    )

    # ---- leads ----
    op.add_column("leads", sa.Column("possible_duplicate_of_id", sa.Uuid))
    op.add_column("leads", sa.Column("email_consent", sa.String(10)))
    op.add_column("leads", sa.Column("whatsapp_consent", sa.String(10)))
    op.add_column("leads", sa.Column("leak_alerted_at", sa.DateTime(timezone=True)))
    op.add_column(
        "leads",
        sa.Column("org_suggestions_dismissed", JSONB, nullable=False, server_default="[]"),
    )
    _set_null_fk(
        "leads", "possible_duplicate_of_id", "leads", "fk_leads_possible_duplicate_same_tenant"
    )
    op.create_index("ix_leads_organisation_id", "leads", ["tenant_id", "organisation_id"])

    # ---- capture ----
    op.create_table(
        "capture_sources",
        *_base("capture_sources"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("source_id", sa.Uuid, nullable=False),
        sa.Column("stage_id", sa.Uuid),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_hint", sa.String(12), nullable=False),
        sa.Column("field_map", JSONB, nullable=False, server_default="{}"),
        sa.Column("consent_text", sa.String(500)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_capture_sources_tenant_name"),
        _same_tenant("source_id", "lead_sources", "fk_capture_sources_source_same_tenant"),
        _same_tenant("stage_id", "lead_stages", "fk_capture_sources_stage_same_tenant"),
    )

    # ---- imports ----
    op.create_table(
        "imports",
        *_base("imports"),
        sa.Column("file_name", sa.String(200), nullable=False),
        sa.Column("headers", JSONB, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("mapping", JSONB, nullable=False, server_default="{}"),
        sa.Column("options", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(10), nullable=False, server_default="uploaded"),
        sa.Column("created_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Uuid, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.CheckConstraint(
            "status IN ('uploaded', 'queued', 'running', 'done', 'cancelled')",
            name="status_valid",
        ),
        _same_tenant("created_by_user_id", "users", "fk_imports_creator_same_tenant"),
    )
    op.create_table(
        "import_rows",
        *_base("import_rows"),
        sa.Column("import_id", sa.Uuid, nullable=False),
        sa.Column("row_number", sa.Integer, nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("message", sa.String(500)),
        sa.CheckConstraint(
            "status IN ('pending', 'created', 'updated', 'skipped', 'failed')",
            name="status_valid",
        ),
        _same_tenant("import_id", "imports", "fk_import_rows_import_same_tenant", "CASCADE"),
        sa.UniqueConstraint("import_id", "row_number", name="uq_import_rows_number"),
    )
    _set_null_fk("import_rows", "lead_id", "leads", "fk_import_rows_lead_same_tenant")

    # ---- merges, consent, suppression, external refs ----
    op.create_table(
        "lead_merges",
        *_base("lead_merges"),
        sa.Column("survivor_id", sa.Uuid, nullable=False),
        sa.Column("merged_lead_id", sa.Uuid, nullable=False),  # deleted; kept as a plain id
        sa.Column("merged_by_user_id", sa.Uuid),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        _same_tenant("survivor_id", "leads", "fk_lead_merges_survivor_same_tenant", "CASCADE"),
    )
    op.create_index("ix_lead_merges_merged", "lead_merges", ["tenant_id", "merged_lead_id"])

    op.create_table(
        "consents",
        *_base("consents"),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("wording", sa.String(500)),
        sa.Column("evidence", JSONB, nullable=False, server_default="{}"),
        sa.Column("actor_user_id", sa.Uuid),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel IN ('email', 'whatsapp')", name="channel_valid"),
        sa.CheckConstraint("status IN ('opted_in', 'opted_out')", name="status_valid"),
        sa.CheckConstraint(
            "source IN ('form', 'import', 'manual', 'api', 'unsubscribe')", name="source_valid"
        ),
        _same_tenant("lead_id", "leads", "fk_consents_lead_same_tenant", "CASCADE"),
    )
    op.create_index("ix_consents_lead", "consents", ["lead_id", "captured_at"])

    op.create_table(
        "suppression_list",
        *_base("suppression_list"),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("value_normalized", sa.String(320), nullable=False),
        sa.Column("reason", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("channel IN ('email', 'whatsapp', 'sms')", name="channel_valid"),
        sa.CheckConstraint("reason IN ('opt_out', 'bounce', 'complaint')", name="reason_valid"),
        sa.UniqueConstraint(
            "tenant_id", "channel", "value_normalized", name="uq_suppression_value"
        ),
    )

    op.create_table(
        "external_refs",
        *_base("external_refs"),
        sa.Column("system", sa.String(60), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "system", "external_id", name="uq_external_ref"),
        _same_tenant("lead_id", "leads", "fk_external_refs_lead_same_tenant", "CASCADE"),
    )
    op.create_index("ix_external_refs_lead", "external_refs", ["lead_id"])

    # ---- routing ----
    op.create_table(
        "assignment_rules",
        *_base("assignment_rules"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("conditions", JSONB, nullable=False, server_default="[]"),
        sa.Column("strategy", sa.String(12), nullable=False),
        sa.Column("user_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("team_id", sa.Uuid),
        sa.Column("last_assigned_user_id", sa.Uuid),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
        sa.CheckConstraint(
            "strategy IN ('round_robin', 'user', 'unassigned')", name="strategy_valid"
        ),
    )
    _set_null_fk("assignment_rules", "team_id", "teams", "fk_assignment_rules_team_same_tenant")

    op.create_table(
        "sla_rules",
        *_base("sla_rules"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("trigger", sa.String(14), nullable=False),
        sa.Column("stage_id", sa.Uuid),
        sa.Column("within_minutes", sa.Integer, nullable=False),
        sa.Column("create_task", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("task_title", sa.String(200)),
        sa.Column("on_breach", sa.String(14), nullable=False, server_default="alert"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
        sa.CheckConstraint("trigger IN ('lead_created', 'stage_entered')", name="trigger_valid"),
        sa.CheckConstraint("on_breach IN ('none', 'alert', 'reassign')", name="breach_valid"),
        sa.CheckConstraint("within_minutes > 0", name="within_positive"),
        sa.CheckConstraint(
            "(trigger = 'stage_entered') = (stage_id IS NOT NULL)", name="stage_when_needed"
        ),
        _same_tenant("stage_id", "lead_stages", "fk_sla_rules_stage_same_tenant", "CASCADE"),
    )

    op.create_table(
        "lead_slas",
        *_base("lead_slas"),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("rule_id", sa.Uuid, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("met_at", sa.DateTime(timezone=True)),
        sa.Column("breached_at", sa.DateTime(timezone=True)),
        sa.Column("task_id", sa.Uuid),
        _same_tenant("lead_id", "leads", "fk_lead_slas_lead_same_tenant", "CASCADE"),
        _same_tenant("rule_id", "sla_rules", "fk_lead_slas_rule_same_tenant", "CASCADE"),
    )
    op.create_index(
        "ix_lead_slas_pending",
        "lead_slas",
        ["tenant_id", "due_at"],
        postgresql_where=sa.text("met_at IS NULL AND breached_at IS NULL"),
    )

    op.create_table(
        "notifications",
        *_base("notifications"),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        _same_tenant("user_id", "users", "fk_notifications_user_same_tenant", "CASCADE"),
        _same_tenant("lead_id", "leads", "fk_notifications_lead_same_tenant", "CASCADE"),
    )
    op.create_index(
        "ix_notifications_user", "notifications", ["tenant_id", "user_id", "created_at"]
    )

    for table in TENANT_TABLES:
        enable_tenant_rls(table)

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        # New built-in timeline types, only where the CRM is already set up.
        for key, label, icon in SYSTEM_TYPES:
            conn.execute(
                sa.text(
                    "INSERT INTO activity_types (id, tenant_id, key, label, icon, is_system, "
                    "is_loggable, is_active, fields, position) "
                    "SELECT gen_random_uuid(), :t, :key, :label, :icon, true, false, true, "
                    "'[]'::jsonb, COALESCE(MAX(position), 0) + 1 FROM activity_types "
                    "WHERE tenant_id = :t HAVING COUNT(*) > 0 "
                    "ON CONFLICT DO NOTHING"
                ),
                {"t": str(tenant_id), "key": key, "label": label, "icon": icon},
            )
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
    keys = [k for k, _, _ in SYSTEM_TYPES]
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM activities WHERE type_key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM activity_types WHERE key = ANY(:k)"), {"k": keys})
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("ix_leads_organisation_id", "leads")
    op.drop_constraint("fk_leads_possible_duplicate_same_tenant", "leads")
    for col in (
        "possible_duplicate_of_id",
        "email_consent",
        "whatsapp_consent",
        "leak_alerted_at",
        "org_suggestions_dismissed",
    ):
        op.drop_column("leads", col)
    for name in ("duplicate_policy_valid", "org_grouping_valid", "leakage_valid"):
        op.drop_constraint(name, "tenant_settings")
    for col in ("duplicate_policy", "org_grouping", "leakage_hours", "leakage_action"):
        op.drop_column("tenant_settings", col)
    codes = [c for c, _, _ in PERMISSIONS]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:codes)"),
            {"codes": codes},
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})

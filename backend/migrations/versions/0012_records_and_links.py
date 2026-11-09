"""Step 2 — records and links: company-defined record types (with stages, fields, access per
role), records, labelled link types and links between any leads/records; timeline and tasks
on records

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Frozen copy of app/modules/crm/setup.py STEP2_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("record_created", "Created", "plus"),
    ("linked", "Linked", "link"),
    ("unlinked", "Unlinked", "unlink"),
]

TENANT_TABLES = (
    "record_types",
    "record_type_stages",
    "records",
    "link_types",
    "links",
    "record_type_access",
)


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
    op.create_table(
        "record_types",
        *_base("record_types"),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("singular", sa.String(60), nullable=False),
        sa.Column("plural", sa.String(60), nullable=False),
        sa.Column("icon", sa.String(40)),
        sa.Column("has_owner", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("has_stages", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "key", name="uq_record_types_tenant_key"),
        sa.UniqueConstraint("tenant_id", "singular", name="uq_record_types_tenant_singular"),
    )

    op.create_table(
        "record_type_stages",
        *_base("record_type_stages"),
        sa.Column("record_type_id", sa.Uuid, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("is_open", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("colour", sa.String(7)),
        sa.Column("required_fields", JSONB, nullable=False, server_default="[]"),
        *_ts(),
        sa.UniqueConstraint("record_type_id", "name", name="uq_record_type_stages_name"),
        _same_tenant(
            "record_type_id", "record_types", "fk_record_type_stages_type_same_tenant", "CASCADE"
        ),
    )

    op.create_table(
        "records",
        *_base("records"),
        sa.Column("record_type_id", sa.Uuid, nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("owner_user_id", sa.Uuid),
        sa.Column("team_id", sa.Uuid),
        sa.Column("stage_id", sa.Uuid),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True)),
        sa.Column("custom_fields", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        *_ts(),
        _same_tenant("record_type_id", "record_types", "fk_records_type_same_tenant"),
        _same_tenant("owner_user_id", "users", "fk_records_owner_same_tenant"),
        _same_tenant("stage_id", "record_type_stages", "fk_records_stage_same_tenant"),
        _same_tenant("created_by_user_id", "users", "fk_records_creator_same_tenant"),
    )
    _set_null_fk("records", "team_id", "teams", "fk_records_team_same_tenant")
    op.create_index(
        "ix_records_type_created", "records", ["tenant_id", "record_type_id", "created_at"]
    )
    op.create_index(
        "ix_records_type_owner", "records", ["tenant_id", "record_type_id", "owner_user_id"]
    )

    op.create_table(
        "link_types",
        *_base("link_types"),
        sa.Column("from_type_id", sa.Uuid),  # NULL = leads
        sa.Column("to_type_id", sa.Uuid),
        sa.Column("label", sa.String(80), nullable=False),  # from → to: "Interested in"
        sa.Column("inverse_label", sa.String(80), nullable=False),  # to → from: "Interested buyers"
        sa.Column("many_to", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("many_from", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        _same_tenant("from_type_id", "record_types", "fk_link_types_from_same_tenant", "CASCADE"),
        _same_tenant("to_type_id", "record_types", "fk_link_types_to_same_tenant", "CASCADE"),
    )

    op.create_table(
        "links",
        *_base("links"),
        sa.Column("link_type_id", sa.Uuid, nullable=False),
        sa.Column("from_lead_id", sa.Uuid),
        sa.Column("from_record_id", sa.Uuid),
        sa.Column("to_lead_id", sa.Uuid),
        sa.Column("to_record_id", sa.Uuid),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("num_nonnulls(from_lead_id, from_record_id) = 1", name="one_from"),
        sa.CheckConstraint("num_nonnulls(to_lead_id, to_record_id) = 1", name="one_to"),
        _same_tenant("link_type_id", "link_types", "fk_links_type_same_tenant", "CASCADE"),
        _same_tenant("from_lead_id", "leads", "fk_links_from_lead_same_tenant", "CASCADE"),
        _same_tenant("from_record_id", "records", "fk_links_from_record_same_tenant", "CASCADE"),
        _same_tenant("to_lead_id", "leads", "fk_links_to_lead_same_tenant", "CASCADE"),
        _same_tenant("to_record_id", "records", "fk_links_to_record_same_tenant", "CASCADE"),
    )
    op.execute(
        "ALTER TABLE links ADD CONSTRAINT uq_links_once UNIQUE NULLS NOT DISTINCT "
        "(link_type_id, from_lead_id, from_record_id, to_lead_id, to_record_id)"
    )
    for col in ("from_lead_id", "from_record_id", "to_lead_id", "to_record_id"):
        op.create_index(f"ix_links_{col}", "links", [col])

    op.create_table(
        "record_type_access",
        *_base("record_type_access"),
        sa.Column("role_id", sa.Uuid, nullable=False),
        sa.Column("record_type_id", sa.Uuid, nullable=False),
        sa.Column("can_view", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("can_create", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("can_edit", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("can_delete", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("scope", sa.String(4), nullable=False, server_default="own"),
        *_ts(),
        sa.CheckConstraint("scope IN ('own', 'team', 'all')", name="scope_valid"),
        sa.UniqueConstraint("role_id", "record_type_id", name="uq_record_type_access"),
        _same_tenant("role_id", "roles", "fk_record_type_access_role_same_tenant", "CASCADE"),
        _same_tenant(
            "record_type_id", "record_types", "fk_record_type_access_type_same_tenant", "CASCADE"
        ),
    )

    # Custom fields for record types use entity "rt:<type key>".
    op.alter_column("custom_field_definitions", "entity", type_=sa.String(50))
    op.alter_column("custom_field_unique_values", "entity", type_=sa.String(50))

    # Timeline and tasks on records.
    op.alter_column("activities", "lead_id", nullable=True)
    op.add_column("activities", sa.Column("record_id", sa.Uuid))
    op.create_foreign_key(
        "fk_activities_record_same_tenant",
        "activities",
        "records",
        ["tenant_id", "record_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "activities_one_subject", "activities", "num_nonnulls(lead_id, record_id) = 1"
    )
    op.create_index("ix_activities_record_time", "activities", ["record_id", "occurred_at"])
    op.add_column("tasks", sa.Column("record_id", sa.Uuid))
    op.create_foreign_key(
        "fk_tasks_record_same_tenant",
        "tasks",
        "records",
        ["tenant_id", "record_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_tasks_record_id", "tasks", ["record_id"])

    for table in TENANT_TABLES:
        enable_tenant_rls(table)

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for key, label, icon in SYSTEM_TYPES:  # only where the CRM is already set up
            conn.execute(
                sa.text(
                    "INSERT INTO activity_types (id, tenant_id, key, label, icon, is_system, "
                    "is_loggable, is_active, fields, position) "
                    "SELECT gen_random_uuid(), :t, :key, :label, :icon, true, false, true, "
                    "'[]'::jsonb, COALESCE(MAX(position), 0) + 1 FROM activity_types "
                    "WHERE tenant_id = :t HAVING COUNT(*) > 0 ON CONFLICT DO NOTHING"
                ),
                {"t": str(tenant_id), "key": key, "label": label, "icon": icon},
            )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM activities WHERE record_id IS NOT NULL"))
        conn.execute(sa.text("DELETE FROM tasks WHERE record_id IS NOT NULL"))
        keys = [k for k, _, _ in SYSTEM_TYPES]
        conn.execute(sa.text("DELETE FROM activities WHERE type_key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM activity_types WHERE key = ANY(:k)"), {"k": keys})
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("ix_tasks_record_id", "tasks")
    op.drop_constraint("fk_tasks_record_same_tenant", "tasks")
    op.drop_column("tasks", "record_id")
    op.drop_index("ix_activities_record_time", "activities")
    op.drop_constraint("activities_one_subject", "activities")
    op.drop_constraint("fk_activities_record_same_tenant", "activities")
    op.drop_column("activities", "record_id")
    op.alter_column("activities", "lead_id", nullable=False)
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
    # Record-type custom fields go with their types (RLS hides rows from a plain DELETE).
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM custom_field_unique_values WHERE entity LIKE 'rt:%'"))
        conn.execute(sa.text("DELETE FROM custom_field_definitions WHERE entity LIKE 'rt:%'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.alter_column("custom_field_unique_values", "entity", type_=sa.String(20))
    op.alter_column("custom_field_definitions", "entity", type_=sa.String(20))

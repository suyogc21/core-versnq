"""Step 4 — tags on leads and deals, saved views, scoring rules (fit + engagement) with bands,
calculated fields, automations (WHEN / IF / THEN) and their run log

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TENANT_TABLES = ("tags", "taggings", "saved_views", "score_rules", "automations", "automation_runs")
# Frozen copy of app/modules/crm/setup.py STEP4_SYSTEM_TYPES.
SYSTEM_TYPES = [("tagged", "Tags changed", "tag")]


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


def upgrade() -> None:
    op.create_table(
        "tags",
        *_base("tags"),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("colour", sa.String(7)),
        *_ts(),
    )
    op.execute("CREATE UNIQUE INDEX uq_tags_tenant_name ON tags (tenant_id, lower(name))")
    op.create_table(
        "taggings",
        *_base("taggings"),
        sa.Column("tag_id", sa.Uuid, nullable=False),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("deal_id", sa.Uuid),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("num_nonnulls(lead_id, deal_id) = 1", name="one_subject"),
        _same_tenant("tag_id", "tags", "fk_taggings_tag_same_tenant", "CASCADE"),
        _same_tenant("lead_id", "leads", "fk_taggings_lead_same_tenant", "CASCADE"),
        _same_tenant("deal_id", "deals", "fk_taggings_deal_same_tenant", "CASCADE"),
    )
    op.execute(
        "ALTER TABLE taggings ADD CONSTRAINT uq_taggings_once "
        "UNIQUE NULLS NOT DISTINCT (tag_id, lead_id, deal_id)"
    )
    op.create_index("ix_taggings_lead", "taggings", ["lead_id"])
    op.create_index("ix_taggings_deal", "taggings", ["deal_id"])

    op.create_table(
        "saved_views",
        *_base("saved_views"),
        sa.Column("entity", sa.String(10), nullable=False),  # leads / deals
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("filters", JSONB, nullable=False, server_default="{}"),
        sa.Column("sort", sa.String(30)),
        sa.Column("direction", sa.String(4)),
        sa.Column("columns", JSONB),
        sa.Column("sharing", sa.String(10), nullable=False, server_default="private"),
        sa.Column("team_id", sa.Uuid),
        sa.Column("owner_user_id", sa.Uuid, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint("entity IN ('leads', 'deals')", name="entity_valid"),
        sa.CheckConstraint("sharing IN ('private', 'team', 'everyone')", name="sharing_valid"),
        sa.CheckConstraint("(sharing = 'team') = (team_id IS NOT NULL)", name="team_when_shared"),
        _same_tenant("owner_user_id", "users", "fk_saved_views_owner_same_tenant", "CASCADE"),
        _same_tenant("team_id", "teams", "fk_saved_views_team_same_tenant", "CASCADE"),
    )

    op.create_table(
        "score_rules",
        *_base("score_rules"),
        sa.Column("kind", sa.String(10), nullable=False),  # fit / engagement
        sa.Column("condition", JSONB),  # fit: {field, op, value}
        sa.Column("activity_type_key", sa.String(60)),  # engagement
        sa.Column("disposition", sa.String(100)),  # engagement: a call outcome value
        sa.Column("points", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint("kind IN ('fit', 'engagement')", name="kind_valid"),
        sa.CheckConstraint("points BETWEEN -1000 AND 1000", name="points_range"),
        sa.CheckConstraint(
            "(kind = 'fit') = (condition IS NOT NULL) AND "
            "(kind = 'engagement') = (activity_type_key IS NOT NULL)",
            name="shape_matches_kind",
        ),
    )

    op.create_table(
        "automations",
        *_base("automations"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("subject", sa.String(5), nullable=False),  # lead / deal
        sa.Column("trigger", JSONB, nullable=False),
        sa.Column("conditions", JSONB, nullable=False, server_default="[]"),
        sa.Column("actions", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("failures_in_row", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint("subject IN ('lead', 'deal')", name="subject_valid"),
        _same_tenant("created_by_user_id", "users", "fk_automations_creator_same_tenant"),
    )
    op.create_table(
        "automation_runs",
        *_base("automation_runs"),
        sa.Column("automation_id", sa.Uuid, nullable=False),
        sa.Column("event_id", sa.Uuid),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("deal_id", sa.Uuid),
        sa.Column("status", sa.String(8), nullable=False),  # done / skipped / failed
        sa.Column("detail", JSONB, nullable=False, server_default="[]"),
        sa.Column("error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('done', 'skipped', 'failed')", name="status_valid"),
        _same_tenant("automation_id", "automations", "fk_runs_automation_same_tenant", "CASCADE"),
    )
    op.create_index("ix_automation_runs_auto", "automation_runs", ["automation_id", "created_at"])
    op.create_index("ix_automation_runs_lead", "automation_runs", ["automation_id", "lead_id"])

    op.add_column("leads", sa.Column("fit_score", sa.Integer, nullable=False, server_default="0"))
    op.add_column(
        "leads", sa.Column("engagement_score", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column("leads", sa.Column("score_band", sa.String(4)))
    op.add_column(
        "tenant_settings",
        sa.Column("engagement_days", sa.Integer, nullable=False, server_default="30"),
    )
    op.add_column(
        "tenant_settings", sa.Column("hot_score", sa.Integer, nullable=False, server_default="50")
    )
    op.add_column(
        "tenant_settings", sa.Column("warm_score", sa.Integer, nullable=False, server_default="20")
    )
    op.add_column("custom_field_definitions", sa.Column("formula", sa.String(500)))
    op.add_column("events", sa.Column("automation_handled_at", sa.DateTime(timezone=True)))
    op.execute(
        "CREATE INDEX ix_events_automation_pending ON events (occurred_at) "
        "WHERE automation_handled_at IS NULL"
    )

    for table in TENANT_TABLES:
        enable_tenant_rls(table)

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        # Events from before automations existed are never replayed.
        conn.execute(sa.text("UPDATE events SET automation_handled_at = now()"))
        for key, label, icon in SYSTEM_TYPES:
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
    keys = [k for k, _, _ in SYSTEM_TYPES]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM activities WHERE type_key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM activity_types WHERE key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM custom_field_definitions WHERE type = 'calculated'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("ix_events_automation_pending", "events")
    op.drop_column("events", "automation_handled_at")
    op.drop_column("custom_field_definitions", "formula")
    for col in ("warm_score", "hot_score", "engagement_days"):
        op.drop_column("tenant_settings", col)
    for col in ("score_band", "engagement_score", "fit_score"):
        op.drop_column("leads", col)
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)

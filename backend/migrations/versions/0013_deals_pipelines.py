"""Step 3 — deals and pipelines: pipelines with stages (open / won / lost, win %), deals on a
lead (amount in minor units + currency), lost reasons, product catalogue and deal lines;
deals on the timeline, tasks and links; company default currency; deals.* permissions

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "pipelines",
    "pipeline_stages",
    "lost_reasons",
    "products",
    "deals",
    "deal_products",
)

PERMISSIONS = [
    ("deals.create", "crm", "Add deals"),
    ("deals.edit", "crm", "Edit visible deals, move them between stages and close them"),
    ("deals.delete", "crm", "Permanently delete deals"),
]
DEFAULT_GRANTS = {
    "admin": ["deals.create", "deals.edit", "deals.delete"],
    "sales_manager": ["deals.create", "deals.edit"],
    "sales_user": ["deals.create", "deals.edit"],
}
# Frozen copy of app/modules/crm/setup.py STEP3_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("deal_created", "Deal added", "handshake"),
    ("deal_updated", "Deal changed", "pencil"),
    ("deal_stage_changed", "Deal moved", "git-commit"),
    ("deal_won", "Deal won", "trophy"),
    ("deal_lost", "Deal lost", "circle-x"),
    ("deal_reopened", "Deal reopened", "rotate-ccw"),
    ("deal_deleted", "Deal deleted", "trash"),
]
# Frozen copy of app/core/money.py COUNTRY_CURRENCY (the common ones; others default to USD).
COUNTRY_CURRENCY = {"IN": "INR", "AE": "AED", "US": "USD", "GB": "GBP", "SG": "SGD", "AU": "AUD"}


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


def _per_tenant(*statements: str) -> None:
    """Data updates run once per company: row-level security hides other companies' rows."""
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for sql in statements:
            conn.execute(sa.text(sql))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS],
    )
    op.add_column(
        "tenant_settings",
        sa.Column("default_currency", sa.String(3), nullable=False, server_default="USD"),
    )

    op.create_table(
        "pipelines",
        *_base("pipelines"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_pipelines_tenant_name"),
    )
    op.create_table(
        "pipeline_stages",
        *_base("pipeline_stages"),
        sa.Column("pipeline_id", sa.Uuid, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(4), nullable=False, server_default="open"),
        sa.Column("probability", sa.Integer, nullable=False, server_default="0"),
        sa.Column("colour", sa.String(7)),
        sa.Column("required_fields", JSONB, nullable=False, server_default="[]"),
        *_ts(),
        sa.CheckConstraint("kind IN ('open', 'won', 'lost')", name="kind_valid"),
        sa.CheckConstraint("probability BETWEEN 0 AND 100", name="probability_valid"),
        sa.UniqueConstraint("pipeline_id", "name", name="uq_pipeline_stages_name"),
        _same_tenant(
            "pipeline_id", "pipelines", "fk_pipeline_stages_pipeline_same_tenant", "CASCADE"
        ),
    )
    op.create_table(
        "lost_reasons",
        *_base("lost_reasons"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_lost_reasons_tenant_name"),
    )
    op.create_table(
        "products",
        *_base("products"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(60)),
        sa.Column("description", sa.Text),
        sa.Column("price_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
        sa.CheckConstraint("price_minor >= 0", name="price_not_negative"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_products_tenant_code"),
    )
    op.create_table(
        "deals",
        *_base("deals"),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("pipeline_id", sa.Uuid, nullable=False),
        sa.Column("stage_id", sa.Uuid, nullable=False),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(4), nullable=False, server_default="open"),
        sa.Column("owner_user_id", sa.Uuid),
        sa.Column("team_id", sa.Uuid),
        sa.Column("amount_minor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("expected_close_on", sa.Date),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("lost_reason_id", sa.Uuid),
        sa.Column("close_note", sa.String(1000)),
        sa.Column("custom_fields", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        *_ts(),
        sa.CheckConstraint("status IN ('open', 'won', 'lost')", name="status_valid"),
        sa.CheckConstraint("amount_minor >= 0", name="amount_not_negative"),
        sa.CheckConstraint(
            "(status = 'lost') = (lost_reason_id IS NOT NULL)", name="lost_has_reason"
        ),
        sa.CheckConstraint("(status = 'open') = (closed_at IS NULL)", name="closed_at_matches"),
        _same_tenant("lead_id", "leads", "fk_deals_lead_same_tenant", "CASCADE"),
        _same_tenant("pipeline_id", "pipelines", "fk_deals_pipeline_same_tenant"),
        _same_tenant("stage_id", "pipeline_stages", "fk_deals_stage_same_tenant"),
        _same_tenant("owner_user_id", "users", "fk_deals_owner_same_tenant"),
        _same_tenant("lost_reason_id", "lost_reasons", "fk_deals_lost_reason_same_tenant"),
        _same_tenant("created_by_user_id", "users", "fk_deals_creator_same_tenant"),
    )
    _set_null_fk("deals", "team_id", "teams", "fk_deals_team_same_tenant")
    op.create_index("ix_deals_board", "deals", ["tenant_id", "pipeline_id", "stage_id"])
    op.create_index("ix_deals_owner", "deals", ["tenant_id", "owner_user_id"])
    op.create_index("ix_deals_lead", "deals", ["lead_id"])
    op.create_table(
        "deal_products",
        *_base("deal_products"),
        sa.Column("deal_id", sa.Uuid, nullable=False),
        sa.Column("product_id", sa.Uuid),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger, nullable=False),
        sa.Column("discount_minor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_minor", sa.BigInteger, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("unit_price_minor >= 0 AND discount_minor >= 0", name="not_negative"),
        sa.CheckConstraint(
            "total_minor = quantity * unit_price_minor - discount_minor AND total_minor >= 0",
            name="total_exact",
        ),
        _same_tenant("deal_id", "deals", "fk_deal_products_deal_same_tenant", "CASCADE"),
        _same_tenant("product_id", "products", "fk_deal_products_product_same_tenant"),
    )
    op.create_index("ix_deal_products_deal", "deal_products", ["deal_id"])

    # Timeline and tasks: deal entries keep their lead too, so they show on its timeline.
    for table in ("activities", "tasks"):
        op.add_column(table, sa.Column("deal_id", sa.Uuid))
        op.create_foreign_key(
            f"fk_{table}_deal_same_tenant",
            table,
            "deals",
            ["tenant_id", "deal_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_deal_id", table, ["deal_id"])

    # Links: a deal can be either end. Link types say which kind each side is.
    for side in ("from", "to"):
        op.add_column(
            "link_types",
            sa.Column(f"{side}_kind", sa.String(6), nullable=False, server_default="lead"),
        )
    _per_tenant(
        "UPDATE link_types SET from_kind = 'record' WHERE from_type_id IS NOT NULL",
        "UPDATE link_types SET to_kind = 'record' WHERE to_type_id IS NOT NULL",
        "UPDATE tenant_settings SET default_currency = CASE default_country "
        + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in COUNTRY_CURRENCY.items())
        + " ELSE 'USD' END",
    )
    for side in ("from", "to"):
        op.create_check_constraint(
            f"{side}_kind_valid",
            "link_types",
            f"{side}_kind IN ('lead', 'deal', 'record') "
            f"AND ({side}_kind = 'record') = ({side}_type_id IS NOT NULL)",
        )
        op.add_column("links", sa.Column(f"{side}_deal_id", sa.Uuid))
        op.create_foreign_key(
            f"fk_links_{side}_deal_same_tenant",
            "links",
            "deals",
            ["tenant_id", f"{side}_deal_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_links_{side}_deal_id", "links", [f"{side}_deal_id"])
        op.drop_constraint(f"one_{side}", "links")
        op.create_check_constraint(
            f"one_{side}",
            "links",
            f"num_nonnulls({side}_lead_id, {side}_record_id, {side}_deal_id) = 1",
        )
    op.drop_constraint("uq_links_once", "links")
    op.execute(
        "ALTER TABLE links ADD CONSTRAINT uq_links_once UNIQUE NULLS NOT DISTINCT (link_type_id, "
        "from_lead_id, from_record_id, from_deal_id, to_lead_id, to_record_id, to_deal_id)"
    )

    for table in TENANT_TABLES:
        enable_tenant_rls(table)

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
    codes = [c for c, _, _ in PERMISSIONS]
    keys = [k for k, _, _ in SYSTEM_TYPES]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM links WHERE from_deal_id IS NOT NULL OR to_deal_id IS NOT NULL")
        )
        conn.execute(sa.text("DELETE FROM link_types WHERE from_kind = 'deal' OR to_kind = 'deal'"))
        conn.execute(sa.text("DELETE FROM activities WHERE type_key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM activity_types WHERE key = ANY(:k)"), {"k": keys})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:codes)"),
            {"codes": codes},
        )
        conn.execute(sa.text("DELETE FROM custom_field_unique_values WHERE entity = 'deal'"))
        conn.execute(sa.text("DELETE FROM custom_field_definitions WHERE entity = 'deal'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_constraint("uq_links_once", "links")
    op.execute(
        "ALTER TABLE links ADD CONSTRAINT uq_links_once UNIQUE NULLS NOT DISTINCT "
        "(link_type_id, from_lead_id, from_record_id, to_lead_id, to_record_id)"
    )
    for side in ("from", "to"):
        op.drop_constraint(f"one_{side}", "links")
        op.create_check_constraint(
            f"one_{side}", "links", f"num_nonnulls({side}_lead_id, {side}_record_id) = 1"
        )
        op.drop_index(f"ix_links_{side}_deal_id", "links")
        op.drop_constraint(f"fk_links_{side}_deal_same_tenant", "links")
        op.drop_column("links", f"{side}_deal_id")
        op.drop_constraint(f"{side}_kind_valid", "link_types")
        op.drop_column("link_types", f"{side}_kind")
    for table in ("activities", "tasks"):
        op.drop_index(f"ix_{table}_deal_id", table)
        op.drop_constraint(f"fk_{table}_deal_same_tenant", table)
        op.drop_column(table, "deal_id")
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
    op.drop_column("tenant_settings", "default_currency")
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})

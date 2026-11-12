"""Step 7b — key accounts add-on (Decision log #31, #36): an organisation marked as a key account
(tier, owner, yearly target, health, parent for the group tree); its departments with budget
holders; competitors; the opportunity grid's manual cells (competitor / not a fit) — the rest of
the grid comes from deals, which can now name the department they are for; the people map; and
the account plan's goals. key_accounts.manage permission. Module switch, off by default.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TABLES = (
    "key_accounts",
    "account_units",
    "competitors",
    "account_cells",
    "account_contacts",
    "account_goals",
)
PERMISSION = ("key_accounts.manage", "key_accounts", "Mark key accounts and plan them")
GRANTS = ("admin", "sales_manager")
# Frozen copy of app/modules/crm/setup.py STEP7B_SYSTEM_TYPES.
SYSTEM_TYPES = [("key_account_updated", "Key account changed", "star")]


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
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), PERMISSION, strict=True))],
    )
    op.create_table(
        "key_accounts",
        *_base("key_accounts"),
        sa.Column("org_lead_id", sa.Uuid, nullable=False),
        sa.Column("tier", sa.String(10), nullable=False, server_default="growth"),
        sa.Column("owner_user_id", sa.Uuid),
        sa.Column("parent_id", sa.Uuid),
        sa.Column("target_minor", sa.BigInteger),
        sa.Column("target_currency", sa.String(3)),
        sa.Column("health", sa.String(9), nullable=False, server_default="on_track"),
        sa.Column("health_note", sa.String(500)),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        *_ts(),
        sa.CheckConstraint("tier IN ('strategic', 'growth', 'maintain')", name="tier_valid"),
        sa.CheckConstraint("health IN ('on_track', 'at_risk', 'off_track')", name="health_valid"),
        sa.CheckConstraint(
            "(target_minor IS NULL) = (target_currency IS NULL) AND "
            "(target_minor IS NULL OR target_minor >= 0)",
            name="target_valid",
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        sa.UniqueConstraint("tenant_id", "org_lead_id", name="uq_key_accounts_org"),
        _same_tenant("org_lead_id", "leads", "fk_key_accounts_org_same_tenant", "CASCADE"),
    )
    _set_null_fk("key_accounts", "owner_user_id", "users", "fk_key_accounts_owner_same_tenant")
    _set_null_fk("key_accounts", "parent_id", "key_accounts", "fk_key_accounts_parent_same_tenant")

    op.create_table(
        "account_units",
        *_base("account_units"),
        sa.Column("account_id", sa.Uuid, nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("budget_holder_lead_id", sa.Uuid),
        sa.Column("budget_minor", sa.BigInteger),
        sa.Column("budget_currency", sa.String(3)),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint(
            "(budget_minor IS NULL) = (budget_currency IS NULL) AND "
            "(budget_minor IS NULL OR budget_minor >= 0)",
            name="budget_valid",
        ),
        sa.UniqueConstraint("account_id", "name", name="uq_account_units_name"),
        _same_tenant(
            "account_id", "key_accounts", "fk_account_units_account_same_tenant", "CASCADE"
        ),
    )
    _set_null_fk(
        "account_units", "budget_holder_lead_id", "leads", "fk_account_units_holder_same_tenant"
    )

    op.create_table(
        "competitors",
        *_base("competitors"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("website", sa.String(300)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_competitors_name"),
    )

    op.create_table(
        "account_cells",
        *_base("account_cells"),
        sa.Column("account_id", sa.Uuid, nullable=False),
        sa.Column("unit_id", sa.Uuid, nullable=False),
        sa.Column("product_id", sa.Uuid, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("competitor_id", sa.Uuid),
        sa.Column("note", sa.String(300)),
        *_ts(),
        sa.CheckConstraint("status IN ('competitor', 'not_fit')", name="status_valid"),
        sa.UniqueConstraint("unit_id", "product_id", name="uq_account_cells_pair"),
        _same_tenant(
            "account_id", "key_accounts", "fk_account_cells_account_same_tenant", "CASCADE"
        ),
        _same_tenant("unit_id", "account_units", "fk_account_cells_unit_same_tenant", "CASCADE"),
        _same_tenant("product_id", "products", "fk_account_cells_product_same_tenant", "CASCADE"),
    )
    _set_null_fk(
        "account_cells", "competitor_id", "competitors", "fk_account_cells_competitor_same_tenant"
    )

    op.create_table(
        "account_contacts",
        *_base("account_contacts"),
        sa.Column("account_id", sa.Uuid, nullable=False),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("unit_id", sa.Uuid),
        sa.Column("role", sa.String(14), nullable=False, server_default="influencer"),
        sa.Column("stance", sa.String(9), nullable=False, server_default="neutral"),
        sa.Column("strength", sa.Integer, nullable=False, server_default="3"),
        sa.Column("note", sa.String(300)),
        *_ts(),
        sa.CheckConstraint(
            "role IN ('decision_maker', 'influencer', 'user', 'gatekeeper')", name="role_valid"
        ),
        sa.CheckConstraint(
            "stance IN ('champion', 'supporter', 'neutral', 'blocker')", name="stance_valid"
        ),
        sa.CheckConstraint("strength BETWEEN 1 AND 5", name="strength_valid"),
        sa.UniqueConstraint("account_id", "lead_id", name="uq_account_contacts_pair"),
        _same_tenant(
            "account_id", "key_accounts", "fk_account_contacts_account_same_tenant", "CASCADE"
        ),
        _same_tenant("lead_id", "leads", "fk_account_contacts_lead_same_tenant", "CASCADE"),
    )
    _set_null_fk(
        "account_contacts", "unit_id", "account_units", "fk_account_contacts_unit_same_tenant"
    )

    op.create_table(
        "account_goals",
        *_base("account_goals"),
        sa.Column("account_id", sa.Uuid, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("target_minor", sa.BigInteger),
        sa.Column("currency", sa.String(3)),
        sa.Column("due_on", sa.Date),
        sa.Column("status", sa.String(6), nullable=False, server_default="open"),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint("status IN ('open', 'done', 'missed')", name="status_valid"),
        sa.CheckConstraint(
            "(target_minor IS NULL) = (currency IS NULL) AND "
            "(target_minor IS NULL OR target_minor >= 0)",
            name="target_valid",
        ),
        _same_tenant(
            "account_id", "key_accounts", "fk_account_goals_account_same_tenant", "CASCADE"
        ),
    )

    op.add_column("deals", sa.Column("account_unit_id", sa.Uuid))
    _set_null_fk("deals", "account_unit_id", "account_units", "fk_deals_unit_same_tenant")
    op.create_index("ix_deals_account_unit", "deals", ["account_unit_id"])

    for table in TABLES:
        enable_tenant_rls(table)

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for key in GRANTS:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                    "SELECT tenant_id, id, :code FROM roles WHERE key = :key "
                    "ON CONFLICT DO NOTHING"
                ),
                {"code": PERMISSION[0], "key": key},
            )
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
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = :c"), {"c": PERMISSION[0]}
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("ix_deals_account_unit", "deals")
    op.drop_constraint("fk_deals_unit_same_tenant", "deals")
    op.drop_column("deals", "account_unit_id")
    for table in reversed(TABLES):
        disable_tenant_rls(table)
    for table in reversed(TABLES):
        op.drop_table(table)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": PERMISSION[0]})

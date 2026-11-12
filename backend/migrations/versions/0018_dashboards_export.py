"""Step 7 — dashboards and CSV export (Decision log #35): permissions for the Team, Business
and Money dashboards, and one export permission per list (default Owner and Admin only; the
admin grants them in Roles). No new tables: every number comes from existing data.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("dashboards.team", "crm", "See the team dashboard (funnel, sources, leaderboard)"),
    ("dashboards.business", "crm", "See the business dashboard (revenue, collections, trend)"),
    ("dashboards.money", "money", "See the money dashboard (invoiced, collected, aging)"),
    ("leads.export", "crm", "Export leads to a CSV file"),
    ("deals.export", "crm", "Export deals to a CSV file"),
    ("customers.export", "crm", "Export customers to a CSV file"),
    ("invoices.export", "money", "Export invoices and payments to a CSV file"),
]
CODES = [c for c, _, _ in PERMISSIONS]
DEFAULT_GRANTS = {
    "admin": CODES,
    "sales_manager": ["dashboards.team"],
    "finance": ["dashboards.money"],
}


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS],
    )
    op.create_index(
        "ix_activities_type_time", "activities", ["tenant_id", "type_key", "occurred_at"]
    )
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
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:codes)"),
            {"codes": CODES},
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("ix_activities_type_time", "activities")
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": CODES})

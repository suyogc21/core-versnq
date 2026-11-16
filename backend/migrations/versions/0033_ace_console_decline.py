"""ACE asks C13 and C14 (docs/plans/ace-c13-c14-plan.md, approved Nov 16).

C14: draft_requests.declined_at / decline_reason (ACE declines to draft, with a reason).
C13: permissions ace.use (people: Open ACE; Owner and Admin by default) and ace.console_login
(only for the role of ACE's key, never granted by default). The one-time sign-in codes live in
Redis only.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("ace.use", "settings", "Open ACE's console (signed in with Core)"),
    ("ace.console_login", "settings",
     "Sign people in to ACE's console with their one-time code (only for ACE's key)"),
]  # fmt: skip
GRANTS = {"admin": ["ace.use"]}


def upgrade() -> None:
    op.add_column("draft_requests", sa.Column("declined_at", sa.DateTime(timezone=True)))
    op.add_column("draft_requests", sa.Column("decline_reason", sa.String(500)))
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
    )
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for role, codes in GRANTS.items():
            for code in codes:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                        "SELECT tenant_id, id, :code FROM roles WHERE key = :key "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"code": code, "key": role},
                )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    conn = op.get_bind()
    codes = [c for c, _, _ in PERMISSIONS]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:c)"), {"c": codes}
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:c)"), {"c": codes})
    op.drop_column("draft_requests", "decline_reason")
    op.drop_column("draft_requests", "declined_at")

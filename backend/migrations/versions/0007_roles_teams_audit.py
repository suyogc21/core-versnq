"""permission catalogue, role permissions, teams, team members, tenant audit log

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

APP_ROLE = "versnq_app"
TENANT_TABLES = ("role_permissions", "teams", "team_members", "audit_log")

# Frozen copy for this migration; later codes arrive in later migrations.
PERMISSIONS = [
    ("users.read", "users", "See team members"),
    ("users.manage", "users", "Invite, edit and disable users"),
    ("roles.manage", "users", "Create and edit roles"),
    ("teams.manage", "users", "Create teams and set their members"),
    ("settings.manage", "settings", "Change workspace settings"),
    ("audit.read", "settings", "View the audit log"),
]
DEFAULT_GRANTS = {
    "admin": [code for code, _, _ in PERMISSIONS],
    "sales_manager": ["users.read"],
    "finance": ["audit.read"],
}


def _ts() -> list[sa.Column]:
    now = sa.func.now()
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def upgrade() -> None:
    permissions = op.create_table(
        "permissions",
        sa.Column("code", sa.String(60), primary_key=True),
        sa.Column("module", sa.String(40), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
    )
    op.bulk_insert(
        permissions, [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS]
    )

    op.create_table(
        "role_permissions",
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("role_id", sa.Uuid, primary_key=True),
        sa.Column(
            "permission_code", sa.String(60), sa.ForeignKey("permissions.code"), primary_key=True
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_role_permissions_role_same_tenant",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("parent_team_id", sa.Uuid),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "id", name="uq_teams_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_teams_tenant_name"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_team_id"],
            ["teams.tenant_id", "teams.id"],
            name="fk_teams_parent_same_tenant",
        ),
    )

    op.create_table(
        "team_members",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("team_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("is_manager", sa.Boolean, nullable=False, server_default=sa.false()),
        *_ts(),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["teams.tenant_id", "teams.id"],
            name="fk_team_members_team_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_team_members_user_same_tenant",
        ),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_type", sa.String(10), nullable=False),
        sa.Column("actor_id", sa.Uuid),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.Uuid),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB),
        sa.Column("ip", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])

    for table in TENANT_TABLES:
        enable_tenant_rls(table)
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {APP_ROLE}")

    # Backfill default grants for tenants created before this migration.
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for key, codes in DEFAULT_GRANTS.items():
            for code in codes:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                        "SELECT tenant_id, id, :code FROM roles WHERE key = :key"
                    ),
                    {"code": code, "key": key},
                )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    op.drop_table("audit_log")
    op.drop_table("team_members")
    op.drop_table("teams")
    op.drop_table("role_permissions")
    op.drop_table("permissions")

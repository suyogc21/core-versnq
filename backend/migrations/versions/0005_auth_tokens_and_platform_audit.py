"""auth tokens (invites, resets) and the append-only platform audit log

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "versnq_app"  # created by docker/postgres/init; must exist in every environment


def upgrade() -> None:
    op.create_unique_constraint("uq_users_tenant_id_id", "users", ["tenant_id", "id"])

    now = sa.func.now()
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_auth_tokens_user_same_tenant",
        ),
        sa.CheckConstraint("kind IN ('invite', 'reset')", name="kind_valid"),
    )
    enable_tenant_rls("auth_tokens")

    op.create_table(
        "platform_audit_log",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("staff_id", sa.Uuid, sa.ForeignKey("platform_staff.id")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.Uuid),
        sa.Column("tenant_slug_snapshot", sa.String(30)),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB),
        sa.Column("ip", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    )
    op.create_index("ix_platform_audit_log_target_id", "platform_audit_log", ["target_id"])
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON platform_audit_log FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("platform_audit_log")
    disable_tenant_rls("auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_constraint("uq_users_tenant_id_id", "users", type_="unique")

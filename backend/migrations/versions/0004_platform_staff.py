"""platform staff accounts and sessions

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    now = sa.func.now()
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "platform_staff",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("totp_secret_enc", sa.Text),
        sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index(
        "uq_platform_staff_email", "platform_staff", [sa.text("lower(email)")], unique=True
    )

    op.create_table(
        "platform_staff_sessions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("staff_id", sa.Uuid, sa.ForeignKey("platform_staff.id"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(400)),
        *_timestamps(),
    )
    op.create_index("ix_platform_staff_sessions_staff_id", "platform_staff_sessions", ["staff_id"])

    op.create_foreign_key(
        "fk_tenants_created_by_staff", "tenants", "platform_staff", ["created_by_staff_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_tenants_created_by_staff", "tenants", type_="foreignkey")
    op.drop_table("platform_staff_sessions")
    op.drop_table("platform_staff")

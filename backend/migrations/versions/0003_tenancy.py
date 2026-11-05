"""tenants, tenant settings, roles and users (RLS on every tenant table)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TENANT_TABLES = ("tenant_settings", "roles", "users")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(30), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("industry_pack", sa.String(40), nullable=False),
        sa.Column("created_by_staff_id", sa.Uuid),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="status_valid"),
    )

    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("labels", JSONB, nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("default_country", sa.String(2), nullable=False),
        sa.Column("branding", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("key", sa.String(40)),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
        sa.CheckConstraint("scope IN ('own', 'team', 'all')", name="scope_valid"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("password_hash", sa.Text),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("role_id", sa.Uuid, nullable=False),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("totp_secret_enc", sa.Text),
        sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_users_role_same_tenant",
        ),
        sa.CheckConstraint("status IN ('invited', 'active', 'disabled')", name="status_valid"),
    )
    op.create_index(
        "uq_users_tenant_email", "users", ["tenant_id", sa.text("lower(email)")], unique=True
    )

    for table in TENANT_TABLES:
        enable_tenant_rls(table)


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("tenant_settings")
    op.drop_table("tenants")

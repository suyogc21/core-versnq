"""Go-live G-4 — lost phone: one-time backup codes for the authenticator app.

user_recovery_codes (a company person's; forced row security) and staff_recovery_codes (Versnq
staff's; platform table, no company). Each code is stored as a keyed hash and works once.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "user_recovery_codes",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_user_recovery_codes_user",
            ondelete="CASCADE",
        ),  # fmt: skip
        sa.UniqueConstraint("tenant_id", "code_hash", name="uq_user_recovery_codes_hash"),
    )
    op.create_index("ix_user_recovery_codes_user", "user_recovery_codes", ["tenant_id", "user_id"])
    enable_tenant_rls("user_recovery_codes")
    op.create_table(
        "staff_recovery_codes",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "staff_id",
            sa.Uuid,
            sa.ForeignKey("platform_staff.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),  # fmt: skip
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("staff_recovery_codes")
    disable_tenant_rls("user_recovery_codes")
    op.drop_table("user_recovery_codes")

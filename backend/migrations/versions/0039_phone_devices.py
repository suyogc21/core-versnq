"""The Android app's phone key (calls plan C4.2, approved by Suyog Nov 16).

phone_devices: one row per rep's phone with the app. Its token (`vq_app_…`, stored hashed) only
reports that rep's calls, uploads their recordings, and reads its own status; the rep or an
admin can remove it (a lost phone, a rep who leaves). Reconnecting the same install replaces
the old token.

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phone_devices",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("token_hash", sa.String(64)),
        sa.Column("install_id", sa.String(64), nullable=False),
        sa.Column("device", sa.String(120)),
        sa.Column("version", sa.String(20)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("last_call_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_phone_devices_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_phone_devices_user_same_tenant",
            ondelete="CASCADE",
        ),  # fmt: skip
    )
    op.create_index("uq_phone_devices_token", "phone_devices", ["token_hash"], unique=True)
    op.create_index("ix_phone_devices_user", "phone_devices", ["tenant_id", "user_id"])
    enable_tenant_rls("phone_devices")


def downgrade() -> None:
    disable_tenant_rls("phone_devices")
    op.drop_table("phone_devices")

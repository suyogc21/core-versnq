"""Phone notifications (calls plan, step C2; pywebpush approved by Suyog, Nov 16).

push_subscriptions: one row per browser/phone a person turned notifications on (the endpoint
and its two keys, from the browser). notifications.pushed_at: when the in-app notification was
also sent to the person's phones (null = not yet; old ones are never sent).

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("pushed_at", sa.DateTime(timezone=True)))
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("endpoint", sa.String(1000), nullable=False),
        sa.Column("p256dh", sa.String(200), nullable=False),
        sa.Column("auth", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "id", name="uq_push_subscriptions_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "endpoint", name="uq_push_subscriptions_endpoint"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_push_subscriptions_user",
            ondelete="CASCADE",
        ),  # fmt: skip
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["tenant_id", "user_id"])
    enable_tenant_rls("push_subscriptions")


def downgrade() -> None:
    disable_tenant_rls("push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_column("notifications", "pushed_at")

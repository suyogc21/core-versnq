"""tenant module switches and the events outbox (both RLS)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "tenant_modules",
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("module_key", sa.String(40), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("type", sa.String(60), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_events_unpublished",
        "events",
        ["occurred_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    enable_tenant_rls("tenant_modules")
    enable_tenant_rls("events")


def downgrade() -> None:
    disable_tenant_rls("events")
    disable_tenant_rls("tenant_modules")
    op.drop_table("events")
    op.drop_table("tenant_modules")

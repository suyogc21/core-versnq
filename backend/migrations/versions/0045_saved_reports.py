"""Custom reports (finishing plan, batch 5c; approved by Suyog Nov 16).

saved_reports: a report someone saved (source, filters, grouping, measure, chart), private or
shared with roles. Whoever opens a shared report sees only what they may see themselves.

Revision ID: 0045
Revises: 0042 (re-chained at merge)
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "saved_reports",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("definition", JSONB, nullable=False),
        sa.Column("shared_role_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_saved_reports_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_saved_reports_owner_same_tenant",
            ondelete="CASCADE",
        ),  # fmt: skip
    )
    op.create_index("ix_saved_reports_owner", "saved_reports", ["tenant_id", "owner_user_id"])
    enable_tenant_rls("saved_reports")


def downgrade() -> None:
    disable_tenant_rls("saved_reports")
    op.drop_table("saved_reports")

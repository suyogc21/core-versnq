"""Customers no longer upload through a link (Decision log #33): only staff upload documents
and enter details. Drops the customer links, the files' "uploaded via link" columns, the link
validity setting and the "Submitted by the customer" activity type.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _per_tenant(*statements: str) -> None:
    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for sql in statements:
            conn.execute(sa.text(sql))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def upgrade() -> None:
    _per_tenant(
        "DELETE FROM activities WHERE type_key = 'customer_submitted'",
        "DELETE FROM activity_types WHERE key = 'customer_submitted'",
        "DELETE FROM notifications WHERE kind = 'customer_submitted'",
    )
    op.drop_constraint("link_only_via_link", "files")
    op.drop_constraint("via_valid", "files")
    op.drop_constraint("fk_files_link_same_tenant", "files")
    op.drop_column("files", "link_id")
    op.drop_column("files", "uploaded_via")
    disable_tenant_rls("customer_links")
    op.drop_table("customer_links")
    op.drop_constraint("customer_settings_valid", "tenant_settings")
    op.drop_column("tenant_settings", "link_days")
    op.create_check_constraint(
        "customer_settings_valid",
        "tenant_settings",
        "next_customer_number >= 1 AND document_reminder_days BETWEEN 1 AND 60 "
        "AND storage_quota_bytes > 0",
    )


def downgrade() -> None:
    op.drop_constraint("customer_settings_valid", "tenant_settings")
    op.add_column(
        "tenant_settings",
        sa.Column("link_days", sa.Integer, nullable=False, server_default="14"),
    )
    op.create_check_constraint(
        "customer_settings_valid",
        "tenant_settings",
        "next_customer_number >= 1 AND link_days BETWEEN 1 AND 90 "
        "AND document_reminder_days BETWEEN 1 AND 60 AND storage_quota_bytes > 0",
    )
    now = sa.func.now()
    op.create_table(
        "customer_links",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid, nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("field_keys", JSONB, nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customer_links_tenant_id_id"),
        sa.UniqueConstraint("code_hash", name="uq_customer_links_code"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_links_customer_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_customer_links_creator_same_tenant",
        ),
    )
    op.create_index("ix_customer_links_customer", "customer_links", ["customer_id"])
    enable_tenant_rls("customer_links")
    op.add_column(
        "files", sa.Column("uploaded_via", sa.String(4), nullable=False, server_default="user")
    )
    op.add_column("files", sa.Column("link_id", sa.Uuid))
    op.execute(
        "ALTER TABLE files ADD CONSTRAINT fk_files_link_same_tenant FOREIGN KEY (tenant_id, "
        "link_id) REFERENCES customer_links (tenant_id, id) ON DELETE SET NULL (link_id)"
    )
    op.create_check_constraint("via_valid", "files", "uploaded_via IN ('user', 'link')")
    op.create_check_constraint(
        "link_only_via_link", "files", "uploaded_via = 'link' OR link_id IS NULL"
    )

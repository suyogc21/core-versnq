"""Step 9b-3 — connect my inbox (Decision log #40).

mailboxes (one per user: IMAP + SMTP settings, the app password encrypted, sync position per
folder, status); messages gain the mailbox they were synced from or sent through; tenant
settings gain the exclusion list (addresses and domains never synced). Permission
mailboxes.manage (admins: exclusions, see who is connected, disconnect, remove synced emails).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("mailboxes.manage", "settings", "See connected inboxes, set the exclusion list"),
]
GRANTS = {"admin": ["mailboxes.manage"]}


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
    )
    now = sa.func.now()
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("email_address", sa.String(254), nullable=False),
        sa.Column("username", sa.String(254), nullable=False),
        sa.Column("password_enc", sa.Text),  # wiped on disconnect
        sa.Column("imap_host", sa.String(255), nullable=False),
        sa.Column("imap_port", sa.Integer, nullable=False),
        sa.Column("smtp_host", sa.String(255), nullable=False),
        sa.Column("smtp_port", sa.Integer, nullable=False),
        sa.Column("smtp_security", sa.String(8), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="active"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("sync_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("sync_state", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_mailboxes_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_mailboxes_user"),
        sa.CheckConstraint("status IN ('active', 'error', 'off')", name="status_valid"),
        sa.CheckConstraint("smtp_security IN ('ssl', 'starttls')", name="security_valid"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_mailboxes_user_same_tenant",
            ondelete="CASCADE",
        ),
    )
    enable_tenant_rls("mailboxes")

    op.add_column("messages", sa.Column("mailbox_id", sa.Uuid))
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT fk_messages_mailbox_same_tenant "
        "FOREIGN KEY (tenant_id, mailbox_id) REFERENCES mailboxes (tenant_id, id) "
        "ON DELETE SET NULL (mailbox_id)"
    )
    op.create_index("ix_messages_mailbox", "messages", ["tenant_id", "mailbox_id"])
    op.add_column(
        "tenant_settings",
        sa.Column("mail_exclusions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for role, codes in GRANTS.items():
            for code in codes:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                        "SELECT tenant_id, id, :code FROM roles WHERE key = :key "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"code": code, "key": role},
                )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    conn = op.get_bind()
    codes = [c for c, _, _ in PERMISSIONS]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:c)"), {"c": codes}
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_column("tenant_settings", "mail_exclusions")
    op.drop_index("ix_messages_mailbox", "messages")
    op.execute("ALTER TABLE messages DROP CONSTRAINT fk_messages_mailbox_same_tenant")
    op.drop_column("messages", "mailbox_id")
    disable_tenant_rls("mailboxes")
    op.drop_table("mailboxes")
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:c)"), {"c": codes})

"""Newsletters (finishing plan, batch 5b; approved by Suyog Nov 16).

newsletters: one email to many people (a saved view, tags, customers), scheduled or sent now,
through the company's own inboxes within their daily limits, or Postmark's broadcast stream.
newsletter_sends: one row per person; opens, clicks, unsubscribes and bounces live on its
message, with the same tracking, unsubscribe link and suppression list as every email.
Permission newsletters.manage (Admin, Sales Manager).

Revision ID: 0044
Revises: 0042
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0044"
down_revision = "0042"
branch_labels = None
depends_on = None

PERMISSIONS = [("newsletters.manage", "crm", "Write and send newsletters")]
GRANTS = {"admin": ["newsletters.manage"], "sales_manager": ["newsletters.manage"]}


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "newsletters",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("preheader", sa.String(200)),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("path", sa.String(10), nullable=False, server_default="mailboxes"),
        sa.Column("mailbox_id", sa.Uuid),
        sa.Column("from_name", sa.String(120)),
        sa.Column("from_email", sa.String(254)),
        sa.Column("audience", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("send_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_newsletters_tenant_id_id"),
    )
    op.create_index("ix_newsletters_due", "newsletters", ["tenant_id", "status", "send_at"])
    op.create_table(
        "newsletter_sends",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "newsletter_id",
            sa.Uuid,
            sa.ForeignKey("newsletters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("reason", sa.String(300)),
        sa.Column("message_id", sa.Uuid),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("newsletter_id", "lead_id", name="uq_newsletter_sends_lead"),
    )
    op.create_index("ix_newsletter_sends_queue", "newsletter_sends", ["newsletter_id", "status"])
    op.create_index("ix_newsletter_sends_message", "newsletter_sends", ["message_id"])
    for table in ("newsletters", "newsletter_sends"):
        enable_tenant_rls(table)

    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
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
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:c)"), {"c": codes})
    for table in ("newsletter_sends", "newsletters"):
        disable_tenant_rls(table)
        op.drop_table(table)

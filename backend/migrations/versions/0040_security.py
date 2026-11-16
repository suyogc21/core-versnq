"""Security (finishing plan, batch 1; approved by Suyog Nov 16).

sign_ins: every sign-in attempt to a company (success or failure, how, from where), kept 180 days,
for login history. tenant_settings.security: idle sign-out minutes, IP allowlist, failed sign-in
alerts. data_exports: a company's "export everything" zips (built by the worker, kept 7 days).
leads.erased_at: a person erased on request (DPDP / GDPR); the row stays, anonymised, because
invoices and payments must be kept for tax law.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def _base() -> list:
    return [
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
    ]


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "sign_ins",
        *_base(),
        sa.Column("user_id", sa.Uuid),  # null when the email matched no one
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("method", sa.String(20), nullable=False),  # password, email_code, app_code…
        sa.Column("reason", sa.String(40)),  # why it failed
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(400)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    )
    op.create_index("ix_sign_ins_user", "sign_ins", ["tenant_id", "user_id", "created_at"])
    op.create_index("ix_sign_ins_time", "sign_ins", ["tenant_id", "created_at"])

    op.create_table(
        "data_exports",
        *_base(),
        sa.Column("requested_by_user_id", sa.Uuid, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),  # queued, running, ready, failed
        sa.Column("path", sa.String(300)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("error", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    for table in ("sign_ins", "data_exports"):
        enable_tenant_rls(table)

    op.add_column(
        "tenant_settings",
        sa.Column("security", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("leads", sa.Column("erased_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("leads", "erased_at")
    op.drop_column("tenant_settings", "security")
    for table in ("sign_ins", "data_exports"):
        disable_tenant_rls(table)
        op.drop_table(table)

"""Calling with the company's own Twilio (calls plan, step C3, approved Nov 16).

calling_accounts: the company's own calling account (Twilio now; Exotel later the same way):
account id, the auth token (encrypted like WhatsApp's), the company's numbers, and where an
unanswered incoming call goes (the company's main number). calls.recording_pending_url: the
provider's link to a recording not fetched yet (the worker fetches it, then clears it).

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("recording_pending_url", sa.String(500)))
    op.create_table(
        "calling_accounts",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(10), nullable=False),
        sa.Column("account_sid", sa.String(64), nullable=False),
        sa.Column("auth_token_enc", sa.Text, nullable=False),
        sa.Column("numbers", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("forward_to", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_calling_accounts_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_calling_accounts_provider"),
        sa.CheckConstraint("provider IN ('twilio')", name="provider_valid"),
    )
    enable_tenant_rls("calling_accounts")


def downgrade() -> None:
    disable_tenant_rls("calling_accounts")
    op.drop_table("calling_accounts")
    op.drop_column("calls", "recording_pending_url")

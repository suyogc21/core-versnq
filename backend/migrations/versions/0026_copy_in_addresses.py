"""Step 9b-2 — copy-in addresses (Decision log #40).

copy_in_addresses: one secret address per company (user_id empty) and one per user. CC / BCC it
on any email, or auto-forward to it, and the email lands on the right lead. The address is
<company slug>-<token>@<INBOUND_EMAIL_DOMAIN>; the token is looked up only inside that company.
tenant_settings.copy_in: {"create_leads": false, "source_id": null} — whether an email with an
unknown person creates a lead (I3: off by default), and with which source.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copy_in_addresses",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Uuid),  # empty: the company's address
        sa.Column("token", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_copy_in_addresses_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "token", name="uq_copy_in_addresses_token"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_copy_in_addresses_user_same_tenant",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_copy_in_addresses_user",
        "copy_in_addresses",
        ["tenant_id", sa.text("coalesce(user_id, '00000000-0000-0000-0000-000000000000'::uuid)")],
        unique=True,
    )
    enable_tenant_rls("copy_in_addresses")
    op.add_column(
        "tenant_settings",
        sa.Column(
            "copy_in",
            JSONB,
            nullable=False,
            server_default=sa.text('\'{"create_leads": false, "source_id": null}\'::jsonb'),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "copy_in")
    disable_tenant_rls("copy_in_addresses")
    op.drop_index("uq_copy_in_addresses_user", "copy_in_addresses")
    op.drop_table("copy_in_addresses")

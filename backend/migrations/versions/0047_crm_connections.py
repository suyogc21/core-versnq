"""Connect any CRM (docs/plans/crm-connectors-plan.md; approved by Suyog Nov 16).

- crm_connections: the company's connected CRM (one per company): Custom CRM (the company's own
  addresses, signed) or LeadSquared (region host, keys encrypted), what to send, a cursor over
  Core's events, the last error.
- crm_syncs: one per call or WhatsApp message sent to that CRM (the event id makes a repeat
  harmless): the CRM's lead and activity ids, status, tries, next try, last error.
The lead's id in the connected CRM goes in the existing external_refs table (system = provider).

The "Calls + WhatsApp" plan is a module switch (crm_screens), so it needs no column here.

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

TABLES = ("crm_connections", "crm_syncs")


def _base(table: str) -> list:
    return [
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id_id"),
    ]


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "crm_connections",
        *_base("crm_connections"),
        sa.Column("provider", sa.String(20), nullable=False),  # custom / leadsquared
        sa.Column("host", sa.String(200)),  # leadsquared: the region's API host
        sa.Column("secret_enc", sa.Text, nullable=False),  # keys (JSON) or signing secret
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("cursor_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_crm_connections_tenant"),
        sa.CheckConstraint("provider IN ('custom', 'leadsquared')", name="provider_valid"),
    )
    op.create_table(
        "crm_syncs",
        *_base("crm_syncs"),
        sa.Column("connection_id", sa.Uuid, nullable=False),
        sa.Column("event_id", sa.Uuid, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),  # call / whatsapp
        sa.Column("ref_id", sa.Uuid, nullable=False),  # the call or the message
        sa.Column("lead_id", sa.Uuid),
        sa.Column("external_lead_id", sa.String(100)),
        sa.Column("external_activity_id", sa.String(100)),
        sa.Column("status", sa.String(10), nullable=False),  # pending / sent / skipped / failed
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_try_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(300)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "event_id", name="uq_crm_syncs_event"),
        sa.CheckConstraint("kind IN ('call', 'whatsapp')", name="kind_valid"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'skipped', 'failed')", name="status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["crm_connections.tenant_id", "crm_connections.id"],
            name="fk_crm_syncs_connection_same_tenant",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_crm_syncs_due", "crm_syncs", ["tenant_id", "status", "next_try_at"])
    for table in TABLES:
        enable_tenant_rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)

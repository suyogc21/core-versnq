"""Zoho CRM as a connected CRM (docs/plans/crm-connectors-plan.md; approved Nov 16):
crm_connections.provider may be 'zoho' (Self Client id, secret and refresh token, encrypted).

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("provider_valid", "crm_connections", type_="check")
    op.create_check_constraint(
        "provider_valid",
        "crm_connections",
        "provider IN ('custom', 'leadsquared', 'hubspot', 'zoho')",
    )


def downgrade() -> None:
    conn = op.get_bind()  # rows are per company (forced row-level security)
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM crm_connections WHERE provider = 'zoho'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_constraint("provider_valid", "crm_connections", type_="check")
    op.create_check_constraint(
        "provider_valid", "crm_connections", "provider IN ('custom', 'leadsquared', 'hubspot')"
    )

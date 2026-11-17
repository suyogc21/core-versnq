"""HubSpot as a connected CRM (docs/plans/crm-connectors-plan.md; approved Nov 16 as the next
CRM): crm_connections.provider may be 'hubspot' (its Service Key, encrypted, in secret_enc).

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("provider_valid", "crm_connections", type_="check")
    op.create_check_constraint(
        "provider_valid", "crm_connections", "provider IN ('custom', 'leadsquared', 'hubspot')"
    )


def downgrade() -> None:
    conn = op.get_bind()  # rows are per company (forced row-level security)
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM crm_connections WHERE provider = 'hubspot'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_constraint("provider_valid", "crm_connections", type_="check")
    op.create_check_constraint(
        "provider_valid", "crm_connections", "provider IN ('custom', 'leadsquared')"
    )

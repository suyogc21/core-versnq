"""Call notes to the connected CRM (Nov 17, Suyog: "build both"): a call's recording link, and
ACE's summary with the next step, are sent to the lead in the company's CRM. crm_syncs may now
be of kind 'recording' or 'summary' as well.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_valid", "crm_syncs", type_="check")
    op.create_check_constraint(
        "kind_valid", "crm_syncs", "kind IN ('call', 'whatsapp', 'recording', 'summary')"
    )


def downgrade() -> None:
    conn = op.get_bind()  # rows are per company (forced row-level security)
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM crm_syncs WHERE kind IN ('recording', 'summary')"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_constraint("kind_valid", "crm_syncs", type_="check")
    op.create_check_constraint("kind_valid", "crm_syncs", "kind IN ('call', 'whatsapp')")

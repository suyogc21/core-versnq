"""Scale: fast "contains" search on names and phone/email at lakhs of rows. Trigram indexes
(Postgres pg_trgm, a trusted built-in extension) let LIKE / ILIKE '%term%' use an index instead
of reading every row. Plus one index for the dashboards' "new leads" count (assigned, or created
if never assigned). No table changes.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-12
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_leads_display_name_trgm", "leads", "display_name"),
    ("ix_leads_org_name_trgm", "leads", "org_name"),
    ("ix_lead_identities_value_trgm", "lead_identities", "value_normalized"),
    ("ix_deals_name_trgm", "deals", "name"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} USING gin ({column} gin_trgm_ops)")
    op.execute(
        "CREATE INDEX ix_leads_reached ON leads (tenant_id, (coalesce(assigned_at, created_at)))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_leads_reached")
    for name, _, _ in INDEXES:
        op.execute(f"DROP INDEX {name}")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")

"""tenant context function used by every RLS policy

app_current_tenant() returns the tenant set for the current transaction, or
NULL when none is set. NULLIF matters: after a transaction-local setting ends,
Postgres leaves '' (not NULL) on the connection, and ''::uuid would raise.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION app_current_tenant()")

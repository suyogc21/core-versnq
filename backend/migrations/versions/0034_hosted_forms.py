"""Real forms (docs/plans/forms-plan.md, approved Nov 16): a form builder and a hosted page.

capture_sources gets public_id (the short random id in the page link; the secret key stays
secret), form (fields, consent, thank-you or redirect, look) and hosted (the page is on).

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("capture_sources", sa.Column("public_id", sa.String(16)))
    op.add_column("capture_sources", sa.Column("form", JSONB))
    op.add_column(
        "capture_sources",
        sa.Column("hosted", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_unique_constraint("uq_capture_sources_public_id", "capture_sources", ["public_id"])


def downgrade() -> None:
    op.drop_constraint("uq_capture_sources_public_id", "capture_sources", type_="unique")
    op.drop_column("capture_sources", "hosted")
    op.drop_column("capture_sources", "form")
    op.drop_column("capture_sources", "public_id")

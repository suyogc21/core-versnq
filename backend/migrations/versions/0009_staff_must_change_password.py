"""platform staff: must_change_password (temporary passwords for new staff)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_staff",
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("platform_staff", "must_change_password")

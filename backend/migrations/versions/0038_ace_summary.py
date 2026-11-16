"""ACE's lead summary (ACE step 1, asked by ACE, approved by Suyog Nov 16).

leads.ace_summary / ace_next_step / ace_prompt_version / ace_summary_at: the latest summary ACE
wrote, shown as a panel at the top of the lead. Not a custom field and not on the timeline, so a
refresh never adds a timeline line or clashes with a rep editing the lead.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("ace_summary", sa.String(600)))
    op.add_column("leads", sa.Column("ace_next_step", sa.String(200)))
    op.add_column("leads", sa.Column("ace_prompt_version", sa.String(50)))
    op.add_column("leads", sa.Column("ace_summary_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for col in ("ace_summary_at", "ace_prompt_version", "ace_next_step", "ace_summary"):
        op.drop_column("leads", col)

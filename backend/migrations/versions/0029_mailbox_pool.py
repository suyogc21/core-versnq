"""Step O1 — the mailbox pool (Decision log #44).

A company may connect any number of inboxes. mailboxes: user_id becomes optional (an inbox can
belong to no one, e.g. sales@), "one per user" becomes "one personal mailbox per user", and each
inbox gains: personal (the user's own "My mailbox"), in_pool (may send sequences / campaigns),
sender name, signature, daily limit, minimum gap between sends, when it last sent, and why it was
paused. Status gains 'paused'. Existing rows stay personal and out of the pool.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_mailboxes_user", "mailboxes", type_="unique")
    op.alter_column("mailboxes", "user_id", nullable=True)
    op.add_column(
        "mailboxes", sa.Column("personal", sa.Boolean, nullable=False, server_default=sa.true())
    )
    op.add_column(
        "mailboxes", sa.Column("in_pool", sa.Boolean, nullable=False, server_default=sa.false())
    )
    op.add_column("mailboxes", sa.Column("from_name", sa.String(120)))
    op.add_column("mailboxes", sa.Column("signature", sa.Text))
    op.add_column(
        "mailboxes", sa.Column("daily_limit", sa.Integer, nullable=False, server_default="30")
    )
    op.add_column(
        "mailboxes", sa.Column("min_gap_minutes", sa.Integer, nullable=False, server_default="6")
    )
    op.add_column("mailboxes", sa.Column("last_sent_at", sa.DateTime(timezone=True)))
    op.add_column("mailboxes", sa.Column("paused_reason", sa.String(200)))
    op.create_index(
        "uq_mailboxes_personal",
        "mailboxes",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("personal"),
    )
    op.create_index(
        "uq_mailboxes_address", "mailboxes", ["tenant_id", sa.text("lower(email_address)")],
        unique=True,
    )  # fmt: skip
    op.create_check_constraint(
        "personal_has_owner", "mailboxes", "NOT personal OR user_id IS NOT NULL"
    )
    op.create_check_constraint(
        "limits_valid",
        "mailboxes",
        "daily_limit BETWEEN 1 AND 2000 AND min_gap_minutes BETWEEN 0 AND 1440",
    )
    op.drop_constraint("status_valid", "mailboxes", type_="check")
    op.create_check_constraint(
        "status_valid", "mailboxes", "status IN ('active', 'error', 'off', 'paused')"
    )


def downgrade() -> None:
    # Row security is forced even for the owner, so lift it for this clean-up of every company.
    for t in ("mailboxes", "messages"):
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE messages SET mailbox_id = NULL "
        "WHERE mailbox_id IN (SELECT id FROM mailboxes WHERE NOT personal)"
    )
    op.execute("DELETE FROM mailboxes WHERE NOT personal")
    op.execute("UPDATE mailboxes SET status = 'off' WHERE status = 'paused'")
    for t in ("mailboxes", "messages"):
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.drop_constraint("status_valid", "mailboxes", type_="check")
    op.create_check_constraint("status_valid", "mailboxes", "status IN ('active', 'error', 'off')")
    op.drop_constraint("limits_valid", "mailboxes", type_="check")
    op.drop_constraint("personal_has_owner", "mailboxes", type_="check")
    op.drop_index("uq_mailboxes_address", "mailboxes")
    op.drop_index("uq_mailboxes_personal", "mailboxes")
    for col in (
        "paused_reason", "last_sent_at", "min_gap_minutes", "daily_limit", "signature",
        "from_name", "in_pool", "personal",
    ):  # fmt: skip
        op.drop_column("mailboxes", col)
    op.alter_column("mailboxes", "user_id", nullable=False)
    op.create_unique_constraint("uq_mailboxes_user", "mailboxes", ["tenant_id", "user_id"])

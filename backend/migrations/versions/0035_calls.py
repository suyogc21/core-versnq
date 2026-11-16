"""Calls (docs/plans/calls-plan.md, step C1, approved Nov 16).

One pipeline for every call, whatever reports it: our Android app (the rep's own SIM), the
company's own Twilio, later Exotel. calls: the lead, the rep, direction, status, the other
number, when and how long, the source and the source's own id (a repeat is the same call), the
timeline activity, the recording (kept 30 days by default) and ACE's analysis.
tenant_settings.calls: record calls or not, how long recordings are kept, whether an unknown
incoming number makes a lead.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

DEFAULTS = sa.text("""'{"record": true, "keep_days": 30, "new_leads": false}'::jsonb""")


def _set_null_fk(table: str, col: str, ref: str, name: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {col}) "
        f"REFERENCES {ref} (tenant_id, id) ON DELETE SET NULL ({col})"
    )


def upgrade() -> None:
    op.add_column(
        "tenant_settings", sa.Column("calls", JSONB, nullable=False, server_default=DEFAULTS)
    )
    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("user_id", sa.Uuid),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),  # the other side, E.164
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("activity_id", sa.Uuid),
        sa.Column("recording_path", sa.String(300)),
        sa.Column("recording_type", sa.String(60)),
        sa.Column("recording_bytes", sa.BigInteger),
        sa.Column("recording_removed_at", sa.DateTime(timezone=True)),
        sa.Column("summary", sa.Text),
        sa.Column("analysis", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        sa.UniqueConstraint("tenant_id", "id", name="uq_calls_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "source", "external_id", name="uq_calls_source_id"),
        sa.CheckConstraint("direction IN ('in', 'out')", name="direction_valid"),
        sa.CheckConstraint(
            "status IN ('answered', 'missed', 'no_answer', 'busy', 'failed')", name="status_valid"
        ),
        sa.CheckConstraint("source IN ('app', 'twilio', 'exotel')", name="source_valid"),
        sa.CheckConstraint("duration_seconds >= 0", name="duration_valid"),
    )
    _set_null_fk("calls", "lead_id", "leads", "fk_calls_lead")
    _set_null_fk("calls", "user_id", "users", "fk_calls_user")
    op.create_index("ix_calls_lead", "calls", ["tenant_id", "lead_id", "started_at"])
    op.create_index("ix_calls_user", "calls", ["tenant_id", "user_id", "started_at"])
    enable_tenant_rls("calls")


def downgrade() -> None:
    disable_tenant_rls("calls")
    op.drop_table("calls")
    op.drop_column("tenant_settings", "calls")

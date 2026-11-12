"""Step 9a — sequences and email (Decision log #39).

message_templates (email now, WhatsApp in step 10), sequences and their steps, enrolments (a
lead going through a sequence), messages (every email in or out, with tracking) and
message_events (delivered, opened, clicked, bounced, complained, unsubscribed). Quiet hours and
the daily sending cap live on tenant_settings.engage. Permission sequences.manage. Timeline
types for emails and sequences. The task origin 'sequence'.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

TABLES = (
    "message_templates",
    "sequences",
    "sequence_steps",
    "enrolments",
    "messages",
    "message_events",
)
PERMISSION = ("sequences.manage", "crm", "Create sequences and message templates")
GRANTS = ("admin", "sales_manager")
# Frozen copy of app/modules/crm/setup.py STEP9A_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("email_sent", "Email sent", "mail"),
    ("email_event", "Email activity", "mail-open"),
    ("sequence_enrolled", "Added to a sequence", "list-start"),
    ("sequence_ended", "Sequence ended", "list-end"),
]
ENGAGE_DEFAULT = (
    '{"from": "09:00", "to": "20:00", "days": [0, 1, 2, 3, 4, 5], "daily_cap": 200}'
)


def _ts() -> list[sa.Column]:
    now = sa.func.now()
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def _base(table: str) -> list:
    return [
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id_id"),
    ]


def _same_tenant(col: str, ref: str, name: str, ondelete: str | None = None):
    return sa.ForeignKeyConstraint(
        ["tenant_id", col], [f"{ref}.tenant_id", f"{ref}.id"], name=name, ondelete=ondelete
    )


def _set_null_fk(table: str, col: str, ref: str, name: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {col}) "
        f"REFERENCES {ref} (tenant_id, id) ON DELETE SET NULL ({col})"
    )


def upgrade() -> None:
    # consents.source allowed 'unsubscribe' (11 letters) in a 10-letter column (since 0011)
    op.alter_column("consents", "source", type_=sa.String(12), existing_nullable=False)
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), PERMISSION, strict=True))],
    )
    op.add_column(
        "tenant_settings",
        sa.Column("engage", JSONB, nullable=False, server_default=sa.text(f"'{ENGAGE_DEFAULT}'::jsonb")),
    )

    op.create_table(
        "message_templates",
        *_base("message_templates"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("subject", sa.String(300)),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint("channel IN ('email', 'whatsapp')", name="channel_valid"),
        sa.UniqueConstraint("tenant_id", "channel", "name", name="uq_message_templates_name"),
    )

    op.create_table(
        "sequences",
        *_base("sequences"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("allow_with_others", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("stop_on", JSONB, nullable=False),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_sequences_name"),
    )

    op.create_table(
        "sequence_steps",
        *_base("sequence_steps"),
        sa.Column("sequence_id", sa.Uuid, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("config", JSONB, nullable=False),
        *_ts(),
        sa.CheckConstraint("kind IN ('email', 'whatsapp', 'task', 'wait', 'check')", name="kind_valid"),
        _same_tenant("sequence_id", "sequences", "fk_sequence_steps_sequence_same_tenant", "CASCADE"),
    )
    op.create_index("ix_sequence_steps_sequence", "sequence_steps", ["sequence_id", "position"])

    op.create_table(
        "enrolments",
        *_base("enrolments"),
        sa.Column("sequence_id", sa.Uuid, nullable=False),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("ended_reason", sa.String(40)),
        sa.Column("enrolled_by_user_id", sa.Uuid),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.CheckConstraint("status IN ('active', 'completed', 'stopped')", name="status_valid"),
        _same_tenant("sequence_id", "sequences", "fk_enrolments_sequence_same_tenant", "CASCADE"),
        _same_tenant("lead_id", "leads", "fk_enrolments_lead_same_tenant", "CASCADE"),
    )
    op.create_index(
        "uq_enrolments_active",
        "enrolments",
        ["tenant_id", "sequence_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_enrolments_due",
        "enrolments",
        ["tenant_id", "next_run_at"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_enrolments_lead", "enrolments", ["tenant_id", "lead_id"])

    op.create_table(
        "messages",
        *_base("messages"),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("enrolment_id", sa.Uuid),
        sa.Column("step_id", sa.Uuid),
        sa.Column("template_id", sa.Uuid),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("from_address", sa.String(320)),
        sa.Column("subject", sa.String(300)),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("links", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("token", sa.String(48), nullable=False, unique=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("provider_id", sa.String(200)),
        sa.Column("error", sa.String(300)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("clicked_at", sa.DateTime(timezone=True)),
        sa.Column("replied_at", sa.DateTime(timezone=True)),
        sa.Column("bounced_at", sa.DateTime(timezone=True)),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint("channel IN ('email', 'whatsapp')", name="channel_valid"),
        sa.CheckConstraint("direction IN ('out', 'in')", name="direction_valid"),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'bounced', 'failed', 'received')",
            name="status_valid",
        ),
    )
    _set_null_fk("messages", "lead_id", "leads", "fk_messages_lead_same_tenant")
    _set_null_fk("messages", "enrolment_id", "enrolments", "fk_messages_enrolment_same_tenant")
    op.create_index("ix_messages_lead", "messages", ["tenant_id", "lead_id", "created_at"])
    op.create_index("ix_messages_enrolment", "messages", ["tenant_id", "enrolment_id"])
    op.create_index("ix_messages_step", "messages", ["tenant_id", "step_id"])
    op.create_index("ix_messages_sent", "messages", ["tenant_id", "channel", "sent_at"])

    op.create_table(
        "message_events",
        *_base("message_events"),
        sa.Column("message_id", sa.Uuid, nullable=False),
        sa.Column("type", sa.String(12), nullable=False),
        sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "type IN ('delivered', 'open', 'click', 'bounce', 'complaint', 'unsubscribe', 'reply')",
            name="type_valid",
        ),
        _same_tenant("message_id", "messages", "fk_message_events_message_same_tenant", "CASCADE"),
    )
    op.create_index("ix_message_events_message", "message_events", ["tenant_id", "message_id"])

    for table in TABLES:
        enable_tenant_rls(table)

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for key in GRANTS:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                    "SELECT tenant_id, id, :code FROM roles WHERE key = :key "
                    "ON CONFLICT DO NOTHING"
                ),
                {"code": PERMISSION[0], "key": key},
            )
        for key, label, icon in SYSTEM_TYPES:
            conn.execute(
                sa.text(
                    "INSERT INTO activity_types (id, tenant_id, key, label, icon, is_system, "
                    "is_loggable, is_active, fields, position) "
                    "SELECT gen_random_uuid(), :t, :key, :label, :icon, true, false, true, "
                    "'[]'::jsonb, COALESCE(MAX(position), 0) + 1 FROM activity_types "
                    "WHERE tenant_id = :t HAVING COUNT(*) > 0 ON CONFLICT DO NOTHING"
                ),
                {"t": str(tenant_id), "key": key, "label": label, "icon": icon},
            )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    conn = op.get_bind()
    keys = [k for k, _, _ in SYSTEM_TYPES]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM activities WHERE type_key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM activity_types WHERE key = ANY(:k)"), {"k": keys})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = :c"),
            {"c": PERMISSION[0]},
        )
        conn.execute(sa.text("DELETE FROM tasks WHERE created_from = 'sequence'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": PERMISSION[0]})
    op.drop_column("tenant_settings", "engage")
    # consents.source stays 12 wide: shrinking it back would break 'unsubscribe' rows

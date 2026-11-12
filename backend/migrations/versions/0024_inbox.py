"""Step 9b-1 — conversations and the shared inbox (Decision log #40).

conversations (a thread with a lead; follows the lead's owner unless someone took it over),
conversation_members (colleagues added to it), conversation_notes (internal, never emailed),
conversation_reads (who read up to when), message_attachments (files that came with an email),
canned_replies. messages gain thread headers, CC and a conversation. Permissions inbox.reply and
inbox.take_over. Timeline type email_received.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

TABLES = (
    "conversations",
    "conversation_members",
    "conversation_notes",
    "conversation_reads",
    "message_attachments",
    "canned_replies",
)
PERMISSIONS = [
    ("inbox.reply", "crm", "Read and answer conversations of leads you can see"),
    ("inbox.take_over", "crm", "Take over or hand on any conversation you can see"),
]
GRANTS = {
    "admin": ["inbox.reply", "inbox.take_over"],
    "sales_manager": ["inbox.reply", "inbox.take_over"],
    "sales_user": ["inbox.reply"],
}
# Frozen copy of app/modules/crm/setup.py STEP9B_SYSTEM_TYPES.
SYSTEM_TYPES = [("email_received", "Email received", "mail")]


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


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
    )
    op.create_table(
        "conversations",
        *_base("conversations"),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("subject", sa.String(300)),
        sa.Column("assignee_user_id", sa.Uuid),  # None: follows the lead's owner
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),
        sa.Column("is_private", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("private_user_id", sa.Uuid),
        sa.Column("enrolment_id", sa.Uuid),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True)),
        sa.Column("last_direction", sa.String(3)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint("status IN ('open', 'closed')", name="status_valid"),
        sa.CheckConstraint("channel IN ('email', 'whatsapp')", name="channel_valid"),
        _same_tenant("lead_id", "leads", "fk_conversations_lead_same_tenant", "CASCADE"),
    )
    op.create_index("ix_conversations_lead", "conversations", ["tenant_id", "lead_id"])
    op.create_index("ix_conversations_recent", "conversations", ["tenant_id", "last_message_at"])

    op.create_table(
        "conversation_members",
        *_base("conversation_members"),
        sa.Column("conversation_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("added_by_user_id", sa.Uuid),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "conversation_id", "user_id", name="uq_conversation_members"
        ),
        _same_tenant(
            "conversation_id",
            "conversations",
            "fk_conversation_members_conv_same_tenant",
            "CASCADE",
        ),
        _same_tenant("user_id", "users", "fk_conversation_members_user_same_tenant", "CASCADE"),
    )
    op.create_index(
        "ix_conversation_members_user", "conversation_members", ["tenant_id", "user_id"]
    )

    op.create_table(
        "conversation_notes",
        *_base("conversation_notes"),
        sa.Column("conversation_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Uuid),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("mentions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _same_tenant(
            "conversation_id", "conversations", "fk_conversation_notes_conv_same_tenant", "CASCADE"
        ),
    )

    op.create_table(
        "conversation_reads",
        *_base("conversation_reads"),
        sa.Column("conversation_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "conversation_id", "user_id", name="uq_conversation_reads"
        ),
        _same_tenant(
            "conversation_id", "conversations", "fk_conversation_reads_conv_same_tenant", "CASCADE"
        ),
    )

    op.create_table(
        "message_attachments",
        *_base("message_attachments"),
        sa.Column("message_id", sa.Uuid, nullable=False),
        sa.Column("file_id", sa.Uuid, nullable=False),
        _same_tenant(
            "message_id", "messages", "fk_message_attachments_message_same_tenant", "CASCADE"
        ),
        _same_tenant("file_id", "files", "fk_message_attachments_file_same_tenant", "CASCADE"),
    )
    op.create_index(
        "ix_message_attachments_message", "message_attachments", ["tenant_id", "message_id"]
    )

    op.create_table(
        "canned_replies",
        *_base("canned_replies"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("is_shared", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("user_id", sa.Uuid),
        *_ts(),
    )

    op.add_column("messages", sa.Column("conversation_id", sa.Uuid))
    op.add_column("messages", sa.Column("message_id_header", sa.String(300)))
    op.add_column("messages", sa.Column("in_reply_to", sa.String(300)))
    op.add_column("messages", sa.Column("references", sa.Text))
    op.add_column(
        "messages", sa.Column("cc", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"))
    )
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT fk_messages_conversation_same_tenant "
        "FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations (tenant_id, id) "
        "ON DELETE SET NULL (conversation_id)"
    )
    op.create_index(
        "ix_messages_conversation", "messages", ["tenant_id", "conversation_id", "created_at"]
    )
    op.create_index(
        "uq_messages_message_id_header",
        "messages",
        ["tenant_id", "message_id_header"],
        unique=True,
        postgresql_where=sa.text("message_id_header IS NOT NULL"),
    )

    for table in TABLES:
        enable_tenant_rls(table)

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for role, codes in GRANTS.items():
            for code in codes:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                        "SELECT tenant_id, id, :code FROM roles WHERE key = :key "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"code": code, "key": role},
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
    codes = [c for c, _, _ in PERMISSIONS]
    keys = [k for k, _, _ in SYSTEM_TYPES]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM activities WHERE type_key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM activity_types WHERE key = ANY(:k)"), {"k": keys})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:c)"), {"c": codes}
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("uq_messages_message_id_header", "messages")
    op.drop_index("ix_messages_conversation", "messages")
    op.execute("ALTER TABLE messages DROP CONSTRAINT fk_messages_conversation_same_tenant")
    for col in ("cc", "references", "in_reply_to", "message_id_header", "conversation_id"):
        op.drop_column("messages", col)
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:c)"), {"c": codes})

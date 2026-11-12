"""Step 10a — the reps' own WhatsApp through the Versnq Chrome extension (Decision log #41).

extension_tokens (one per connected browser: a one-time connect code, then a token that works
only on /api/v1/extension/*), whatsapp_chat_links (a WhatsApp Web chat without a visible
number, linked to a lead once by the rep), messages.external_id (WhatsApp's own message id, so
nothing is logged twice). Timeline types whatsapp_sent and whatsapp_received.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

TABLES = ("extension_tokens", "whatsapp_chat_links")
# Frozen copy of app/modules/crm/setup.py STEP10_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("whatsapp_sent", "WhatsApp sent", "message-circle"),
    ("whatsapp_received", "WhatsApp received", "message-circle"),
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
    now = sa.func.now()
    op.create_table(
        "extension_tokens",
        *_base("extension_tokens"),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("code_hash", sa.String(64)),  # one-time connect code, cleared once used
        sa.Column("code_expires_at", sa.DateTime(timezone=True)),
        sa.Column("token_hash", sa.String(64)),  # set when the code is exchanged
        sa.Column("device", sa.String(120)),
        sa.Column("version", sa.String(20)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        _same_tenant("user_id", "users", "fk_extension_tokens_user_same_tenant", "CASCADE"),
    )
    op.create_index("uq_extension_tokens_token", "extension_tokens", ["token_hash"], unique=True)
    op.create_index("ix_extension_tokens_code", "extension_tokens", ["tenant_id", "code_hash"])

    op.create_table(
        "whatsapp_chat_links",
        *_base("whatsapp_chat_links"),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("chat_key", sa.String(200), nullable=False),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", "chat_key", name="uq_whatsapp_chat_links"),
        _same_tenant("user_id", "users", "fk_whatsapp_chat_links_user_same_tenant", "CASCADE"),
        _same_tenant("lead_id", "leads", "fk_whatsapp_chat_links_lead_same_tenant", "CASCADE"),
    )
    for table in TABLES:
        enable_tenant_rls(table)

    op.add_column("messages", sa.Column("external_id", sa.String(200)))
    op.create_index(
        "uq_messages_external_id",
        "messages",
        ["tenant_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
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
        conn.execute(sa.text("DELETE FROM messages WHERE channel = 'whatsapp'"))
        conn.execute(sa.text("DELETE FROM conversations WHERE channel = 'whatsapp'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("uq_messages_external_id", "messages")
    op.drop_column("messages", "external_id")
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)

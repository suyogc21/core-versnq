"""Step 10b — the company's official WhatsApp number (Decision log #41).

whatsapp_accounts (one per company: Meta Cloud API ids, access token and app secret encrypted,
webhook verify token, health), whatsapp_templates (written with our variables, sent to Meta for
approval, status). conversations gain the account they belong to (empty for chats logged by the
reps' extension). messages gain the template used and delivered / read times.
tenant_settings.whatsapp: unknown number → lead, its source, STOP words, the autoresponder.
consents may come from a WhatsApp STOP message. Permission whatsapp.manage (admins).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-12
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

TABLES = ("whatsapp_accounts", "whatsapp_templates")
PERMISSIONS = [("whatsapp.manage", "settings", "Connect the WhatsApp number, write its templates")]
GRANTS = {"admin": ["whatsapp.manage"]}
# Frozen copy of app/modules/engage/whatsapp.py DEFAULT_SETTINGS.
DEFAULTS = {
    "create_leads": True,
    "source_id": None,
    "stop_words": ["STOP", "UNSUBSCRIBE", "STOP ALL", "बंद"],
    "welcome": {"on": False, "text": ""},
    "away": {"on": False, "text": ""},
}


def _base(table: str) -> list:
    return [
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id_id"),
    ]


def _ts() -> list[sa.Column]:
    now = sa.func.now()
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
    )
    op.create_table(
        "whatsapp_accounts",
        *_base("whatsapp_accounts"),
        sa.Column("phone_number_id", sa.String(40), nullable=False),
        sa.Column("waba_id", sa.String(40), nullable=False),
        sa.Column("display_number", sa.String(40)),
        sa.Column("verified_name", sa.String(200)),
        sa.Column("access_token_enc", sa.Text, nullable=False),
        sa.Column("app_secret_enc", sa.Text, nullable=False),
        sa.Column("verify_token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="active"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("quality_rating", sa.String(20)),
        sa.Column("messaging_limit", sa.String(40)),
        sa.Column("health_checked_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.UniqueConstraint("tenant_id", name="uq_whatsapp_accounts_one_per_company"),
        sa.CheckConstraint("status IN ('active', 'error')", name="status_valid"),
    )
    op.create_table(
        "whatsapp_templates",
        *_base("whatsapp_templates"),
        sa.Column("name", sa.String(120), nullable=False),  # Meta's: lowercase_with_underscores
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("category", sa.String(14), nullable=False),
        sa.Column("body", sa.Text, nullable=False),  # with our {{lead.first_name}} variables
        sa.Column("variables", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("footer", sa.String(60)),
        sa.Column("meta_id", sa.String(60)),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(500)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "name", "language", name="uq_whatsapp_templates_name"),
        sa.CheckConstraint("category IN ('marketing', 'utility')", name="category_valid"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'paused', 'disabled')",
            name="status_valid",
        ),
    )
    for table in TABLES:
        enable_tenant_rls(table)

    op.add_column("conversations", sa.Column("whatsapp_account_id", sa.Uuid))
    op.execute(
        "ALTER TABLE conversations ADD CONSTRAINT fk_conversations_wa_account_same_tenant "
        "FOREIGN KEY (tenant_id, whatsapp_account_id) "
        "REFERENCES whatsapp_accounts (tenant_id, id) ON DELETE SET NULL (whatsapp_account_id)"
    )
    op.add_column("messages", sa.Column("whatsapp_template_id", sa.Uuid))
    op.add_column("messages", sa.Column("delivered_at", sa.DateTime(timezone=True)))
    op.add_column("messages", sa.Column("read_at", sa.DateTime(timezone=True)))
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT fk_messages_wa_template_same_tenant "
        "FOREIGN KEY (tenant_id, whatsapp_template_id) "
        "REFERENCES whatsapp_templates (tenant_id, id) ON DELETE SET NULL (whatsapp_template_id)"
    )
    op.add_column(
        "tenant_settings",
        sa.Column(
            "whatsapp",
            JSONB,
            nullable=False,
            server_default=sa.text(f"'{json.dumps(DEFAULTS, ensure_ascii=False)}'::jsonb"),
        ),
    )
    op.drop_constraint("source_valid", "consents", type_="check")
    op.create_check_constraint(
        "source_valid",
        "consents",
        "source IN ('form', 'import', 'manual', 'api', 'unsubscribe', 'whatsapp')",
    )
    # WhatsApp tells us when a message was read
    op.drop_constraint("status_valid", "messages", type_="check")
    op.create_check_constraint(
        "status_valid",
        "messages",
        "status IN ('queued', 'sent', 'delivered', 'read', 'bounced', 'failed', 'received')",
    )

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
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))


def downgrade() -> None:
    conn = op.get_bind()
    codes = [c for c, _, _ in PERMISSIONS]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:c)"), {"c": codes}
        )
        conn.execute(sa.text("DELETE FROM consents WHERE source = 'whatsapp'"))
        conn.execute(
            sa.text(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE whatsapp_account_id IS NOT NULL)"
            )
        )
        conn.execute(sa.text("DELETE FROM conversations WHERE whatsapp_account_id IS NOT NULL"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_constraint("source_valid", "consents", type_="check")
    op.create_check_constraint(
        "source_valid", "consents", "source IN ('form', 'import', 'manual', 'api', 'unsubscribe')"
    )
    op.execute("UPDATE messages SET status = 'delivered' WHERE status = 'read'")
    op.drop_constraint("status_valid", "messages", type_="check")
    op.create_check_constraint(
        "status_valid",
        "messages",
        "status IN ('queued', 'sent', 'delivered', 'bounced', 'failed', 'received')",
    )
    op.drop_column("tenant_settings", "whatsapp")
    op.execute("ALTER TABLE messages DROP CONSTRAINT fk_messages_wa_template_same_tenant")
    for col in ("read_at", "delivered_at", "whatsapp_template_id"):
        op.drop_column("messages", col)
    op.execute("ALTER TABLE conversations DROP CONSTRAINT fk_conversations_wa_account_same_tenant")
    op.drop_column("conversations", "whatsapp_account_id")
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:c)"), {"c": codes})

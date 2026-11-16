"""Lead ads and SMS (finishing plan, batch 5d; approved by Suyog Nov 16).

Lead ads:
- lead_ad_sources: one per connected Facebook/Instagram Page (page id, encrypted page token,
  optional encrypted app secret, verify token) or Google Ads lead form (hashed webhook key).
- lead_ad_leads: one per lead the ad network sent (its own lead id, unique), so a repeat is
  ignored and a failed fetch is retried by the worker.

SMS:
- sms_accounts: the company's SMS provider (MSG91 for India, Twilio elsewhere, or the test
  sender), keys encrypted, a random token that signs our webhook addresses.
- sms_templates: the company's SMS texts; for India each needs its DLT template id.
- sms_messages: every SMS in and out (status, provider id, delivery).
- leads.sms_consent; consents may now be for SMS; sequences may have SMS steps; timeline types
  sms_sent and sms_received.

Revision ID: 0046
Revises: 0043
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0046"
down_revision = "0043"
branch_labels = None
depends_on = None

TABLES = ("lead_ad_sources", "lead_ad_leads", "sms_accounts", "sms_templates", "sms_messages")
# Frozen copy of app/modules/crm/setup.py BATCH5D_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("sms_sent", "SMS sent", "message-square"),
    ("sms_received", "SMS received", "message-square"),
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


def _ts() -> list:
    now = sa.func.now()
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "lead_ad_sources",
        *_base("lead_ad_sources"),
        sa.Column("provider", sa.String(10), nullable=False),  # facebook / google
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("page_id", sa.String(40)),  # facebook
        sa.Column("page_token_enc", sa.Text),  # facebook
        sa.Column("app_secret_enc", sa.Text),  # facebook: the company's own app (else ours)
        sa.Column("verify_token", sa.String(64)),  # facebook webhook check
        sa.Column("key_hash", sa.String(64)),  # google: sha256 of the webhook key
        sa.Column("source_id", sa.Uuid, nullable=False),
        sa.Column("stage_id", sa.Uuid),
        sa.Column("brand_id", sa.Uuid),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_lead_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.CheckConstraint("provider IN ('facebook', 'google')", name="provider_valid"),
        _same_tenant("source_id", "lead_sources", "fk_lead_ad_sources_source_same_tenant"),
        _same_tenant("stage_id", "lead_stages", "fk_lead_ad_sources_stage_same_tenant"),
    )
    op.create_index(
        "uq_lead_ad_sources_page",
        "lead_ad_sources",
        ["tenant_id", "page_id"],
        unique=True,
        postgresql_where=sa.text("page_id IS NOT NULL"),
    )

    op.create_table(
        "lead_ad_leads",
        *_base("lead_ad_leads"),
        sa.Column("ad_source_id", sa.Uuid, nullable=False),
        sa.Column("provider", sa.String(10), nullable=False),
        sa.Column("provider_lead_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),  # pending / done / failed
        sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(300)),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "provider", "provider_lead_id", name="uq_lead_ad_leads"),
        _same_tenant(
            "ad_source_id", "lead_ad_sources", "fk_lead_ad_leads_source_same_tenant", "CASCADE"
        ),
    )
    op.create_index("ix_lead_ad_leads_pending", "lead_ad_leads", ["tenant_id", "status"])

    op.create_table(
        "sms_accounts",
        *_base("sms_accounts"),
        sa.Column("provider", sa.String(10), nullable=False),  # msg91 / twilio / test
        sa.Column("sender", sa.String(40), nullable=False),  # DLT header or a Twilio number
        sa.Column("account_sid", sa.String(64)),  # twilio
        sa.Column("auth_enc", sa.Text),  # msg91 auth key or the Twilio auth token
        sa.Column("webhook_token", sa.String(64), nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", name="uq_sms_accounts_tenant"),
        sa.CheckConstraint("provider IN ('msg91', 'twilio', 'test')", name="provider_valid"),
    )
    op.create_table(
        "sms_templates",
        *_base("sms_templates"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("body", sa.String(1000), nullable=False),
        sa.Column("dlt_template_id", sa.String(40)),  # India: the DLT-registered template
        sa.Column("provider_template_id", sa.String(60)),  # MSG91's own template id
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
    )
    op.create_table(
        "sms_messages",
        *_base("sms_messages"),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("direction", sa.String(3), nullable=False),  # out / in
        sa.Column("number", sa.String(32), nullable=False),  # the lead's side, E.164
        sa.Column("body", sa.String(1600), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("provider", sa.String(10), nullable=False),
        sa.Column("provider_id", sa.String(100)),
        sa.Column("error", sa.String(300)),
        sa.Column("template_id", sa.Uuid),
        sa.Column("enrolment_id", sa.Uuid),
        sa.Column("step_id", sa.Uuid),
        sa.Column("sent_by_user_id", sa.Uuid),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("direction IN ('out', 'in')", name="direction_valid"),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'failed', 'received')", name="status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["leads.tenant_id", "leads.id"],
            name="fk_sms_messages_lead_same_tenant",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_sms_messages_lead", "sms_messages", ["tenant_id", "lead_id"])
    op.create_index(
        "uq_sms_messages_provider_id",
        "sms_messages",
        ["tenant_id", "provider", "provider_id"],
        unique=True,
        postgresql_where=sa.text("provider_id IS NOT NULL"),
    )
    for table in TABLES:
        enable_tenant_rls(table)

    op.add_column("leads", sa.Column("sms_consent", sa.String(10)))
    op.drop_constraint("channel_valid", "consents", type_="check")
    op.create_check_constraint(
        "channel_valid", "consents", "channel IN ('email', 'whatsapp', 'sms')"
    )
    op.drop_constraint("kind_valid", "sequence_steps", type_="check")
    op.create_check_constraint(
        "kind_valid",
        "sequence_steps",
        "kind IN ('email', 'whatsapp', 'sms', 'task', 'wait', 'check')",
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
        conn.execute(sa.text("DELETE FROM consents WHERE channel = 'sms'"))
        conn.execute(sa.text("DELETE FROM sequence_steps WHERE kind = 'sms'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_constraint("kind_valid", "sequence_steps", type_="check")
    op.create_check_constraint(
        "kind_valid", "sequence_steps", "kind IN ('email', 'whatsapp', 'task', 'wait', 'check')"
    )
    op.drop_constraint("channel_valid", "consents", type_="check")
    op.create_check_constraint("channel_valid", "consents", "channel IN ('email', 'whatsapp')")
    op.drop_column("leads", "sms_consent")
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)

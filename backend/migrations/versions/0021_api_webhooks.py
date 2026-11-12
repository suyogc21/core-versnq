"""Milestone 4 — API keys, outbound webhooks, API and webhook logs (Decision log #37).

An API key carries one of the company's roles through an integration user (status
'integration': cannot sign in, never listed as a team member). Webhook endpoints receive the
events they picked, signed, with retries; every delivery is kept as the webhook log. Every
request made with a key is kept as the API log. Both logs stay 30 days, then are archived to a
file. Permission integrations.manage. Activity types for API conversations and intent changes.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

TABLES = ("api_keys", "webhook_endpoints", "webhook_deliveries", "api_request_log")
PERMISSION = ("integrations.manage", "settings", "Manage API keys, webhooks and their logs")
GRANTS = ("admin",)
# Frozen copy of app/modules/crm/setup.py STEP_M4_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("api_conversation", "Conversation", "messages-square"),
    ("intent_changed", "Intent changed", "gauge"),
]


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
    op.drop_constraint("status_valid", "users", type_="check")
    op.create_check_constraint(
        "status_valid", "users", "status IN ('invited', 'active', 'disabled', 'integration')"
    )
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), PERMISSION, strict=True))],
    )

    op.create_table(
        "api_keys",
        *_base("api_keys"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_ts(),
        _same_tenant("user_id", "users", "fk_api_keys_user_same_tenant"),
    )

    op.create_table(
        "webhook_endpoints",
        *_base("webhook_endpoints"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("events", JSONB, nullable=False),  # event types, or ["*"] for all
        sa.Column("secret_enc", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("failing_since", sa.DateTime(timezone=True)),
        sa.Column("switched_off_reason", sa.String(200)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
    )

    op.create_table(
        "webhook_deliveries",
        *_base("webhook_deliveries"),
        sa.Column("endpoint_id", sa.Uuid, nullable=False),
        sa.Column("event_id", sa.Uuid),  # no key: events may be cleaned up later
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_try_at", sa.DateTime(timezone=True)),
        sa.Column("last_status_code", sa.Integer),
        sa.Column("last_error", sa.String(300)),
        sa.Column("last_duration_ms", sa.Integer),
        sa.Column("response_snippet", sa.String(500)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.CheckConstraint("status IN ('pending', 'ok', 'failed')", name="status_valid"),
        _same_tenant(
            "endpoint_id", "webhook_endpoints", "fk_webhook_deliveries_endpoint_same_tenant",
            "CASCADE",
        ),
    )  # fmt: skip
    op.create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["tenant_id", "next_try_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_webhook_deliveries_endpoint_time",
        "webhook_deliveries",
        ["tenant_id", "endpoint_id", "created_at"],
    )
    op.create_index("ix_webhook_deliveries_time", "webhook_deliveries", ["tenant_id", "created_at"])

    op.create_table(
        "api_request_log",
        *_base("api_request_log"),
        sa.Column("key_id", sa.Uuid, nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("status", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("ip", sa.String(64)),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_api_request_log_time", "api_request_log", ["tenant_id", "at"])
    op.create_index("ix_api_request_log_key_time", "api_request_log", ["tenant_id", "key_id", "at"])

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
        # keys' users may own or have created records: keep them, switched off
        conn.execute(sa.text("UPDATE users SET status = 'disabled' WHERE status = 'integration'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": PERMISSION[0]})
    op.drop_constraint("status_valid", "users", type_="check")
    op.create_check_constraint(
        "status_valid", "users", "status IN ('invited', 'active', 'disabled')"
    )

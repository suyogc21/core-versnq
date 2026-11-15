"""Step O3 — reply categories, rules and drafts (Decision log #44, plan in
docs/plans/outreach-plan.md, the contract with ACE).

reply_categories (the company's own list; exactly one needs_human, key fixed), reply_rules (what
happens for a category: convert / draft / stop / unsubscribe / notify), message_classifications
(each sorting of a reply, by ACE or a person; history kept), draft_requests (Core asks ACE for a
draft; ACE answers with the request id), drafts (waiting for a person: approve / edit / reject;
sent from the right inbox in the same thread). Permission drafts.approve_for_users (ACE's key
only, to act for the person who clicked in Slack). The default categories are made on first use.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

TABLES = (
    "reply_categories", "reply_rules", "message_classifications", "draft_requests", "drafts",
)  # fmt: skip
PERMISSIONS = [
    ("drafts.approve_for_users", "crm",
     "Approve or reject drafts for the person who clicked (only for ACE's key)"),
]  # fmt: skip
EMPTY = sa.text("'[]'::jsonb")


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


def _fk(col: str, ref: str, name: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", col], [f"{ref}.tenant_id", f"{ref}.id"], name=name, ondelete=ondelete
    )


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
    )
    op.create_table(
        "reply_categories",
        *_base("reply_categories"),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("needs_human", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("auto_send_allowed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "key", name="uq_reply_categories_key"),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,39}$'", name="key_valid"),
        sa.CheckConstraint("NOT needs_human OR key = 'needs_human'", name="needs_human_key"),
    )
    op.create_index(
        "uq_reply_categories_one_needs_human", "reply_categories", ["tenant_id"],
        unique=True, postgresql_where=sa.text("needs_human"),
    )  # fmt: skip
    op.create_table(
        "reply_rules",
        *_base("reply_rules"),
        sa.Column("category_id", sa.Uuid, nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("instructions", sa.String(1000)),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
        _fk("category_id", "reply_categories", "fk_reply_rules_category", "CASCADE"),
        sa.CheckConstraint(
            "action IN ('convert', 'draft', 'stop', 'unsubscribe', 'notify')", name="action_valid"
        ),
    )
    op.create_table(
        "message_classifications",
        *_base("message_classifications"),
        sa.Column("message_id", sa.Uuid, nullable=False),
        sa.Column("conversation_id", sa.Uuid),
        sa.Column("category_key", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Integer),
        sa.Column("summary", sa.String(500)),
        sa.Column("reasons", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("language", sa.String(20)),
        sa.Column("prompt_version", sa.String(60)),
        sa.Column("by", sa.String(6), nullable=False),
        sa.Column("by_user_id", sa.Uuid),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("rules_run_at", sa.DateTime(timezone=True)),
        sa.Column("rules_run", JSONB, nullable=False, server_default=EMPTY),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        _fk("message_id", "messages", "fk_message_classifications_message", "CASCADE"),
        sa.CheckConstraint("by IN ('ace', 'person')", name="by_valid"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="conf_valid"),
    )
    op.create_index(
        "uq_message_classifications_current", "message_classifications",
        ["tenant_id", "message_id"], unique=True, postgresql_where=sa.text("is_current"),
    )  # fmt: skip
    op.create_table(
        "draft_requests",
        *_base("draft_requests"),
        sa.Column("message_id", sa.Uuid, nullable=False),
        sa.Column("conversation_id", sa.Uuid, nullable=False),
        sa.Column("category_key", sa.String(40), nullable=False),
        sa.Column("rule_id", sa.Uuid),
        sa.Column("instructions", sa.String(1000)),
        sa.Column("draft_id", sa.Uuid),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        _fk("message_id", "messages", "fk_draft_requests_message", "CASCADE"),
        _fk("conversation_id", "conversations", "fk_draft_requests_conversation", "CASCADE"),
    )
    op.create_table(
        "drafts",
        *_base("drafts"),
        sa.Column("conversation_id", sa.Uuid, nullable=False),
        sa.Column("reply_to_message_id", sa.Uuid, nullable=False),
        sa.Column("request_id", sa.Uuid),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("reasons", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("language", sa.String(20)),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("decided_by_user_id", sa.Uuid),
        sa.Column("via", sa.String(6)),
        sa.Column("body_changed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reject_reason", sa.String(500)),
        sa.Column("message_id", sa.Uuid),
        sa.Column("superseded_by_message_id", sa.Uuid),
        sa.Column("error", sa.String(300)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        *_ts(),
        _fk("conversation_id", "conversations", "fk_drafts_conversation", "CASCADE"),
        _fk("reply_to_message_id", "messages", "fk_drafts_reply_to", "CASCADE"),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_drafts_request"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'superseded', 'sent')",
            name="status_valid",
        ),
        sa.CheckConstraint("via IS NULL OR via IN ('core', 'slack')", name="via_valid"),
    )
    op.create_index(
        "uq_drafts_one_pending", "drafts", ["tenant_id", "conversation_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )  # fmt: skip
    for table in TABLES:
        enable_tenant_rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)
    conn = op.get_bind()
    codes = [c for c, _, _ in PERMISSIONS]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:c)"), {"c": codes}
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:c)"), {"c": codes})

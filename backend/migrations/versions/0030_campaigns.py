"""Step O2 — campaigns (Decision log #44, plan in docs/plans/outreach-plan.md).

Cold contacts live apart from leads ("Already your lead? Never a cold email."):
contacts, campaigns, campaign_steps (each with 1-5 variants), campaign_contacts (a contact's
place in a campaign: next step, variant, the inbox it always uses). messages gain the contact,
campaign, step, variant and whether it was an auto-reply. conversations may belong to a contact
instead of a lead (exactly one of the two until converted, then the lead). Permissions
campaigns.manage and outreach.reply.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

TABLES = ("contacts", "campaigns", "campaign_steps", "campaign_contacts")
PERMISSIONS = [
    ("campaigns.manage", "crm", "Create campaigns, import contacts, launch and pause them"),
    ("outreach.reply", "crm", "Read and answer campaign replies (all campaigns with "
     "campaigns.manage, otherwise the campaigns you own)"),
]  # fmt: skip
GRANTS = {
    "admin": ["campaigns.manage", "outreach.reply"],
    "sales_manager": ["campaigns.manage", "outreach.reply"],
    "sales_user": ["outreach.reply"],
}
EMPTY = sa.text("'[]'::jsonb")
EMPTY_OBJ = sa.text("'{}'::jsonb")


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


def _set_null_fk(table: str, col: str, ref: str, name: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {col}) "
        f"REFERENCES {ref} (tenant_id, id) ON DELETE SET NULL ({col})"
    )


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
    )
    op.create_table(
        "contacts",
        *_base("contacts"),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("company", sa.String(200)),
        sa.Column("title", sa.String(200)),
        sa.Column("phone", sa.String(40)),
        sa.Column("website", sa.String(300)),
        sa.Column("variables", JSONB, nullable=False, server_default=EMPTY_OBJ),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("lead_id", sa.Uuid),
        sa.Column("source", sa.String(200)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint(
            "status IN ('active', 'unsubscribed', 'bounced', 'converted')", name="status_valid"
        ),
    )
    op.create_index(
        "uq_contacts_email", "contacts", ["tenant_id", sa.text("lower(email)")], unique=True
    )
    _set_null_fk("contacts", "lead_id", "leads", "fk_contacts_lead_same_tenant")

    op.create_table(
        "campaigns",
        *_base("campaigns"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(2000)),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("owner_user_id", sa.Uuid),
        sa.Column("mailbox_ids", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("schedule", JSONB, nullable=False, server_default=EMPTY_OBJ),
        sa.Column("daily_cap", sa.Integer, nullable=False, server_default="500"),
        sa.Column("track_opens", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("track_clicks", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("launched_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint(
            "status IN ('draft', 'running', 'paused', 'finished')", name="status_valid"
        ),
        sa.CheckConstraint("daily_cap BETWEEN 1 AND 100000", name="daily_cap_valid"),
    )
    op.create_table(
        "campaign_steps",
        *_base("campaign_steps"),
        sa.Column("campaign_id", sa.Uuid, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("wait_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("variants", JSONB, nullable=False, server_default=EMPTY),
        *_ts(),
        _fk("campaign_id", "campaigns", "fk_campaign_steps_campaign_same_tenant", "CASCADE"),
        sa.UniqueConstraint("tenant_id", "campaign_id", "position", name="uq_campaign_steps_pos"),
        sa.CheckConstraint("wait_days BETWEEN 0 AND 365", name="wait_days_valid"),
    )
    op.create_table(
        "campaign_contacts",
        *_base("campaign_contacts"),
        sa.Column("campaign_id", sa.Uuid, nullable=False),
        sa.Column("contact_id", sa.Uuid, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("position", sa.Integer, nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("variant", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mailbox_id", sa.Uuid),
        sa.Column("ended_reason", sa.String(40)),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        *_ts(),
        _fk("campaign_id", "campaigns", "fk_campaign_contacts_campaign_same_tenant", "CASCADE"),
        _fk("contact_id", "contacts", "fk_campaign_contacts_contact_same_tenant", "CASCADE"),
        sa.UniqueConstraint("tenant_id", "campaign_id", "contact_id", name="uq_campaign_contact"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'replied', 'finished', 'stopped', 'bounced', "
            "'unsubscribed')",
            name="status_valid",
        ),
    )
    _set_null_fk("campaign_contacts", "mailbox_id", "mailboxes", "fk_campaign_contacts_mailbox")
    op.create_index(
        "ix_campaign_contacts_due",
        "campaign_contacts",
        ["tenant_id", "next_run_at"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_campaign_contacts_contact", "campaign_contacts", ["tenant_id", "contact_id"]
    )
    for table in TABLES:
        enable_tenant_rls(table)

    for col in ("contact_id", "campaign_id", "campaign_step_id"):
        op.add_column("messages", sa.Column(col, sa.Uuid))
    op.add_column("messages", sa.Column("variant", sa.Integer))
    op.add_column(
        "messages",
        sa.Column("auto_submitted", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    _set_null_fk("messages", "contact_id", "contacts", "fk_messages_contact_same_tenant")
    _set_null_fk("messages", "campaign_id", "campaigns", "fk_messages_campaign_same_tenant")
    _set_null_fk("messages", "campaign_step_id", "campaign_steps", "fk_messages_campaign_step")
    op.create_index("ix_messages_campaign", "messages", ["tenant_id", "campaign_id"])

    op.alter_column("conversations", "lead_id", nullable=True)
    op.add_column("conversations", sa.Column("contact_id", sa.Uuid))
    op.add_column("conversations", sa.Column("campaign_id", sa.Uuid))
    op.create_foreign_key(
        "fk_conversations_contact_same_tenant", "conversations", "contacts",
        ["tenant_id", "contact_id"], ["tenant_id", "id"], ondelete="CASCADE",
    )  # fmt: skip
    _set_null_fk("conversations", "campaign_id", "campaigns", "fk_conversations_campaign")
    op.create_check_constraint(
        "lead_or_contact", "conversations", "lead_id IS NOT NULL OR contact_id IS NOT NULL"
    )
    op.create_index("ix_conversations_contact", "conversations", ["tenant_id", "contact_id"])

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
        conn.execute(
            sa.text(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE lead_id IS NULL)"
            )
        )
        conn.execute(sa.text("DELETE FROM conversations WHERE lead_id IS NULL"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.drop_index("ix_conversations_contact", "conversations")
    op.drop_constraint("lead_or_contact", "conversations", type_="check")
    op.drop_constraint("fk_conversations_campaign", "conversations", type_="foreignkey")
    op.drop_constraint("fk_conversations_contact_same_tenant", "conversations", type_="foreignkey")
    op.drop_column("conversations", "campaign_id")
    op.drop_column("conversations", "contact_id")
    op.alter_column("conversations", "lead_id", nullable=False)
    op.drop_index("ix_messages_campaign", "messages")
    for name in (
        "fk_messages_campaign_step", "fk_messages_campaign_same_tenant",
        "fk_messages_contact_same_tenant",
    ):  # fmt: skip
        op.drop_constraint(name, "messages", type_="foreignkey")
    for col in ("auto_submitted", "variant", "campaign_step_id", "campaign_id", "contact_id"):
        op.drop_column("messages", col)
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:c)"), {"c": codes})

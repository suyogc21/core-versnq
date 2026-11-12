"""Step 6 — money (Decision log #34): billing entities with their own numbering, tax rates,
invoices and lines, installments, payments and how they were applied, payment links, gateway
accounts (keys encrypted) and every gateway webhook received, the company's own mailbox for
invoice emails, and the record of each email sent. Money settings on tenant_settings. invoices.*,
payments.* and money.settings permissions (Finance holds all of money).

Rule 7: every amount is a bigint in minor units with its currency; the database checks the sums.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "billing_entities",
    "tax_rates",
    "invoices",
    "invoice_lines",
    "installments",
    "payments",
    "payment_allocations",
    "gateway_accounts",
    "payment_links",
    "gateway_events",
    "mail_accounts",
    "money_messages",
)

PERMISSIONS = [
    ("invoices.read", "money", "See invoices, payments and balances"),
    ("invoices.create", "money", "Create and issue invoices and send payment links"),
    ("invoices.void", "money", "Void issued invoices"),
    ("payments.record", "money", "Record payments received outside the gateway"),
    ("payments.reverse", "money", "Reverse recorded payments"),
    ("money.settings", "money", "Set up billing entities, taxes, gateways and the mailbox"),
]
ALL = [c for c, _, _ in PERMISSIONS]
DEFAULT_GRANTS = {
    "admin": ALL,
    "sales_manager": ["invoices.read", "invoices.create", "payments.record"],
    "sales_user": ["invoices.read", "invoices.create", "payments.record"],
    "finance": ALL,
}
# Frozen copy of app/modules/crm/setup.py STEP6_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("invoice_issued", "Invoice issued", "receipt"),
    ("invoice_voided", "Invoice voided", "receipt-x"),
    ("payment_received", "Payment received", "indian-rupee"),
    ("payment_reversed", "Payment reversed", "undo"),
    ("payment_link_sent", "Payment link sent", "link"),
    ("invoice_emailed", "Invoice emailed", "mail"),
]


def _ts() -> list[sa.Column]:
    now = sa.func.now()
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


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


def _money(name: str, default: str | None = "0") -> sa.Column:
    return sa.Column(name, sa.BigInteger, nullable=False, server_default=default)


def upgrade() -> None:
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS],
    )
    for name, type_, default in (
        ("money_reminder_before_days", sa.Integer, "3"),
        ("money_overdue_every_days", sa.Integer, "7"),
        ("money_default_pay", sa.String(6), "both"),
        (
            "money_emails",
            JSONB,
            '{"invoice": true, "receipt": true, "reminder": true, "void": true}',
        ),
    ):
        op.add_column(
            "tenant_settings", sa.Column(name, type_, nullable=False, server_default=default)
        )
    op.create_check_constraint(
        "money_settings_valid",
        "tenant_settings",
        "money_reminder_before_days BETWEEN 0 AND 30 AND money_overdue_every_days BETWEEN 1 AND 60 "
        "AND money_default_pay IN ('link', 'direct', 'both') "
        "AND jsonb_typeof(money_emails) = 'object'",
    )

    op.create_table(
        "billing_entities",
        *_base("billing_entities"),
        sa.Column("name", sa.String(120), nullable=False),  # short name shown in Core
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("tax_label", sa.String(20)),  # "GSTIN", "TRN", "EIN"
        sa.Column("tax_id", sa.String(40)),
        sa.Column("address", sa.Text),
        sa.Column("email", sa.String(254)),
        sa.Column("phone", sa.String(40)),
        sa.Column("bank_details", sa.Text),
        sa.Column("upi_id", sa.String(100)),
        sa.Column("terms", sa.Text),
        sa.Column("due_days", sa.Integer, nullable=False, server_default="7"),
        sa.Column("invoice_prefix", sa.String(20), nullable=False, server_default="INV-"),
        sa.Column("receipt_prefix", sa.String(20), nullable=False, server_default="RCT-"),
        sa.Column("next_invoice_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("next_receipt_number", sa.Integer, nullable=False, server_default="1"),
        # Numbers restart each financial year: INV-2026-27/0001 (India starts in April).
        sa.Column("yearly_reset", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("year_start_month", sa.Integer, nullable=False, server_default="4"),
        sa.Column("number_period", sa.String(9)),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint(
            "next_invoice_number >= 1 AND next_receipt_number >= 1 "
            "AND year_start_month BETWEEN 1 AND 12 AND due_days BETWEEN 0 AND 365",
            name="numbers_valid",
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_billing_entities_name"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_billing_entities_default ON billing_entities (tenant_id) "
        "WHERE is_default"
    )

    op.create_table(
        "tax_rates",
        *_base("tax_rates"),
        sa.Column("name", sa.String(60), nullable=False),
        # [{"name": "CGST", "rate_bp": 900}, ...] — basis points: 900 = 9%
        sa.Column("parts", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint("jsonb_typeof(parts) = 'array'", name="parts_is_list"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tax_rates_name"),
    )

    op.create_table(
        "invoices",
        *_base("invoices"),
        sa.Column("customer_id", sa.Uuid, nullable=False),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("deal_id", sa.Uuid),
        sa.Column("entity_id", sa.Uuid, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("number", sa.String(40)),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("issue_date", sa.Date),
        sa.Column("due_date", sa.Date),
        sa.Column("pay_link", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("pay_direct", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text),
        _money("subtotal_minor"),
        _money("discount_minor"),
        _money("tax_minor"),
        _money("total_minor"),
        _money("paid_minor"),
        sa.Column("tax_breakdown", JSONB, nullable=False, server_default="[]"),
        sa.Column("repeat_months", sa.Integer),
        sa.Column("repeat_next_date", sa.Date),
        sa.Column("repeated_from_id", sa.Uuid),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("issued_by_user_id", sa.Uuid),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column("voided_by_user_id", sa.Uuid),
        sa.Column("void_reason", sa.String(500)),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        *_ts(),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'partly_paid', 'paid', 'void')", name="status_valid"
        ),
        sa.CheckConstraint(
            "subtotal_minor >= 0 AND discount_minor >= 0 AND tax_minor >= 0 AND paid_minor >= 0 "
            "AND total_minor = subtotal_minor + tax_minor AND paid_minor <= total_minor",
            name="sums_valid",
        ),
        sa.CheckConstraint("(status = 'draft') = (number IS NULL)", name="number_once_issued"),
        sa.CheckConstraint(
            "status = 'draft' OR (issue_date IS NOT NULL AND due_date IS NOT NULL "
            "AND due_date >= issue_date AND issued_at IS NOT NULL)",
            name="issued_has_dates",
        ),
        sa.CheckConstraint(
            "(status = 'void') = (voided_at IS NOT NULL AND void_reason IS NOT NULL)",
            name="void_has_reason",
        ),
        sa.CheckConstraint("pay_link OR pay_direct", name="some_way_to_pay"),
        sa.CheckConstraint(
            "repeat_months IS NULL OR repeat_months IN (1, 3, 6, 12)", name="repeat_valid"
        ),
        sa.UniqueConstraint("tenant_id", "entity_id", "number", name="uq_invoices_number"),
        _same_tenant("customer_id", "customers", "fk_invoices_customer_same_tenant"),
        _same_tenant("lead_id", "leads", "fk_invoices_lead_same_tenant"),
        _same_tenant("entity_id", "billing_entities", "fk_invoices_entity_same_tenant"),
        _same_tenant("created_by_user_id", "users", "fk_invoices_creator_same_tenant"),
        _same_tenant("issued_by_user_id", "users", "fk_invoices_issuer_same_tenant"),
        _same_tenant("voided_by_user_id", "users", "fk_invoices_voider_same_tenant"),
    )
    _set_null_fk("invoices", "deal_id", "deals", "fk_invoices_deal_same_tenant")
    _set_null_fk("invoices", "repeated_from_id", "invoices", "fk_invoices_repeat_same_tenant")
    op.create_index("ix_invoices_customer", "invoices", ["customer_id"])
    op.create_index("ix_invoices_lead", "invoices", ["lead_id"])
    op.create_index("ix_invoices_status_due", "invoices", ["tenant_id", "status", "due_date"])

    op.create_table(
        "invoice_lines",
        *_base("invoice_lines"),
        sa.Column("invoice_id", sa.Uuid, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("product_id", sa.Uuid),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger, nullable=False),
        _money("discount_minor"),
        sa.Column("net_minor", sa.BigInteger, nullable=False),
        sa.Column("tax_rate_id", sa.Uuid),
        sa.Column("tax_name", sa.String(60)),
        # Copied from the tax rate, so changing a rate never changes an old invoice.
        sa.Column("tax_parts", JSONB, nullable=False, server_default="[]"),
        _money("tax_minor"),
        sa.Column("total_minor", sa.BigInteger, nullable=False),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 100000 AND unit_price_minor >= 0 AND discount_minor >= 0 "
            "AND net_minor = quantity * unit_price_minor - discount_minor AND net_minor >= 0 "
            "AND tax_minor >= 0 AND total_minor = net_minor + tax_minor",
            name="line_sums_valid",
        ),
        sa.UniqueConstraint("invoice_id", "position", name="uq_invoice_lines_position"),
        _same_tenant("invoice_id", "invoices", "fk_invoice_lines_invoice_same_tenant", "CASCADE"),
    )
    _set_null_fk("invoice_lines", "product_id", "products", "fk_invoice_lines_product_same_tenant")
    _set_null_fk("invoice_lines", "tax_rate_id", "tax_rates", "fk_invoice_lines_tax_same_tenant")

    op.create_table(
        "installments",
        *_base("installments"),
        sa.Column("invoice_id", sa.Uuid, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        _money("paid_minor"),
        sa.Column("before_sent_on", sa.Date),
        sa.Column("due_sent_on", sa.Date),
        sa.Column("overdue_sent_on", sa.Date),
        sa.CheckConstraint(
            "amount_minor > 0 AND paid_minor >= 0 AND paid_minor <= amount_minor",
            name="amounts_valid",
        ),
        sa.UniqueConstraint("invoice_id", "position", name="uq_installments_position"),
        _same_tenant("invoice_id", "invoices", "fk_installments_invoice_same_tenant", "CASCADE"),
    )
    op.create_index("ix_installments_due", "installments", ["tenant_id", "due_date"])

    op.create_table(
        "gateway_accounts",
        *_base("gateway_accounts"),
        sa.Column("entity_id", sa.Uuid, nullable=False),
        sa.Column("gateway", sa.String(10), nullable=False),
        sa.Column("key_id", sa.String(200)),  # Razorpay key id (Stripe needs none)
        sa.Column("secret_enc", sa.Text, nullable=False),
        sa.Column("webhook_secret_enc", sa.Text, nullable=False),
        sa.Column("mode", sa.String(4), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint("gateway IN ('razorpay', 'stripe')", name="gateway_valid"),
        sa.CheckConstraint("mode IN ('test', 'live')", name="mode_valid"),
        sa.UniqueConstraint("tenant_id", "entity_id", "gateway", name="uq_gateway_accounts_entity"),
        _same_tenant(
            "entity_id", "billing_entities", "fk_gateway_accounts_entity_same_tenant", "CASCADE"
        ),
    )
    _set_null_fk(
        "gateway_accounts", "created_by_user_id", "users", "fk_gateway_accounts_creator_same_tenant"
    )

    op.create_table(
        "payments",
        *_base("payments"),
        sa.Column("invoice_id", sa.Uuid, nullable=False),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("entity_id", sa.Uuid, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("paid_on", sa.Date, nullable=False),
        sa.Column("reference", sa.String(120)),
        sa.Column("gateway_account_id", sa.Uuid),
        sa.Column("gateway_payment_id", sa.String(100)),
        sa.Column("proof_file_id", sa.Uuid),
        sa.Column("receipt_number", sa.String(40), nullable=False),
        sa.Column("recorded_by_user_id", sa.Uuid),
        sa.Column("status", sa.String(8), nullable=False, server_default="ok"),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.Column("reversed_by_user_id", sa.Uuid),
        sa.Column("reverse_reason", sa.String(500)),
        _created(),
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint(
            "method IN ('gateway', 'bank', 'upi', 'cash', 'cheque', 'card', 'other')",
            name="method_valid",
        ),
        sa.CheckConstraint(
            "(method = 'gateway') = (gateway_payment_id IS NOT NULL)", name="gateway_has_id"
        ),
        # Spec rule: every manually recorded payment has proof attached.
        sa.CheckConstraint(
            "method = 'gateway' OR proof_file_id IS NOT NULL", name="manual_has_proof"
        ),
        sa.CheckConstraint("status IN ('ok', 'reversed')", name="status_valid"),
        sa.CheckConstraint(
            "(status = 'reversed') = (reversed_at IS NOT NULL AND reverse_reason IS NOT NULL)",
            name="reversed_has_reason",
        ),
        sa.UniqueConstraint("tenant_id", "entity_id", "receipt_number", name="uq_payments_receipt"),
        sa.UniqueConstraint(
            "tenant_id", "gateway_account_id", "gateway_payment_id", name="uq_payments_gateway_id"
        ),
        _same_tenant("invoice_id", "invoices", "fk_payments_invoice_same_tenant"),
        _same_tenant("lead_id", "leads", "fk_payments_lead_same_tenant"),
        _same_tenant("entity_id", "billing_entities", "fk_payments_entity_same_tenant"),
        _same_tenant("proof_file_id", "files", "fk_payments_proof_same_tenant"),
        _same_tenant("recorded_by_user_id", "users", "fk_payments_recorder_same_tenant"),
        _same_tenant("reversed_by_user_id", "users", "fk_payments_reverser_same_tenant"),
    )
    _set_null_fk(
        "payments", "gateway_account_id", "gateway_accounts", "fk_payments_gateway_same_tenant"
    )
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"])
    op.create_index("ix_payments_paid_on", "payments", ["tenant_id", "paid_on"])

    op.create_table(
        "payment_allocations",
        *_base("payment_allocations"),
        sa.Column("payment_id", sa.Uuid, nullable=False),
        sa.Column("installment_id", sa.Uuid, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.UniqueConstraint("payment_id", "installment_id", name="uq_payment_allocations_pair"),
        _same_tenant(
            "payment_id", "payments", "fk_payment_allocations_payment_same_tenant", "CASCADE"
        ),
        _same_tenant(
            "installment_id", "installments", "fk_payment_allocations_inst_same_tenant", "CASCADE"
        ),
    )

    op.create_table(
        "payment_links",
        *_base("payment_links"),
        sa.Column("invoice_id", sa.Uuid, nullable=False),
        sa.Column("installment_id", sa.Uuid),
        sa.Column("gateway_account_id", sa.Uuid, nullable=False),
        sa.Column("gateway", sa.String(10), nullable=False),
        sa.Column("gateway_link_id", sa.String(100), nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("status", sa.String(9), nullable=False, server_default="active"),
        sa.Column("payment_id", sa.Uuid),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        _created(),
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint(
            "status IN ('active', 'paid', 'cancelled', 'flagged')", name="status_valid"
        ),
        sa.UniqueConstraint(
            "tenant_id", "gateway_account_id", "gateway_link_id", name="uq_payment_links_gateway"
        ),
        _same_tenant("invoice_id", "invoices", "fk_payment_links_invoice_same_tenant", "CASCADE"),
        _same_tenant(
            "gateway_account_id", "gateway_accounts", "fk_payment_links_account_same_tenant"
        ),
    )
    _set_null_fk(
        "payment_links", "installment_id", "installments", "fk_payment_links_inst_same_tenant"
    )
    _set_null_fk("payment_links", "payment_id", "payments", "fk_payment_links_payment_same_tenant")
    _set_null_fk(
        "payment_links", "created_by_user_id", "users", "fk_payment_links_creator_same_tenant"
    )
    op.create_index("ix_payment_links_invoice", "payment_links", ["invoice_id"])

    op.create_table(
        "gateway_events",
        *_base("gateway_events"),
        sa.Column("gateway_account_id", sa.Uuid, nullable=False),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("result", sa.String(20), nullable=False),  # applied / ignored / flagged
        sa.Column("detail", sa.String(500)),
        _created(),
        sa.UniqueConstraint(
            "tenant_id", "gateway_account_id", "event_id", name="uq_gateway_events_event"
        ),
        _same_tenant(
            "gateway_account_id",
            "gateway_accounts",
            "fk_gateway_events_account_same_tenant",
            "CASCADE",
        ),
    )

    op.create_table(
        "mail_accounts",
        *_base("mail_accounts"),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer, nullable=False),
        sa.Column("security", sa.String(8), nullable=False),  # ssl / starttls
        sa.Column("username", sa.String(254), nullable=False),
        sa.Column("password_enc", sa.Text, nullable=False),
        sa.Column("from_name", sa.String(120), nullable=False),
        sa.Column("from_email", sa.String(254), nullable=False),
        sa.Column("reply_to", sa.String(254)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        *_ts(),
        sa.CheckConstraint("security IN ('ssl', 'starttls')", name="security_valid"),
        sa.CheckConstraint("port IN (25, 465, 587, 2525)", name="port_valid"),
        sa.UniqueConstraint("tenant_id", name="uq_mail_accounts_tenant"),
    )

    op.create_table(
        "money_messages",
        *_base("money_messages"),
        sa.Column("invoice_id", sa.Uuid, nullable=False),
        sa.Column("payment_id", sa.Uuid),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False, server_default="email"),
        sa.Column("to_address", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("status", sa.String(7), nullable=False, server_default="queued"),
        sa.Column("error", sa.String(500)),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        _created(),
        sa.CheckConstraint("kind IN ('invoice', 'receipt', 'reminder', 'void')", name="kind_valid"),
        sa.CheckConstraint("status IN ('queued', 'sent', 'failed')", name="status_valid"),
        _same_tenant("invoice_id", "invoices", "fk_money_messages_invoice_same_tenant", "CASCADE"),
    )
    _set_null_fk(
        "money_messages", "payment_id", "payments", "fk_money_messages_payment_same_tenant"
    )
    _set_null_fk(
        "money_messages", "created_by_user_id", "users", "fk_money_messages_creator_same_tenant"
    )
    op.create_index("ix_money_messages_invoice", "money_messages", ["invoice_id"])

    for table in TENANT_TABLES:
        enable_tenant_rls(table)

    conn = op.get_bind()
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        for key, codes in DEFAULT_GRANTS.items():
            for code in codes:
                conn.execute(
                    sa.text(
                        "INSERT INTO role_permissions (tenant_id, role_id, permission_code) "
                        "SELECT tenant_id, id, :code FROM roles WHERE key = :key "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"code": code, "key": key},
                )
        for key, label, icon in SYSTEM_TYPES:  # only where the CRM is already set up
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
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:codes)"),
            {"codes": ALL},
        )
        conn.execute(sa.text("DELETE FROM tasks WHERE created_from = 'money'"))
        # Payment proofs are files with no document; they go with the payments.
        proofs = conn.execute(sa.text("DELETE FROM payments RETURNING proof_file_id")).scalars()
        conn.execute(
            sa.text("DELETE FROM files WHERE id = ANY(:ids)"),
            {"ids": [p for p in proofs.all() if p]},
        )
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    for table in (
        "money_messages",
        "mail_accounts",
        "gateway_events",
        "payment_links",
        "payment_allocations",
        "payments",
        "gateway_accounts",
        "installments",
        "invoice_lines",
        "invoices",
        "tax_rates",
        "billing_entities",
    ):
        op.drop_table(table)
    op.drop_constraint("money_settings_valid", "tenant_settings")
    for col in (
        "money_reminder_before_days",
        "money_overdue_every_days",
        "money_default_pay",
        "money_emails",
    ):
        op.drop_column("tenant_settings", col)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": ALL})

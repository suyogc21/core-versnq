"""Step 5 — customers and documents: a lead becomes a customer (number, since, status, fields);
company document checklist; each customer's documents with review status; stored files (on our
own server, Decision log #29); secure customer links; storage quota and link settings;
customers.* and documents.verify permissions (Finance reads every customer)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

TENANT_TABLES = ("customers", "document_requirements", "documents", "files", "customer_links")

PERMISSIONS = [
    ("customers.read", "crm", "See customers and their documents"),
    ("customers.create", "crm", "Make leads into customers"),
    ("documents.verify", "crm", "Verify or reject customers' documents"),
]
DEFAULT_GRANTS = {
    "admin": ["customers.read", "customers.create", "documents.verify"],
    "sales_manager": ["customers.read", "customers.create", "documents.verify"],
    "sales_user": ["customers.read", "customers.create"],
    "finance": ["customers.read"],
}
# Frozen copy of app/modules/crm/setup.py STEP5_SYSTEM_TYPES.
SYSTEM_TYPES = [
    ("became_customer", "Became a customer", "badge-check"),
    ("customer_updated", "Customer changed", "pencil"),
    ("document_uploaded", "Document uploaded", "file-up"),
    ("document_verified", "Document verified", "file-check"),
    ("document_rejected", "Document rejected", "file-x"),
    ("document_deleted", "Document file deleted", "trash"),
    ("customer_submitted", "Submitted by the customer", "send"),
]
GB = 1024**3


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
    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS],
    )
    for name, type_, default in (
        ("customer_prefix", sa.String(10), "C-"),
        ("next_customer_number", sa.Integer, "1"),
        ("link_days", sa.Integer, "14"),
        ("document_reminder_days", sa.Integer, "3"),
        ("storage_quota_bytes", sa.BigInteger, str(2 * GB)),
    ):
        op.add_column(
            "tenant_settings", sa.Column(name, type_, nullable=False, server_default=default)
        )
    op.create_check_constraint(
        "customer_settings_valid",
        "tenant_settings",
        "next_customer_number >= 1 AND link_days BETWEEN 1 AND 90 "
        "AND document_reminder_days BETWEEN 1 AND 60 AND storage_quota_bytes > 0",
    )

    op.create_table(
        "customers",
        *_base("customers"),
        sa.Column("lead_id", sa.Uuid, nullable=False),
        sa.Column("number", sa.String(30), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="active"),
        sa.Column("custom_fields", JSONB, nullable=False, server_default="{}"),
        sa.Column("won_deal_id", sa.Uuid),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        *_ts(),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="status_valid"),
        sa.UniqueConstraint("tenant_id", "lead_id", name="uq_customers_lead"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_customers_number"),
        _same_tenant("lead_id", "leads", "fk_customers_lead_same_tenant", "CASCADE"),
        _same_tenant("created_by_user_id", "users", "fk_customers_creator_same_tenant"),
    )
    _set_null_fk("customers", "won_deal_id", "deals", "fk_customers_deal_same_tenant")

    op.create_table(
        "document_requirements",
        *_base("document_requirements"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("hint", sa.String(300)),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("allow_office", sa.Boolean, nullable=False, server_default=sa.false()),
        # Empty = every customer; otherwise only customers with a won deal for these products.
        sa.Column("product_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False),
        *_ts(),
        sa.CheckConstraint("jsonb_typeof(product_ids) = 'array'", name="products_is_list"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_document_requirements_name"),
    )

    op.create_table(
        "documents",
        *_base("documents"),
        sa.Column("customer_id", sa.Uuid, nullable=False),
        sa.Column("requirement_id", sa.Uuid),  # None: "Other documents"
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="pending"),
        sa.Column("reject_reason", sa.String(500)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_user_id", sa.Uuid),
        *_ts(),
        sa.CheckConstraint(
            "status IN ('pending', 'received', 'verified', 'rejected')", name="status_valid"
        ),
        sa.CheckConstraint(
            "(status = 'rejected') = (reject_reason IS NOT NULL)", name="rejected_has_reason"
        ),
        sa.CheckConstraint(
            "(status IN ('verified', 'rejected')) = (reviewed_at IS NOT NULL)",
            name="reviewed_matches",
        ),
        _same_tenant("customer_id", "customers", "fk_documents_customer_same_tenant", "CASCADE"),
        _same_tenant("reviewed_by_user_id", "users", "fk_documents_reviewer_same_tenant"),
    )
    _set_null_fk(
        "documents", "requirement_id", "document_requirements", "fk_documents_req_same_tenant"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_requirement ON documents (customer_id, requirement_id) "
        "WHERE requirement_id IS NOT NULL"
    )
    op.create_index("ix_documents_customer", "documents", ["customer_id"])

    op.create_table(
        "customer_links",
        *_base("customer_links"),
        sa.Column("customer_id", sa.Uuid, nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("field_keys", JSONB, nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid),
        *_ts(),
        sa.UniqueConstraint("code_hash", name="uq_customer_links_code"),
        _same_tenant(
            "customer_id", "customers", "fk_customer_links_customer_same_tenant", "CASCADE"
        ),
        _same_tenant("created_by_user_id", "users", "fk_customer_links_creator_same_tenant"),
    )
    op.create_index("ix_customer_links_customer", "customer_links", ["customer_id"])

    op.create_table(
        "files",
        *_base("files"),
        sa.Column("lead_id", sa.Uuid, nullable=False),  # whose file it is (quota, clean-up)
        sa.Column("document_id", sa.Uuid),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_via", sa.String(4), nullable=False),  # user / link
        sa.Column("uploaded_by_user_id", sa.Uuid),
        sa.Column("link_id", sa.Uuid),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("size_bytes > 0", name="size_positive"),
        sa.CheckConstraint("uploaded_via IN ('user', 'link')", name="via_valid"),
        sa.CheckConstraint("uploaded_via = 'link' OR link_id IS NULL", name="link_only_via_link"),
        sa.UniqueConstraint("path", name="uq_files_path"),
        _same_tenant("lead_id", "leads", "fk_files_lead_same_tenant", "CASCADE"),
        _same_tenant("document_id", "documents", "fk_files_document_same_tenant", "CASCADE"),
    )
    _set_null_fk("files", "uploaded_by_user_id", "users", "fk_files_uploader_same_tenant")
    _set_null_fk("files", "link_id", "customer_links", "fk_files_link_same_tenant")
    op.create_index("ix_files_document", "files", ["document_id"])
    op.create_index("ix_files_lead", "files", ["lead_id"])

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
    codes = [c for c, _, _ in PERMISSIONS]
    keys = [k for k, _, _ in SYSTEM_TYPES]
    for tenant_id in conn.execute(sa.text("SELECT id FROM tenants")).scalars().all():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(sa.text("DELETE FROM activities WHERE type_key = ANY(:k)"), {"k": keys})
        conn.execute(sa.text("DELETE FROM activity_types WHERE key = ANY(:k)"), {"k": keys})
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = ANY(:codes)"),
            {"codes": codes},
        )
        conn.execute(sa.text("DELETE FROM custom_field_unique_values WHERE entity = 'customer'"))
        conn.execute(sa.text("DELETE FROM custom_field_definitions WHERE entity = 'customer'"))
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(table)
    for table in ("files", "customer_links", "documents", "document_requirements", "customers"):
        op.drop_table(table)
    op.drop_constraint("customer_settings_valid", "tenant_settings")
    for col in (
        "customer_prefix",
        "next_customer_number",
        "link_days",
        "document_reminder_days",
        "storage_quota_bytes",
    ):
        op.drop_column("tenant_settings", col)
    conn.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})

"""Several brands in one company (finish plan, batch 4; approved by Suyog Nov 16).

brands: a company's brands (name, colour, logo address, website, the billing entity whose header
its invoices use, default, active). A nullable brand_id on leads, deals, invoices,
capture_sources (forms), mailboxes and whatsapp_accounts. user_brands: the brands a person is
limited to (none listed = every brand). Brands are never deleted, only switched off, so the
brand_id columns need no ON DELETE rule.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

BRANDED = ("leads", "deals", "invoices", "capture_sources", "mailboxes", "whatsapp_accounts")


def _same_tenant(col: str, ref: str, name: str, ondelete: str | None = None):
    return sa.ForeignKeyConstraint(
        ["tenant_id", col], [f"{ref}.tenant_id", f"{ref}.id"], name=name, ondelete=ondelete
    )


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "brands",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("colour", sa.String(7)),
        sa.Column("logo_url", sa.String(500)),
        sa.Column("website", sa.String(300)),
        sa.Column("billing_entity_id", sa.Uuid),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_brands_tenant_id_id"),
        _same_tenant("billing_entity_id", "billing_entities", "fk_brands_entity_same_tenant"),
    )
    op.create_index("uq_brands_name", "brands", ["tenant_id", sa.text("lower(name)")], unique=True)
    op.create_index(
        "uq_brands_one_default", "brands", ["tenant_id"], unique=True,
        postgresql_where=sa.text("is_default"),
    )  # fmt: skip
    enable_tenant_rls("brands")

    op.create_table(
        "user_brands",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("brand_id", sa.Uuid, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", "brand_id", name="uq_user_brands"),
        _same_tenant("user_id", "users", "fk_user_brands_user_same_tenant", "CASCADE"),
        _same_tenant("brand_id", "brands", "fk_user_brands_brand_same_tenant", "CASCADE"),
    )
    enable_tenant_rls("user_brands")

    for table in BRANDED:
        op.add_column(table, sa.Column("brand_id", sa.Uuid))
        op.create_foreign_key(
            f"fk_{table}_brand_same_tenant", table, "brands",
            ["tenant_id", "brand_id"], ["tenant_id", "id"],
        )  # fmt: skip
    op.create_index("ix_leads_brand", "leads", ["tenant_id", "brand_id"])
    op.create_index("ix_deals_brand", "deals", ["tenant_id", "brand_id"])


def downgrade() -> None:
    op.drop_index("ix_deals_brand", "deals")
    op.drop_index("ix_leads_brand", "leads")
    for table in BRANDED:
        op.drop_constraint(f"fk_{table}_brand_same_tenant", table, type_="foreignkey")
        op.drop_column(table, "brand_id")
    disable_tenant_rls("user_brands")
    op.drop_table("user_brands")
    disable_tenant_rls("brands")
    op.drop_index("uq_brands_one_default", "brands")
    op.drop_index("uq_brands_name", "brands")
    op.drop_table("brands")

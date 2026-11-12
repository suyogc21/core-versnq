"""Step 8 — page layouts and field permissions (Decision log #38).

record_layouts: one per company per kind of record (lead, deal, customer, rt:<key>): sections
with their fields in order, up to 4 highlights, and the add-form fields. No row = today's page.
field_permissions: per role, kind of record and field ("org_name", "amount", "cf.<key>"):
'view' or 'hidden'; no row = edit. A calculated field built from a hidden field is hidden too
unless custom_field_definitions.show_with_hidden_inputs is set.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

TABLES = ("record_layouts", "field_permissions")


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


def upgrade() -> None:
    op.create_table(
        "record_layouts",
        *_base("record_layouts"),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("sections", JSONB, nullable=False),  # [{"name", "fields": [keys]}]
        sa.Column("highlights", JSONB, nullable=False),  # [keys], at most 4
        sa.Column("add_form", JSONB, nullable=False),  # [keys]
        sa.Column("updated_by_user_id", sa.Uuid),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "entity", name="uq_record_layouts_entity"),
    )
    op.create_table(
        "field_permissions",
        *_base("field_permissions"),
        sa.Column("role_id", sa.Uuid, nullable=False),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("field", sa.String(70), nullable=False),
        sa.Column("access", sa.String(6), nullable=False),
        *_ts(),
        sa.CheckConstraint("access IN ('view', 'hidden')", name="access_valid"),
        sa.UniqueConstraint("tenant_id", "role_id", "entity", "field", name="uq_field_permissions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_field_permissions_role_same_tenant",
            ondelete="CASCADE",
        ),
    )
    op.add_column(
        "custom_field_definitions",
        sa.Column("show_with_hidden_inputs", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    for table in TABLES:
        enable_tenant_rls(table)


def downgrade() -> None:
    op.drop_column("custom_field_definitions", "show_with_hidden_inputs")
    for table in reversed(TABLES):
        disable_tenant_rls(table)
        op.drop_table(table)

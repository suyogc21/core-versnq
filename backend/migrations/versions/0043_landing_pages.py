"""Landing pages (finishing plan, batch 5a; approved by Suyog Nov 16).

landing_pages: a company's simple pages at /p/<slug> on its own address, made of blocks
(heading, text, image, video, one of its hosted forms, a button), with a visit count. Leads that
come through a page's form carry attribution landing_page = /p/<slug>, so each page's lead count
is counted from the leads themselves. Permission pages.manage (Owner and Admin by default).

A/B tests on sequence email steps need no schema: the variant lives in the step's config and
messages.variant already records which one was sent.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import disable_tenant_rls, enable_tenant_rls

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

PERMISSIONS = [("pages.manage", "crm", "Build and publish landing pages")]
GRANTS = {"admin": ["pages.manage"]}


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "landing_pages",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("blocks", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("brand_id", sa.Uuid),
        sa.Column("seo_title", sa.String(200)),
        sa.Column("seo_description", sa.String(300)),
        sa.Column("visits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Uuid),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_landing_pages_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_landing_pages_slug"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "brand_id"],
            ["brands.tenant_id", "brands.id"],
            name="fk_landing_pages_brand_same_tenant",
        ),  # fmt: skip
    )
    enable_tenant_rls("landing_pages")
    op.create_index(
        "ix_leads_landing_page",
        "leads",
        ["tenant_id", sa.text("(attribution->>'landing_page')")],
    )

    op.bulk_insert(
        sa.table("permissions", sa.column("code"), sa.column("module"), sa.column("description")),
        [dict(zip(("code", "module", "description"), p, strict=True)) for p in PERMISSIONS],
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
    conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    op.execute("DELETE FROM permissions WHERE code = 'pages.manage'")
    op.drop_index("ix_leads_landing_page", table_name="leads")
    disable_tenant_rls("landing_pages")
    op.drop_table("landing_pages")

"""WhatsApp extras on the company number (finish plan, batch 3; approved by Suyog Nov 16).

whatsapp_templates.header: the template's header, {format: text|image|video|document, text?,
path?, content_type?, name?, media_id?, media_at?}; the example file lives on our disk (path).
whatsapp_templates.buttons: [{type: quick_reply|url|phone, text, url?, url_var?, phone?}].
whatsapp_accounts.app_id: the company's Meta app id, needed only to upload a header example
when a template with a photo, video or document header is sent for approval.
Photos, PDFs, voice notes and videos in and out use the existing message_attachments + files.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_templates", sa.Column("header", JSONB))
    op.add_column(
        "whatsapp_templates",
        sa.Column("buttons", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("whatsapp_accounts", sa.Column("app_id", sa.String(40)))


def downgrade() -> None:
    op.drop_column("whatsapp_accounts", "app_id")
    op.drop_column("whatsapp_templates", "buttons")
    op.drop_column("whatsapp_templates", "header")

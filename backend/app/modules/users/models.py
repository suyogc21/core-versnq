import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import IdMixin, TimestampMixin
from app.modules.roles import models as _roles  # noqa: F401  (roles table must be registered)


class User(IdMixin, TimestampMixin, Base):
    """A person who logs in to one tenant (admin, salesperson, finance...)."""

    __tablename__ = "users"
    __table_args__ = (
        # role must belong to the same tenant: enforced by the database
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_users_role_same_tenant",
        ),
        Index("uq_users_tenant_email", "tenant_id", text("lower(email)"), unique=True),
        CheckConstraint("status IN ('invited', 'active', 'disabled')", name="status_valid"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

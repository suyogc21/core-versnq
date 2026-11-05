import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import IdMixin, TimestampMixin


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_roles_tenant_id_id"
        ),  # target for tenant-safe FKs
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
        CheckConstraint("scope IN ('own', 'team', 'all')", name="scope_valid"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(80))
    key: Mapped[str | None] = mapped_column(String(40))  # system roles: owner, admin, ...
    scope: Mapped[str] = mapped_column(String(10))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class Permission(Base):
    """Global catalogue (no tenant_id); rows come from migrations."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(60), primary_key=True)
    module: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="fk_role_permissions_role_same_tenant",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    permission_code: Mapped[str] = mapped_column(
        String(60), ForeignKey("permissions.code"), primary_key=True
    )

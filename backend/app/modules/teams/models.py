import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import IdMixin, TimestampMixin
from app.modules.users import models as _users  # noqa: F401


class Team(IdMixin, TimestampMixin, Base):
    """Teams nest to any depth through parent_team_id."""

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_teams_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_teams_tenant_name"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_team_id"],
            ["teams.tenant_id", "teams.id"],
            name="fk_teams_parent_same_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(120))
    parent_team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class TeamMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
        ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["teams.tenant_id", "teams.id"],
            name="fk_team_members_team_same_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_team_members_user_same_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    is_manager: Mapped[bool] = mapped_column(Boolean, default=False)

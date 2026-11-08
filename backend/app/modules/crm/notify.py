"""In-app notifications and who receives alerts about a lead."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import Lead, Notification
from app.modules.roles.models import Role
from app.modules.teams.models import TeamMember
from app.modules.users.models import User


async def notify(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    kind: str,
    title: str,
    lead_id: uuid.UUID | None = None,
) -> None:
    for user_id in dict.fromkeys(user_ids):  # once each, order kept
        db.add(
            Notification(
                tenant_id=tenant_id, user_id=user_id, kind=kind, title=title[:300], lead_id=lead_id
            )
        )


async def managers_of(db: AsyncSession, lead: Lead) -> list[uuid.UUID]:
    """Managers of the lead's team; if there are none, the active Owners and Admins."""
    ids: list[uuid.UUID] = []
    if lead.team_id:
        ids = list(
            (
                await db.scalars(
                    select(TeamMember.user_id)
                    .join(User, User.id == TeamMember.user_id)
                    .where(
                        TeamMember.team_id == lead.team_id,
                        TeamMember.is_manager.is_(True),
                        User.status == "active",
                        User.id != lead.owner_user_id,
                    )
                )
            ).all()
        )
    if not ids:
        ids = list(
            (
                await db.scalars(
                    select(User.id)
                    .join(Role, Role.id == User.role_id)
                    .where(Role.key.in_(["owner", "admin"]), User.status == "active")
                )
            ).all()
        )
    return ids

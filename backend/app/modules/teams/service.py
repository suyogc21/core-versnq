import uuid

from sqlalchemy import Uuid, bindparam, delete, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Invalid, NotFound
from app.modules.audit.models import record
from app.modules.auth.deps import CurrentUser
from app.modules.teams.models import Team, TeamMember
from app.modules.users.models import User

_SUBTREE = text(
    """
    WITH RECURSIVE sub(id) AS (
        SELECT id FROM teams WHERE id = ANY(:roots)
        UNION
        SELECT t.id FROM teams t JOIN sub ON t.parent_team_id = sub.id
    )
    SELECT id FROM sub
    """
).bindparams(bindparam("roots", type_=ARRAY(Uuid)))


async def subtree(db: AsyncSession, roots: set[uuid.UUID]) -> set[uuid.UUID]:
    """The given teams plus every team below them, at any depth."""
    if not roots:
        return set()
    return set((await db.scalars(_SUBTREE, {"roots": list(roots)})).all())


async def visible_user_ids(
    db: AsyncSession, user_id: uuid.UUID, scope: str
) -> set[uuid.UUID] | None:
    """Who this user may see. None = everyone in the tenant."""
    if scope == "all":
        return None
    if scope == "own":
        return {user_id}
    managed = set(
        (
            await db.scalars(
                select(TeamMember.team_id).where(
                    TeamMember.user_id == user_id, TeamMember.is_manager.is_(True)
                )
            )
        ).all()
    )
    teams = await subtree(db, managed)
    if not teams:
        return {user_id}
    members = await db.scalars(
        select(TeamMember.user_id).where(TeamMember.team_id.in_(teams)).distinct()
    )
    return set(members.all()) | {user_id}


async def get_team(db: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFound("Team not found")
    return team


async def _check_parent(db: AsyncSession, team: Team | None, parent_id: uuid.UUID | None) -> None:
    if parent_id is None:
        return
    if await db.get(Team, parent_id) is None:
        raise Invalid("Parent team not found")
    if team is not None and parent_id in await subtree(db, {team.id}):
        raise Invalid("A team cannot be placed under itself or its own sub-team")


def _snap(team: Team) -> dict:
    return {"name": team.name, "parent_team_id": str(team.parent_team_id or "") or None}


async def create_team(
    db: AsyncSession, actor: CurrentUser, name: str, parent_id: uuid.UUID | None
) -> Team:
    await _check_parent(db, None, parent_id)
    team = Team(tenant_id=actor.user.tenant_id, name=name, parent_team_id=parent_id)
    db.add(team)
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict("A team with this name already exists") from None
    await record(
        db,
        tenant_id=team.tenant_id,
        actor_id=actor.user.id,
        action="team.created",
        entity_type="team",
        entity_id=team.id,
        after=_snap(team),
    )
    return team


async def update_team(db: AsyncSession, actor: CurrentUser, team: Team, changes: dict) -> Team:
    before = _snap(team)
    if "parent_id" in changes:
        await _check_parent(db, team, changes["parent_id"])
        team.parent_team_id = changes["parent_id"]
    if changes.get("name"):
        team.name = changes["name"]
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict("A team with this name already exists") from None
    await record(
        db,
        tenant_id=team.tenant_id,
        actor_id=actor.user.id,
        action="team.updated",
        entity_type="team",
        entity_id=team.id,
        before=before,
        after=_snap(team),
    )
    return team


async def delete_team(db: AsyncSession, actor: CurrentUser, team: Team) -> None:
    children = await db.scalar(select(func.count()).where(Team.parent_team_id == team.id))
    if children:
        raise Conflict("Move or delete the sub-teams first")
    before = _snap(team)
    await db.delete(team)
    await record(
        db,
        tenant_id=team.tenant_id,
        actor_id=actor.user.id,
        action="team.deleted",
        entity_type="team",
        entity_id=team.id,
        before=before,
    )


async def set_members(
    db: AsyncSession, actor: CurrentUser, team: Team, members: list[tuple[uuid.UUID, bool]]
) -> list[TeamMember]:
    ids = {uid for uid, _ in members}
    found = set((await db.scalars(select(User.id).where(User.id.in_(ids)))).all()) if ids else set()
    if found != ids:
        raise Invalid("Some users do not exist in this workspace")
    before = await _member_snapshot(db, team.id)
    await db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    rows = [
        TeamMember(tenant_id=team.tenant_id, team_id=team.id, user_id=uid, is_manager=mgr)
        for uid, mgr in members
    ]
    db.add_all(rows)
    await db.flush()
    await record(
        db,
        tenant_id=team.tenant_id,
        actor_id=actor.user.id,
        action="team.members_set",
        entity_type="team",
        entity_id=team.id,
        before=before,
        after=await _member_snapshot(db, team.id),
    )
    return rows


async def _member_snapshot(db: AsyncSession, team_id: uuid.UUID) -> dict:
    rows = (
        await db.execute(
            select(TeamMember.user_id, TeamMember.is_manager).where(TeamMember.team_id == team_id)
        )
    ).all()
    return {"members": sorted([str(u), m] for u, m in rows)}

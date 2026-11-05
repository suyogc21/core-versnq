import uuid
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.modules.auth.deps import CurrentUser, TenantDb, require
from app.modules.teams import service
from app.modules.teams.models import Team, TeamMember

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None


class MemberIn(BaseModel):
    user_id: uuid.UUID
    is_manager: bool = False


class MemberOut(MemberIn):
    pass


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    members: list[MemberOut]


async def _out(db, team: Team) -> TeamOut:
    rows = (await db.scalars(select(TeamMember).where(TeamMember.team_id == team.id))).all()
    return TeamOut(
        id=team.id,
        name=team.name,
        parent_id=team.parent_team_id,
        members=[MemberOut(user_id=m.user_id, is_manager=m.is_manager) for m in rows],
    )


@router.get("", response_model=list[TeamOut])
async def list_teams(
    db: TenantDb, _: Annotated[CurrentUser, require("users.read")]
) -> list[TeamOut]:
    teams = (await db.scalars(select(Team).order_by(Team.name))).all()
    return [await _out(db, t) for t in teams]


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamIn, db: TenantDb, actor: Annotated[CurrentUser, require("teams.manage")]
) -> TeamOut:
    return await _out(db, await service.create_team(db, actor, body.name, body.parent_id))


@router.patch("/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: uuid.UUID,
    body: TeamPatch,
    db: TenantDb,
    actor: Annotated[CurrentUser, require("teams.manage")],
) -> TeamOut:
    team = await service.get_team(db, team_id)
    changes = body.model_dump(include=body.model_fields_set)
    return await _out(db, await service.update_team(db, actor, team, changes))


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID, db: TenantDb, actor: Annotated[CurrentUser, require("teams.manage")]
) -> None:
    await service.delete_team(db, actor, await service.get_team(db, team_id))


@router.put("/{team_id}/members", response_model=TeamOut)
async def set_members(
    team_id: uuid.UUID,
    body: list[MemberIn],
    db: TenantDb,
    actor: Annotated[CurrentUser, require("teams.manage")],
) -> TeamOut:
    team = await service.get_team(db, team_id)
    await service.set_members(db, actor, team, [(m.user_id, m.is_manager) for m in body])
    return await _out(db, team)

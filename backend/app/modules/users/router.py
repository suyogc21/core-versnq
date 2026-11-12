import logging
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.hosts import Workspace
from app.core.mailer import Email, Mailer, get_mailer
from app.modules.auth.deps import CurrentUser, TenantDb, WorkspaceDep, require
from app.modules.roles.models import Role
from app.modules.teams.models import Team, TeamMember
from app.modules.teams.service import visible_user_ids
from app.modules.users import service
from app.modules.users.models import User

log = logging.getLogger("versnq.users")
router = APIRouter(prefix="/api/v1/users", tags=["users"])
MailerDep = Annotated[Mailer, Depends(get_mailer)]
Reader = Annotated[CurrentUser, require("users.read")]
Manager = Annotated[CurrentUser, require("users.manage")]


class InviteIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role_id: uuid.UUID


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    role_id: uuid.UUID | None = None


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    name: str
    phone: str | None
    status: str
    role_id: uuid.UUID
    totp_enabled: bool


class InvitedOut(UserOut):
    invite_sent: bool


class TemporaryPasswordOut(BaseModel):
    temporary_password: str


class InviteResult(BaseModel):
    invite_sent: bool


async def _send_invite(mailer: Mailer, ws: Workspace, user: User, plain: str) -> bool:
    link = f"https://{ws.slug}.{get_settings().base_domain}/invite?token={plain}"
    try:
        await mailer.send(
            Email(
                to=user.email,
                subject=f"You're invited to {ws.name} on Versnq Core",
                body=f"Hi {user.name},\n\nYou have been invited to {ws.name} on Versnq Core.\n"
                f"Set your password here (valid for 72 hours):\n{link}\n",
            )
        )
        return True
    except Exception:
        log.exception("Invite email to %s failed", user.email)
        return False


@router.get("", response_model=list[UserOut])
async def list_users(db: TenantDb, actor: Reader) -> list[User]:
    return await service.list_visible(db, actor)


class UserRow(UserOut):
    role_name: str
    teams: list[str]
    last_login_at: datetime | None


class UserPage(BaseModel):
    items: list[UserRow]
    total: int


USER_SORTS = {
    "name": User.name,
    "email": User.email,
    "role": Role.name,
    "status": User.status,
    "last_login": User.last_login_at,
}


@router.get("/page", response_model=UserPage)
async def page_users(
    db: TenantDb,
    actor: Reader,
    q: Annotated[str | None, Query(max_length=200)] = None,
    role_id: Annotated[list[uuid.UUID], Query()] = [],  # noqa: B006 (FastAPI query default)
    team_id: Annotated[list[uuid.UUID], Query()] = [],  # noqa: B006
    status_: Annotated[list[Literal["invited", "active", "disabled"]], Query(alias="status")] = [],  # noqa: B006
    sort: Literal["name", "email", "role", "status", "last_login"] = "name",
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserPage:
    """Users this person may see, a page at a time, for lists of hundreds of people."""
    where = [User.status != "integration"]  # API keys' users are not team members
    visible = await visible_user_ids(db, actor.user.id, actor.role.scope)
    if visible is not None:
        where.append(User.id.in_(visible))
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        where.append(or_(func.lower(User.name).like(term), func.lower(User.email).like(term)))
    if role_id:
        where.append(User.role_id.in_(role_id))
    if team_id:
        where.append(User.id.in_(select(TeamMember.user_id).where(TeamMember.team_id.in_(team_id))))
    if status_:
        where.append(User.status.in_(status_))
    base = select(User, Role.name).join(Role, Role.id == User.role_id).where(*where)
    total = await db.scalar(select(func.count()).select_from(User).where(*where))
    col = USER_SORTS[sort]
    key = (col.asc() if direction == "asc" else col.desc()).nulls_last()
    rows = (
        await db.execute(base.order_by(key, User.name, User.id).limit(limit).offset(offset))
    ).all()
    ids = [u.id for u, _ in rows]
    teams: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    if ids:
        for user_id, team in await db.execute(
            select(TeamMember.user_id, Team.name)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.user_id.in_(ids))
            .order_by(Team.name)
        ):
            teams[user_id].append(team)
    items = [
        UserRow(
            **UserOut.model_validate(u).model_dump(),
            role_name=role_name,
            teams=teams[u.id],
            last_login_at=u.last_login_at,
        )
        for u, role_name in rows
    ]
    return UserPage(items=items, total=total or 0)


@router.post("", response_model=InvitedOut, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteIn, db: TenantDb, ws: WorkspaceDep, actor: Manager, mailer: MailerDep
) -> InvitedOut:
    user, plain = await service.invite(db, actor, str(body.email), body.name, body.role_id)
    await db.commit()  # the invite link must exist before it is emailed
    sent = await _send_invite(mailer, ws, user, plain)
    return InvitedOut(**UserOut.model_validate(user).model_dump(), invite_sent=sent)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, db: TenantDb, actor: Reader) -> User:
    return await service.get_visible(db, actor, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserPatch, db: TenantDb, actor: Manager) -> User:
    target = await service.get_visible(db, actor, user_id)
    return await service.update(db, actor, target, body.model_dump(include=body.model_fields_set))


@router.post("/{user_id}/disable", response_model=UserOut)
async def disable_user(user_id: uuid.UUID, db: TenantDb, actor: Manager) -> User:
    target = await service.get_visible(db, actor, user_id)
    return await service.set_status(db, actor, target, "disabled")


@router.post("/{user_id}/enable", response_model=UserOut)
async def enable_user(user_id: uuid.UUID, db: TenantDb, actor: Manager) -> User:
    target = await service.get_visible(db, actor, user_id)
    return await service.set_status(db, actor, target, "active")


@router.post("/{user_id}/temporary-password", response_model=TemporaryPasswordOut)
async def temporary_password(
    user_id: uuid.UUID, db: TenantDb, actor: Manager
) -> TemporaryPasswordOut:
    target = await service.get_visible(db, actor, user_id)
    return TemporaryPasswordOut(
        temporary_password=await service.set_temporary_password(db, actor, target)
    )


@router.post("/{user_id}/resend-invite", response_model=InviteResult)
async def resend_invite(
    user_id: uuid.UUID, db: TenantDb, ws: WorkspaceDep, actor: Manager, mailer: MailerDep
) -> InviteResult:
    target = await service.get_visible(db, actor, user_id)
    plain = await service.renew_invite(db, actor, target)
    await db.commit()
    return InviteResult(invite_sent=await _send_invite(mailer, ws, target, plain))

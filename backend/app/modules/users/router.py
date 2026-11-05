import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings
from app.core.hosts import Workspace
from app.core.mailer import Email, Mailer, get_mailer
from app.modules.auth.deps import CurrentUser, TenantDb, WorkspaceDep, require
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

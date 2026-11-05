"""Versnq staff manage other staff accounts (staff console)."""

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_platform_db
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.security import hash_password
from app.platform import audit
from app.platform.staff.models import PlatformStaff
from app.platform.staff.router import current_staff
from app.platform.staff.service import revoke_all_sessions

router = APIRouter(
    prefix="/platform/staff", tags=["platform-staff"], dependencies=[Depends(current_staff)]
)
Db = Annotated[AsyncSession, Depends(get_platform_db)]
Staff = Annotated[PlatformStaff, Depends(current_staff)]


class StaffCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)


class StaffPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class StaffAccountOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    name: str
    is_active: bool
    totp_enabled: bool
    must_change_password: bool


class StaffCreated(StaffAccountOut):
    temporary_password: str


def _snap(s: PlatformStaff) -> dict:
    return {"email": s.email, "name": s.name, "is_active": s.is_active}


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=list[StaffAccountOut])
async def list_staff(db: Db) -> list[PlatformStaff]:
    return list((await db.scalars(select(PlatformStaff).order_by(PlatformStaff.name))).all())


@router.post("", response_model=StaffCreated, status_code=status.HTTP_201_CREATED)
async def create_staff(body: StaffCreate, request: Request, db: Db, actor: Staff) -> StaffCreated:
    """The temporary password is shown once; the new person must change it and set up 2FA."""
    temp = secrets.token_urlsafe(12)
    member = PlatformStaff(
        email=str(body.email),
        name=body.name,
        password_hash=hash_password(temp),
        must_change_password=True,
    )
    db.add(member)
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict("A staff account with this email already exists") from None
    await audit.record(
        db,
        staff_id=actor.id,
        action="staff.created",
        target_type="staff",
        target_id=member.id,
        after=_snap(member),
        ip=_ip(request),
    )
    return StaffCreated(
        **StaffAccountOut.model_validate(member).model_dump(), temporary_password=temp
    )


@router.patch("/{staff_id}", response_model=StaffAccountOut)
async def update_staff(
    staff_id: uuid.UUID, body: StaffPatch, request: Request, db: Db, actor: Staff
) -> PlatformStaff:
    member = await db.get(PlatformStaff, staff_id)
    if member is None:
        raise NotFound("Staff account not found")
    before = _snap(member)
    if body.is_active is not None and body.is_active != member.is_active:
        if member.id == actor.id:
            raise Forbidden("You cannot deactivate your own account")
        member.is_active = body.is_active
        if not body.is_active:
            await revoke_all_sessions(db, member.id)
    if body.name:
        member.name = body.name
    await audit.record(
        db,
        staff_id=actor.id,
        action="staff.updated",
        target_type="staff",
        target_id=member.id,
        before=before,
        after=_snap(member),
        ip=_ip(request),
    )
    return member

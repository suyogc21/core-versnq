"""The Android app's phone key (calls plan C4.2, docs/plans/android-app-plan.md).

The rep signs in to Core inside the app as usual; the page then asks Core for a key for this
phone (`POST /api/v1/phone/devices`) and hands it to the app's native part, which uses it from
then on, even while the app is closed. The key acts as the rep but works only on:
- `POST /api/v1/calls`: report a call from the phone's call log;
- `PUT /api/v1/calls/{id}/recording`: upload that call's recording;
- `GET /api/v1/phone/me`: check the key and whether the company records calls;
- `GET /api/v1/phone/lookup?number=`: who is calling (the caller popup, C4.4), only among the
  leads this rep may see; the number isn't stored.
Everything else answers 401. The rep (My account) or an admin (Settings → Calls) can remove a
phone; reconnecting the same install replaces its old key.
"""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import CurrentUser, WorkspaceDep, current_user, has_permission, require
from app.modules.calls import service as S
from app.modules.calls.models import PhoneDevice
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.identities import normalize
from app.modules.crm.models import Lead, LeadIdentity, LeadStage
from app.modules.users.models import User

PREFIX = "vq_app_"
# (method, path) the phone key may use; nothing else.
ALLOWED = (
    ("POST", re.compile(r"^/api/v1/calls$")),
    ("PUT", re.compile(r"^/api/v1/calls/[0-9a-fA-F-]{36}/recording$")),
    ("GET", re.compile(r"^/api/v1/phone/me$")),
    ("GET", re.compile(r"^/api/v1/phone/lookup$")),
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


def allowed(method: str, path: str) -> bool:
    return any(method == m and p.match(path) for m, p in ALLOWED)


async def token_user(db: AsyncSession, token: str) -> tuple[PhoneDevice, User] | None:
    """Used by auth.deps for `vq_app_…` keys."""
    row = await db.scalar(
        select(PhoneDevice).where(
            PhoneDevice.token_hash == _hash(token), PhoneDevice.revoked_at.is_(None)
        )
    )
    if row is None:
        return None
    user = await db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if row.last_used_at is None or now() - row.last_used_at > timedelta(seconds=60):
        row.last_used_at = now()
    return row, user


async def note_call(db: AsyncSession, request: Request) -> None:
    """A call reported with a phone key: remember when this phone last sent one."""
    device_id = getattr(request.state, "phone_device", None)
    if device_id and (row := await db.get(PhoneDevice, device_id)):
        row.last_call_at = now()


# ---------- shapes ----------
class ConnectIn(BaseModel):
    install_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    device: str | None = Field(default=None, max_length=120)
    version: str | None = Field(default=None, max_length=20)


class ConnectOut(BaseModel):
    token: str  # shown once; the app keeps it
    device_id: uuid.UUID


class DeviceOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    device: str | None
    version: str | None
    created_at: datetime
    last_used_at: datetime | None
    last_call_at: datetime | None


class PhoneMeOut(BaseModel):
    user_name: str
    company: str
    record_calls: bool  # the company's setting: upload recordings or not


class CallerOut(BaseModel):
    lead_id: uuid.UUID
    name: str
    stage: str | None
    owner_name: str | None
    is_yours: bool


async def _out(db, rows) -> list[DeviceOut]:
    ids = {r.user_id for r in rows}
    names = dict((await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()) \
        if ids else {}  # fmt: skip
    return [
        DeviceOut(
            id=r.id,
            user_id=r.user_id,
            user_name=names.get(r.user_id, ""),
            device=r.device,
            version=r.version,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            last_call_at=r.last_call_at,
        )  # fmt: skip
        for r in rows
    ]


router = APIRouter(prefix="/api/v1/phone", tags=["phone-app"], dependencies=CRM)
Rep = Annotated[CurrentUser, require("leads.edit")]
Admin = Annotated[CurrentUser, require("settings.manage")]
Phone = Annotated[CurrentUser, Depends(current_user)]


@router.post("/devices", response_model=ConnectOut, status_code=status.HTTP_201_CREATED)
async def connect(request: Request, body: ConnectIn, db: CrmDb, actor: Rep) -> ConnectOut:
    """A key for this phone, asked for by the signed-in rep's page inside the app. Only a person
    signed in normally can ask (not an API key, not another phone)."""
    if actor.user.status == "integration" or getattr(request.state, "phone_device", None):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in to Core inside the app")
    same_install = PhoneDevice.install_id == body.install_id, PhoneDevice.revoked_at.is_(None)
    old = (await db.scalars(select(PhoneDevice).where(*same_install))).all()
    for row in old:  # the same install reconnecting (or another rep on the same phone)
        row.revoked_at = now()
    token = PREFIX + secrets.token_urlsafe(32)
    row = PhoneDevice(
        id=uuid.uuid4(), tenant_id=actor.user.tenant_id, user_id=actor.user.id,
        token_hash=_hash(token), install_id=body.install_id, device=body.device,
        version=body.version, last_used_at=now(),
    )  # fmt: skip
    db.add(row)
    await db.flush()
    await audit(db, actor, "phone.connected", "phone_device", row.id)
    return ConnectOut(token=token, device_id=row.id)


@router.get("/me", response_model=PhoneMeOut)
async def phone_me(db: CrmDb, actor: Phone, workspace: WorkspaceDep) -> PhoneMeOut:
    settings = await S.settings_of(db, actor.user.tenant_id)
    return PhoneMeOut(
        user_name=actor.user.name, company=workspace.slug, record_calls=bool(settings["record"])
    )


@router.get("/lookup", response_model=CallerOut | None)
async def lookup(number: str, db: CrmDb, actor: Phone) -> CallerOut | None:
    """Who is calling: the lead with this number, among the leads this rep may see."""
    try:
        phone = normalize("phone", number[:40], await L.tenant_country(db, actor.user.tenant_id))
    except Invalid:
        return None
    lead = await db.scalar(
        select(Lead)
        .join(LeadIdentity, LeadIdentity.lead_id == Lead.id)
        .where(LeadIdentity.type == "phone", LeadIdentity.value_normalized == phone)
        .where(await L.visibility_filter(db, actor))
        .order_by(Lead.is_open.desc(), Lead.last_activity_at.desc().nulls_last())
        .limit(1)
    )
    if lead is None:
        return None
    stage = await db.get(LeadStage, lead.stage_id)
    owner = await db.get(User, lead.owner_user_id) if lead.owner_user_id else None
    return CallerOut(
        lead_id=lead.id, name=lead.display_name, stage=stage.name if stage else None,
        owner_name=owner.name if owner else None, is_yours=lead.owner_user_id == actor.user.id,
    )  # fmt: skip


@router.get("/devices", response_model=list[DeviceOut])
async def my_devices(db: CrmDb, actor: Rep) -> list[DeviceOut]:
    rows = (await db.scalars(select(PhoneDevice).where(
        PhoneDevice.user_id == actor.user.id, PhoneDevice.revoked_at.is_(None))
        .order_by(PhoneDevice.created_at.desc()))).all()  # fmt: skip
    return await _out(db, rows)


@router.get("/all-devices", response_model=list[DeviceOut])
async def all_devices(db: CrmDb, actor: Admin) -> list[DeviceOut]:
    rows = (await db.scalars(select(PhoneDevice).where(PhoneDevice.revoked_at.is_(None))
        .order_by(PhoneDevice.last_used_at.desc().nulls_last()))).all()  # fmt: skip
    return await _out(db, rows)


@router.post("/devices/{device_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove(device_id: uuid.UUID, db: CrmDb, actor: Rep) -> None:
    """The rep removes their own phone; an admin (settings.manage) anyone's."""
    row = await db.get(PhoneDevice, device_id)
    admin = has_permission(actor.permissions, "settings.manage")
    if row is None or (row.user_id != actor.user.id and not admin):
        raise NotFound("Not found")
    if row.revoked_at is None:
        row.revoked_at = now()
        await db.flush()
        await audit(db, actor, "phone.removed", "phone_device", row.id)

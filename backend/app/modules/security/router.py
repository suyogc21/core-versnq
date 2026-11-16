"""Security endpoints (finishing plan, batch 1).

- My account: my signed-in devices (sign one out), my sign-in history.
- Settings → Security (admins): idle sign-out, IP allowlist, failed sign-in alerts; everyone's
  sign-ins; sign out one person or the whole company.
- Data protection: export everything (a zip built by the worker, kept 7 days); erase a person.
"""

import ipaddress
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import ratelimit
from app.core.client_ip import client_ip
from app.core.errors import Invalid, NotFound
from app.core.events import emit
from app.core.security import hash_token
from app.modules.auth.deps import ActiveUser, CurrentUser, TenantDb, require
from app.modules.auth.models import UserSession
from app.modules.auth.service import revoke_all_sessions
from app.modules.crm import leads as L
from app.modules.crm.deps import audit
from app.modules.security import service as S
from app.modules.security.models import DataExport, SignIn
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["security"])
Admin = Annotated[CurrentUser, require("settings.manage")]
UserAdmin = Annotated[CurrentUser, require("users.manage")]
Auditor = Annotated[CurrentUser, require("audit.read")]


def now() -> datetime:
    return datetime.now(UTC)


# ---------- shapes ----------
class SecuritySettings(BaseModel):
    idle_minutes: int = Field(default=0, description="0 = off; otherwise 30 to 1440")
    ip_allowlist: list[str] = Field(default=[], max_length=50)
    alert_failed_sign_ins: bool = True


class SecuritySettingsOut(SecuritySettings):
    your_ip: str


class SignInOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_name: str | None = None
    email: str
    success: bool
    method: str
    reason: str | None
    ip: str | None
    user_agent: str | None
    created_at: datetime


class SignedInDevice(BaseModel):
    id: uuid.UUID
    ip: str | None
    user_agent: str | None
    last_active_at: datetime
    this_device: bool


class ExportOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    status: str
    size_bytes: int | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None


class EraseIn(BaseModel):
    confirm: Literal["ERASE"]


# ---------- my account ----------
@router.get("/me/devices", response_model=list[SignedInDevice])
async def my_devices(
    db: TenantDb, current: ActiveUser, user_refresh: Annotated[str | None, Cookie()] = None
) -> list[SignedInDevice]:
    mine = hash_token(user_refresh) if user_refresh else None
    rows = (
        await db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == current.user.id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now(),
            )
            .order_by(UserSession.created_at.desc())
        )
    ).all()
    return [
        SignedInDevice(
            id=r.id,
            ip=r.ip,
            user_agent=r.user_agent,
            last_active_at=r.created_at,
            this_device=r.refresh_token_hash == mine,
        )  # fmt: skip
        for r in rows
    ]


@router.post("/me/devices/{session_id}/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_device(session_id: uuid.UUID, db: TenantDb, current: ActiveUser) -> None:
    """That device can't renew its sign-in; it is signed out within 15 minutes at most."""
    row = await db.get(UserSession, session_id)
    if row is None or row.user_id != current.user.id:
        raise NotFound("Not found")
    row.revoked_at = row.revoked_at or now()


@router.get("/me/sign-ins", response_model=list[SignInOut])
async def my_sign_ins(db: TenantDb, current: ActiveUser) -> list[SignInOut]:
    rows = (
        await db.scalars(
            select(SignIn)
            .where(SignIn.user_id == current.user.id)
            .order_by(SignIn.created_at.desc())
            .limit(50)
        )
    ).all()
    return [SignInOut.model_validate(r) for r in rows]


# ---------- Settings → Security ----------
@router.get("/security/settings", response_model=SecuritySettingsOut)
async def get_settings_(request: Request, db: TenantDb, actor: Admin) -> SecuritySettingsOut:
    current = await S.settings_of(db, actor.user.tenant_id)
    return SecuritySettingsOut(**current, your_ip=client_ip(request))


@router.put("/security/settings", response_model=SecuritySettingsOut)
async def put_settings(
    body: SecuritySettings, request: Request, db: TenantDb, actor: Admin
) -> SecuritySettingsOut:
    if body.idle_minutes and not 30 <= body.idle_minutes <= 1440:
        raise Invalid("Idle sign-out is off (0) or between 30 and 1440 minutes")
    clean = []
    for item in body.ip_allowlist:
        try:
            clean.append(str(ipaddress.ip_network(item.strip(), strict=False)))
        except ValueError:
            raise Invalid(f"“{item}” isn't an IP address or range (like 203.0.113.0/24)") from None
    new = {**body.model_dump(), "ip_allowlist": list(dict.fromkeys(clean))}
    you = client_ip(request)
    if not S.ip_allowed(new, you):
        raise Invalid(
            f"Your own address ({you}) isn't in the list: saving it would lock you out",
            code="would_lock_you_out",
        )
    row = await db.get(TenantSettings, actor.user.tenant_id)
    before = {**S.DEFAULTS, **(row.security or {})}
    row.security = new
    await db.flush()
    await audit(db, actor, "security.settings_changed", "tenant", actor.user.tenant_id,
                before=before, after=new)  # fmt: skip
    return SecuritySettingsOut(**new, your_ip=you)


@router.get("/security/sign-ins", response_model=list[SignInOut])
async def all_sign_ins(
    db: TenantDb,
    actor: Auditor,
    user_id: uuid.UUID | None = None,
    failed: bool = False,
    before: datetime | None = None,
    limit: int = 100,
) -> list[SignInOut]:
    q = select(SignIn).order_by(SignIn.created_at.desc()).limit(min(max(limit, 1), 500))
    if user_id:
        q = q.where(SignIn.user_id == user_id)
    if failed:
        q = q.where(SignIn.success.is_(False))
    if before:
        q = q.where(SignIn.created_at < before)
    rows = (await db.scalars(q)).all()
    ids = {r.user_id for r in rows if r.user_id}
    names = dict((await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()) \
        if ids else {}  # fmt: skip
    out = []
    for r in rows:
        item = SignInOut.model_validate(r)
        item.user_name = names.get(r.user_id)
        out.append(item)
    return out


@router.post("/security/users/{user_id}/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_user(user_id: uuid.UUID, db: TenantDb, actor: UserAdmin) -> None:
    """Sign one person out everywhere, at once."""
    if await db.get(User, user_id) is None:
        raise NotFound("Not found")
    await revoke_all_sessions(db, user_id)
    await audit(db, actor, "security.user_signed_out", "user", user_id)


@router.post("/security/sign-out-everyone", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_everyone(db: TenantDb, actor: Admin) -> None:
    """Everyone in the company, including you, is signed out at once (a suspected breach)."""
    ids = (await db.scalars(select(User.id))).all()
    for uid in ids:
        await revoke_all_sessions(db, uid)
    await audit(db, actor, "security.everyone_signed_out", "tenant", actor.user.tenant_id,
                after={"people": len(ids)})  # fmt: skip


# ---------- data protection ----------
@router.post("/data-exports", response_model=ExportOut, status_code=status.HTTP_201_CREATED)
async def start_export(db: TenantDb, actor: Admin) -> ExportOut:
    await ratelimit.enforce(f"rl:export:{actor.user.tenant_id}", 3, 86400)
    busy = await db.scalar(
        select(DataExport.id).where(DataExport.status.in_(["queued", "running"])).limit(1)
    )
    if busy:
        raise Invalid("An export is already being made", code="export_running")
    row = DataExport(id=uuid.uuid4(), tenant_id=actor.user.tenant_id,
                     requested_by_user_id=actor.user.id, status="queued")  # fmt: skip
    db.add(row)
    await db.flush()
    await audit(db, actor, "data.export_requested", "data_export", row.id)
    from app.workers.queue import enqueue

    await enqueue("data_export_job", str(row.tenant_id), str(row.id), defer_by=1)
    await db.refresh(row)
    return ExportOut.model_validate(row)


@router.get("/data-exports", response_model=list[ExportOut])
async def list_exports(db: TenantDb, actor: Admin) -> list[ExportOut]:
    rows = await db.scalars(select(DataExport).order_by(DataExport.created_at.desc()).limit(20))
    return [ExportOut.model_validate(r) for r in rows.all()]


@router.get("/data-exports/{export_id}/download")
async def download_export(export_id: uuid.UUID, db: TenantDb, actor: Admin) -> FileResponse:
    row = await db.get(DataExport, export_id)
    if row is None or row.status != "ready" or not row.path:
        raise NotFound("This export isn't ready or has expired")
    await audit(db, actor, "data.export_downloaded", "data_export", row.id)
    return FileResponse(
        S.export_file(row.path), media_type="application/zip",
        filename=f"versnq-core-export-{row.created_at:%Y-%m-%d}.zip",
        headers={"Cache-Control": "private, no-store"},
    )  # fmt: skip


@router.post("/leads/{lead_id}/erase", status_code=status.HTTP_204_NO_CONTENT)
async def erase(lead_id: uuid.UUID, body: EraseIn, db: TenantDb, actor: Admin) -> None:
    """Erase a person on their request (DPDP / GDPR). This can't be undone."""
    lead = await L.get_visible(db, actor, lead_id)
    if lead.erased_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already erased")
    await S.erase_lead(db, lead)
    await audit(db, actor, "lead.erased", "lead", lead.id)
    # So every connected system (ACE, webhooks) deletes its own copy too.
    await emit(db, lead.tenant_id, "lead.erased", {"lead_id": str(lead.id)})


@router.get("/leads/{lead_id}/personal-data")
async def personal_data(lead_id: uuid.UUID, db: TenantDb, actor: Admin) -> dict:
    """Everything Core keeps about one person, for their access request (GDPR Art. 15 / 20,
    DPDP right to information): details, contact points, consents, timeline, messages, calls
    (not the audio), deals and invoices."""
    lead = await L.get_visible(db, actor, lead_id)
    out = await S.person_data(db, lead)
    await audit(db, actor, "lead.personal_data_exported", "lead", lead.id)
    return out

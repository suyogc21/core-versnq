import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip
from app.core.deps import get_platform_db
from app.core.mailer import Email, Mailer, get_mailer
from app.core.modules import module_states, set_module
from app.core.tenancy import set_tenant_context
from app.platform import audit
from app.platform.models import Tenant
from app.platform.packs import available_packs, load_pack
from app.platform.staff.models import PlatformStaff
from app.platform.staff.router import current_staff
from app.platform.tenants import service
from app.platform.tenants.schemas import (
    AuditOut,
    InviteResult,
    TenantCreate,
    TenantCreated,
    TenantOut,
    TenantUpdate,
)

log = logging.getLogger("versnq.platform")
router = APIRouter(
    prefix="/platform", tags=["platform-tenants"], dependencies=[Depends(current_staff)]
)

Db = Annotated[AsyncSession, Depends(get_platform_db)]
Staff = Annotated[PlatformStaff, Depends(current_staff)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]


def _ip(request: Request) -> str:
    return client_ip(request)


async def _tenant_or_404(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await service.get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return tenant


async def _try_send(mailer: Mailer, email: Email) -> bool:
    """Email goes out only after the data is committed; a failure is reported, not fatal."""
    try:
        await mailer.send(email)
        return True
    except Exception:
        log.exception("Invite email to %s failed", email.to)
        return False


@router.post("/tenants", status_code=status.HTTP_201_CREATED, response_model=TenantCreated)
async def create_tenant(
    body: TenantCreate, request: Request, db: Db, staff: Staff, mailer: MailerDep
) -> TenantCreated:
    try:
        tenant, plain = await service.provision_tenant(db, body, staff.id, _ip(request))
    except IntegrityError as exc:
        if "tenants_slug_key" in str(exc.orig):
            raise HTTPException(status.HTTP_409_CONFLICT, "This workspace name is taken") from None
        raise
    await db.commit()
    email = service.invite_email(tenant, body.owner_name, str(body.owner_email), plain)
    sent = await _try_send(mailer, email)
    return TenantCreated(**TenantOut.model_validate(tenant).model_dump(), invite_sent=sent)


class PackOut(BaseModel):
    key: str
    name: str


@router.get("/packs", response_model=list[PackOut])
async def list_packs() -> list[PackOut]:
    """Industry packs a new company can start from."""
    return [PackOut(key=k, name=load_pack(k).name) for k in available_packs()]


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(
    db: Db,
    q: str | None = None,
    status_filter: Annotated[
        str | None, Query(alias="status", pattern="^(active|suspended)$")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Tenant]:
    return await service.list_tenants(db, q, status_filter, limit, offset)


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
async def get_tenant(tenant_id: uuid.UUID, db: Db) -> Tenant:
    return await _tenant_or_404(db, tenant_id)


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: uuid.UUID, body: TenantUpdate, request: Request, db: Db, staff: Staff
) -> Tenant:
    tenant = await _tenant_or_404(db, tenant_id)
    return await service.update_tenant(db, tenant, body.name, staff.id, _ip(request))


@router.post("/tenants/{tenant_id}/suspend", response_model=TenantOut)
async def suspend_tenant(tenant_id: uuid.UUID, request: Request, db: Db, staff: Staff) -> Tenant:
    tenant = await _tenant_or_404(db, tenant_id)
    return await service.set_status(db, tenant, "suspended", staff.id, _ip(request))


@router.post("/tenants/{tenant_id}/reactivate", response_model=TenantOut)
async def reactivate_tenant(tenant_id: uuid.UUID, request: Request, db: Db, staff: Staff) -> Tenant:
    tenant = await _tenant_or_404(db, tenant_id)
    return await service.set_status(db, tenant, "active", staff.id, _ip(request))


@router.post("/tenants/{tenant_id}/resend-owner-invite", response_model=InviteResult)
async def resend_owner_invite(
    tenant_id: uuid.UUID, request: Request, db: Db, staff: Staff, mailer: MailerDep
) -> InviteResult:
    tenant = await _tenant_or_404(db, tenant_id)
    try:
        owner, plain = await service.renew_owner_invite(db, tenant, staff.id, _ip(request))
    except service.OwnerAlreadyActive:
        raise HTTPException(status.HTTP_409_CONFLICT, "The owner has already accepted") from None
    await db.commit()
    sent = await _try_send(mailer, service.invite_email(tenant, owner.name, owner.email, plain))
    return InviteResult(invite_sent=sent)


class OwnerResetIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


@router.post("/tenants/{tenant_id}/owner-2fa-reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_owner_two_factor(
    tenant_id: uuid.UUID, body: OwnerResetIn, request: Request, db: Db, staff: Staff,
    mailer: MailerDep,
) -> None:  # fmt: skip
    """Lost phone: remove a company Owner's authenticator app (go-live G-4). Audited."""
    tenant = await _tenant_or_404(db, tenant_id)
    try:
        owner = await service.reset_owner_two_factor(db, tenant, body.email, staff.id, _ip(request))
    except service.NotAnOwnerWithApp:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No Owner with that email uses an authenticator app"
        ) from None
    await db.commit()
    await _try_send(
        mailer,
        Email(
            to=owner.email,
            subject=f"Your authenticator app was reset for {tenant.name}",
            body=f"Hi {owner.name},\n\nVersnq support removed the authenticator app from your "
            "account, as you asked. Sign in with your password and the code we email you; you "
            "can set the app up again in My account.\n\nIf you didn't ask for this, reply to "
            "this email.\n",
        ),
    )


@router.get("/audit", response_model=list[AuditOut])
async def list_audit(
    db: Db,
    target_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list:
    return await audit.list_entries(db, target_id, limit)


@router.get("/tenants/{tenant_id}/modules", response_model=dict[str, bool])
async def get_modules(tenant_id: uuid.UUID, db: Db) -> dict[str, bool]:
    tenant = await _tenant_or_404(db, tenant_id)
    await set_tenant_context(db, tenant.id)
    return await module_states(db, tenant.id)


@router.put("/tenants/{tenant_id}/modules", response_model=dict[str, bool])
async def put_modules(
    tenant_id: uuid.UUID, body: dict[str, bool], request: Request, db: Db, staff: Staff
) -> dict[str, bool]:
    """Switch modules on or off for one tenant. Keys not sent are left unchanged."""
    tenant = await _tenant_or_404(db, tenant_id)
    await set_tenant_context(db, tenant.id)
    before = await module_states(db, tenant.id)
    for key, enabled in body.items():
        await set_module(db, tenant.id, key, enabled)
    after = await module_states(db, tenant.id)
    await audit.record(
        db,
        staff_id=staff.id,
        action="tenant.modules_changed",
        target_type="tenant",
        target_id=tenant.id,
        tenant_slug=tenant.slug,
        before=before,
        after=after,
        ip=_ip(request),
    )
    return after

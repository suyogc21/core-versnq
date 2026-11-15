"""One-step tenant provisioning and tenant management by Versnq staff."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mailer import Email
from app.core.money import for_country
from app.core.tenancy import set_tenant_context
from app.modules.auth.service import INVITE_TTL, issue_link_token
from app.modules.crm.setup import seed_crm
from app.modules.roles.models import Role, RolePermission
from app.modules.roles.permissions import DEFAULT_GRANTS
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User
from app.platform import audit
from app.platform.models import Tenant
from app.platform.packs import load_pack
from app.platform.tenants.schemas import TenantCreate

INVITE_HOURS = int(INVITE_TTL.total_seconds() // 3600)

# key, name, scope — seeded for every tenant, with DEFAULT_GRANTS (Owner holds every code).
SYSTEM_ROLES = (
    ("owner", "Owner", "all"),
    ("admin", "Admin", "all"),
    ("sales_manager", "Sales Manager", "team"),
    ("sales_user", "Sales User", "own"),
    ("finance", "Finance", "own"),
)


class OwnerAlreadyActive(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _snapshot(t: Tenant) -> dict:
    return {"name": t.name, "slug": t.slug, "status": t.status, "industry_pack": t.industry_pack}


async def _seed_roles(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    roles = {
        key: Role(tenant_id=tenant_id, key=key, name=name, scope=scope, is_system=True)
        for key, name, scope in SYSTEM_ROLES
    }
    db.add_all(roles.values())
    await db.flush()
    db.add_all(
        RolePermission(tenant_id=tenant_id, role_id=roles[key].id, permission_code=code)
        for key, codes in DEFAULT_GRANTS.items()
        for code in sorted(codes)
    )
    return {key: role.id for key, role in roles.items()}


async def _new_invite(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return await issue_link_token(db, tenant_id, user_id, "invite", INVITE_TTL)


def invite_email(tenant: Tenant, owner_name: str, owner_email: str, plain_token: str) -> Email:
    link = f"https://{tenant.slug}.{get_settings().base_domain}/invite?token={plain_token}"
    return Email(
        to=owner_email,
        subject=f"You're invited to {tenant.name} on Versnq Core",
        body=(
            f"Hi {owner_name},\n\n"
            f"You have been invited to {tenant.name} on Versnq Core.\n"
            f"Set your password here (valid for {INVITE_HOURS} hours):\n"
            f"{link}\n"
        ),
    )


async def provision_tenant(
    db: AsyncSession, data: TenantCreate, staff_id: uuid.UUID, ip: str | None
) -> tuple[Tenant, str]:
    """Create tenant + settings + roles + invited Owner + invite token in the caller's
    transaction. Returns the tenant and the plain invite token (to email after commit)."""
    pack = load_pack(data.industry_pack)
    tenant = Tenant(
        name=data.name,
        slug=data.slug,
        status="active",
        industry_pack=data.industry_pack,
        created_by_staff_id=staff_id,
    )
    db.add(tenant)
    await db.flush()  # duplicate slug fails here

    await set_tenant_context(db, tenant.id)
    db.add(
        TenantSettings(
            tenant_id=tenant.id,
            labels=pack.model_dump()["labels"],
            timezone=data.timezone,
            default_country=data.default_country,
            default_currency=for_country(data.default_country),
            branding={},
        )
    )
    role_ids = await _seed_roles(db, tenant.id)
    await seed_crm(db, tenant.id, pack)
    owner = User(
        tenant_id=tenant.id,
        email=str(data.owner_email),
        name=data.owner_name,
        status="invited",
        role_id=role_ids["owner"],
    )
    db.add(owner)
    await db.flush()
    plain = await _new_invite(db, tenant.id, owner.id)

    await audit.record(
        db,
        staff_id=staff_id,
        action="tenant.created",
        target_type="tenant",
        target_id=tenant.id,
        tenant_slug=tenant.slug,
        after=_snapshot(tenant) | {"owner_email": owner.email},
        ip=ip,
    )
    return tenant, plain


async def get_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    return await db.get(Tenant, tenant_id)


async def list_tenants(
    db: AsyncSession, q: str | None, status: str | None, limit: int, offset: int
) -> list[Tenant]:
    query = select(Tenant).order_by(Tenant.created_at.desc()).limit(limit).offset(offset)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Tenant.name.ilike(like), Tenant.slug.ilike(like)))
    if status:
        query = query.where(Tenant.status == status)
    return list((await db.scalars(query)).all())


async def update_tenant(
    db: AsyncSession, tenant: Tenant, name: str, staff_id: uuid.UUID, ip: str | None
) -> Tenant:
    before = _snapshot(tenant)
    tenant.name = name
    await audit.record(
        db,
        staff_id=staff_id,
        action="tenant.updated",
        target_type="tenant",
        target_id=tenant.id,
        tenant_slug=tenant.slug,
        before=before,
        after=_snapshot(tenant),
        ip=ip,
    )
    return tenant


async def set_status(
    db: AsyncSession, tenant: Tenant, status: str, staff_id: uuid.UUID, ip: str | None
) -> Tenant:
    before = _snapshot(tenant)
    tenant.status = status
    action = "tenant.suspended" if status == "suspended" else "tenant.reactivated"
    await audit.record(
        db,
        staff_id=staff_id,
        action=action,
        target_type="tenant",
        target_id=tenant.id,
        tenant_slug=tenant.slug,
        before=before,
        after=_snapshot(tenant),
        ip=ip,
    )
    return tenant


async def renew_owner_invite(
    db: AsyncSession, tenant: Tenant, staff_id: uuid.UUID, ip: str | None
) -> tuple[User, str]:
    """Invalidate the Owner's open invite links and issue a new one."""
    await set_tenant_context(db, tenant.id)
    owner = await db.scalar(
        select(User)
        .join(Role, (Role.id == User.role_id) & (Role.tenant_id == User.tenant_id))
        .where(Role.key == "owner", User.status == "invited")
        .order_by(User.created_at)
        .limit(1)
    )
    if owner is None:
        raise OwnerAlreadyActive
    plain = await _new_invite(db, tenant.id, owner.id)  # older invite links stop working
    await audit.record(
        db,
        staff_id=staff_id,
        action="tenant.owner_invite_resent",
        target_type="tenant",
        target_id=tenant.id,
        tenant_slug=tenant.slug,
        after={"owner_email": owner.email},
        ip=ip,
    )
    return owner, plain


class NotAnOwnerWithApp(Exception):
    """No Owner with that email uses an authenticator app in this company."""


async def reset_owner_two_factor(
    db: AsyncSession, tenant: Tenant, email: str, staff_id: uuid.UUID, ip: str | None
) -> User:
    """Lost phone (go-live G-4): Versnq staff remove a company Owner's authenticator app and
    backup codes and sign them out everywhere. Audited in the staff audit log."""
    from sqlalchemy import func

    from app.modules.auth.service import clear_recovery_codes, revoke_all_sessions

    await set_tenant_context(db, tenant.id)
    owner = await db.scalar(
        select(User)
        .join(Role, (Role.id == User.role_id) & (Role.tenant_id == User.tenant_id))
        .where(Role.key == "owner", func.lower(User.email) == email.strip().lower())
    )
    if owner is None or not owner.totp_enabled:
        raise NotAnOwnerWithApp
    owner.totp_enabled, owner.totp_secret_enc = False, None
    await clear_recovery_codes(db, owner.id)
    await revoke_all_sessions(db, owner.id)
    await audit.record(
        db,
        staff_id=staff_id,
        action="tenant.owner_2fa_reset",
        target_type="tenant",
        target_id=tenant.id,
        tenant_slug=tenant.slug,
        after={"owner_email": owner.email},
        ip=ip,
    )
    return owner

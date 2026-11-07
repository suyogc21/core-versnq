"""Test data builders. All writes go through the runtime role, like the app."""

import uuid
from uuid import UUID

from app.core.security import create_access_token, hash_password
from app.core.tenancy import platform_session, tenant_session
from app.core.twofactor import encrypt_secret, new_secret
from app.modules.roles.models import Role
from app.platform.models import Tenant
from app.platform.staff.models import PlatformStaff


async def make_tenant(slug: str | None = None, name: str = "Test Co") -> UUID:
    tenant = Tenant(
        name=name,
        slug=slug or f"t{uuid.uuid4().hex[:12]}",
        status="active",
        industry_pack="generic",
    )
    async with platform_session() as s:
        s.add(tenant)
    return tenant.id


async def make_role(tenant_id: UUID, name: str, scope: str = "all") -> UUID:
    role = Role(tenant_id=tenant_id, name=name, scope=scope, is_system=False)
    async with tenant_session(tenant_id) as s:
        s.add(role)
    return role.id


async def make_staff(
    password: str = "s3cret-pass-123", is_active: bool = True, totp_secret: str | None = None
) -> str:
    email = f"staff-{uuid.uuid4().hex[:10]}@versnq.in"
    async with platform_session() as s:
        s.add(
            PlatformStaff(
                email=email,
                name="Staff",
                password_hash=hash_password(password),
                is_active=is_active,
                totp_secret_enc=encrypt_secret(totp_secret) if totp_secret else None,
                totp_enabled=totp_secret is not None,
            )
        )
    return email


async def staff_headers(two_factor: bool = True) -> dict[str, str]:
    """A staff account plus a valid bearer header for it."""
    staff = PlatformStaff(
        email=f"staff-{uuid.uuid4().hex[:10]}@versnq.in",
        name="Staff",
        password_hash=hash_password("s3cret-pass-123"),
        totp_secret_enc=encrypt_secret(new_secret()),
        totp_enabled=two_factor,
    )
    async with platform_session() as s:
        s.add(staff)
    return {"Authorization": f"Bearer {create_access_token(staff.id, 'staff', None)}"}


PASSWORD = "pass-word-123"


async def make_workspace(slug: str | None = None, status: str = "active") -> tuple[UUID, str]:
    """A tenant with its five system roles. Returns (tenant_id, slug)."""
    from app.modules.crm.setup import seed_crm
    from app.modules.settings.models import TenantSettings
    from app.platform.packs import load_pack
    from app.platform.tenants.service import _seed_roles

    slug = slug or f"w{uuid.uuid4().hex[:10]}"
    tenant = Tenant(name=f"Co {slug}", slug=slug, status=status, industry_pack="generic")
    async with platform_session() as s:
        s.add(tenant)
    async with tenant_session(tenant.id) as s:
        s.add(
            TenantSettings(
                tenant_id=tenant.id,
                labels=load_pack("generic").model_dump()["labels"],
                timezone="Asia/Kolkata",
                default_country="IN",
                branding={},
            )
        )
        await _seed_roles(s, tenant.id)
        await seed_crm(s, tenant.id, load_pack("generic"))
    return tenant.id, slug


async def make_user(
    tenant_id: UUID,
    *,
    role_key: str = "sales_user",
    email: str | None = None,
    password: str | None = PASSWORD,
    status: str = "active",
    must_change_password: bool = False,
    totp_secret: str | None = None,
) -> tuple[UUID, str]:
    """Returns (user_id, email)."""
    from sqlalchemy import select

    from app.modules.users.models import User

    email = email or f"u-{uuid.uuid4().hex[:10]}@client.com"
    async with tenant_session(tenant_id) as s:
        role_id = await s.scalar(select(Role.id).where(Role.key == role_key))
        user = User(
            tenant_id=tenant_id,
            email=email,
            name="Test User",
            password_hash=hash_password(password) if password else None,
            status=status,
            role_id=role_id,
            must_change_password=must_change_password,
            totp_secret_enc=encrypt_secret(totp_secret) if totp_secret else None,
            totp_enabled=totp_secret is not None,
        )
        s.add(user)
    return user.id, email


async def login_as(
    tenant_id: UUID, role_key: str | None = "sales_user", *, role_id: UUID | None = None
) -> tuple[UUID, dict[str, str]]:
    """Create an active user with a role and return (user_id, bearer headers).
    Owner/Admin get 2FA enabled so they are not restricted."""
    from sqlalchemy import select

    from app.modules.users.models import User

    async with tenant_session(tenant_id) as s:
        if role_id is None:
            role_id = await s.scalar(select(Role.id).where(Role.key == role_key))
        user = User(
            tenant_id=tenant_id,
            email=f"u-{uuid.uuid4().hex[:10]}@client.com",
            name="Member",
            password_hash=hash_password(PASSWORD),
            status="active",
            role_id=role_id,
            totp_secret_enc=encrypt_secret(new_secret()),
            totp_enabled=role_key in ("owner", "admin"),
        )
        s.add(user)
    return user.id, {"Authorization": f"Bearer {create_access_token(user.id, 'user', tenant_id)}"}


async def make_custom_role(
    tenant_id: UUID, name: str, scope: str = "all", permissions: tuple[str, ...] = ()
) -> UUID:
    from app.modules.roles.models import RolePermission

    role = Role(tenant_id=tenant_id, name=name, scope=scope, is_system=False)
    async with tenant_session(tenant_id) as s:
        s.add(role)
        await s.flush()
        s.add_all(
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_code=c)
            for c in permissions
        )
    return role.id

"""Test data builders. All writes go through the runtime role, like the app."""

import uuid
from uuid import UUID

from app.core.security import create_access_token, hash_password
from app.core.tenancy import platform_session, tenant_session
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


async def make_staff(password: str = "s3cret-pass-123", is_active: bool = True) -> str:
    email = f"staff-{uuid.uuid4().hex[:10]}@versnq.in"
    async with platform_session() as s:
        s.add(
            PlatformStaff(
                email=email,
                name="Staff",
                password_hash=hash_password(password),
                is_active=is_active,
            )
        )
    return email


async def staff_headers() -> dict[str, str]:
    """A staff account plus a valid bearer header for it."""
    staff = PlatformStaff(
        email=f"staff-{uuid.uuid4().hex[:10]}@versnq.in",
        name="Staff",
        password_hash=hash_password("s3cret-pass-123"),
    )
    async with platform_session() as s:
        s.add(staff)
    return {"Authorization": f"Bearer {create_access_token(staff.id, 'staff', None)}"}

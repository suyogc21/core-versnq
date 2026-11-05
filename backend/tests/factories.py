"""Test data builders. All writes go through the runtime role, like the app."""

import uuid
from uuid import UUID

from app.core.tenancy import platform_session, tenant_session
from app.modules.roles.models import Role
from app.platform.models import Tenant


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

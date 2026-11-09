from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.auth.deps import effective_permissions
from app.modules.roles.models import Role
from app.modules.roles.permissions import ALL_CODES, DEFAULT_GRANTS
from tests.factories import login_as


async def _perms(tenant_id, key):
    async with tenant_session(tenant_id) as s:
        role = await s.scalar(select(Role).where(Role.key == key))
        return await effective_permissions(s, role)


async def test_owner_has_every_permission(ws):
    tenant_id, _ = ws
    assert await _perms(tenant_id, "owner") == set(ALL_CODES)


async def test_default_grants_seeded(ws):
    tenant_id, _ = ws
    for key in ("admin", "sales_manager", "sales_user", "finance"):
        assert await _perms(tenant_id, key) == DEFAULT_GRANTS[key]


async def test_sales_user_cannot_list_users(ws):
    tenant_id, c = ws
    _, headers = await login_as(tenant_id, "sales_user")
    assert (await c.get("/api/v1/users", headers=headers)).status_code == 403


async def test_unknown_permission_is_denied():
    from app.modules.auth.deps import has_permission

    assert has_permission({"users.read"}, "users.read")
    assert not has_permission({"users.read"}, "users.delete_everything")


async def test_me_lists_the_users_permissions(ws):
    tenant_id, c = ws
    _, mgr = await login_as(tenant_id, "sales_manager")
    _, owner = await login_as(tenant_id, "owner")
    assert (await c.get("/api/v1/auth/me", headers=mgr)).json()["permissions"] == [
        "deals.create",
        "deals.edit",
        "leads.assign",
        "leads.create",
        "leads.edit",
        "leads.import",
        "leads.merge",
        "users.read",
    ]
    assert set((await c.get("/api/v1/auth/me", headers=owner)).json()["permissions"]) == set(
        ALL_CODES
    )

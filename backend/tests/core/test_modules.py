from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import errors
from app.core.modules import require_module
from tests.factories import login_as, make_workspace, staff_headers


async def _modules(c, headers):
    return {
        m["key"]: m["enabled"] for m in (await c.get("/api/v1/modules", headers=headers)).json()
    }


async def test_defaults_money_and_ace_off(client_for):
    tenant_id, slug = await make_workspace()
    _, rep = await login_as(tenant_id, "sales_user")
    mods = await _modules(client_for(slug), rep)
    assert mods["crm"] and mods["email"] and mods["whatsapp"]
    assert not mods["money"] and not mods["ace"]


async def test_staff_toggles_module_and_it_is_audited(client_for):
    tenant_id, slug = await make_workspace()
    staff = await staff_headers()
    _, rep = await login_as(tenant_id, "sales_user")
    async with AsyncClient(
        transport=ASGITransport(app=__import__("app.main").main.app), base_url="http://test"
    ) as pc:
        r = await pc.put(
            f"/platform/tenants/{tenant_id}/modules", json={"whatsapp": False}, headers=staff
        )
        audit = await pc.get("/platform/audit", params={"target_id": str(tenant_id)}, headers=staff)
    assert r.status_code == 200
    assert (await _modules(client_for(slug), rep))["whatsapp"] is False
    assert "tenant.modules_changed" in [a["action"] for a in audit.json()]


async def test_crm_cannot_be_switched_off(client_for):
    tenant_id, _ = await make_workspace()
    staff = await staff_headers()
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as pc:
        r = await pc.put(
            f"/platform/tenants/{tenant_id}/modules", json={"crm": False}, headers=staff
        )
        unknown = await pc.put(
            f"/platform/tenants/{tenant_id}/modules", json={"teleport": True}, headers=staff
        )
    assert r.status_code == 422 and unknown.status_code == 422


async def test_route_behind_switched_off_module_is_404(settings):
    tenant_id, slug = await make_workspace()
    probe = FastAPI()
    errors.install(probe)

    @probe.get("/api/v1/probe", dependencies=[require_module("money")])
    async def money_probe() -> dict:
        return {"ok": True}

    @probe.get("/api/v1/probe-email", dependencies=[require_module("email")])
    async def email_probe() -> dict:
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=probe), base_url=f"http://{slug}.{settings.base_domain}"
    ) as c:
        off = await c.get("/api/v1/probe")
        on = await c.get("/api/v1/probe-email")
    assert off.status_code == 404 and on.status_code == 200

import uuid

import pytest
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.audit.models import AuditLog
from tests.factories import login_as, make_workspace


async def test_admin_edits_labels_timezone_and_branding(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")

    r = await c.patch(
        "/api/v1/settings",
        json={
            "labels": {"lead": {"singular": "Buyer", "plural": "Buyers"}},
            "timezone": "Asia/Dubai",
            "default_country": "AE",
            "branding": {"primary_color": "#0A7CFF", "logo_url": "https://cdn.acme.com/l.png"},
        },
        headers=admin,
    )
    got = (await c.get("/api/v1/settings", headers=admin)).json()

    assert r.status_code == 200
    assert got["labels"]["lead"] == {"singular": "Buyer", "plural": "Buyers"}
    assert got["labels"]["deal"]["singular"] == "Deal"  # untouched keys stay
    assert (got["timezone"], got["default_country"]) == ("Asia/Dubai", "AE")
    assert got["branding"]["primary_color"] == "#0A7CFF"


@pytest.mark.parametrize(
    "body",
    [
        {"labels": {"spaceship": {"singular": "S", "plural": "Ss"}}},
        {"timezone": "Mars/Base"},
        {"default_country": "UAE"},
        {"branding": {"primary_color": "blue"}},
        {"branding": {"logo_url": "http://insecure.com/l.png"}},
    ],
)
async def test_invalid_settings_422(ws, body):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    assert (await c.patch("/api/v1/settings", json=body, headers=admin)).status_code == 422


async def test_sales_user_cannot_edit_settings(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    r = await c.patch("/api/v1/settings", json={"timezone": "UTC"}, headers=rep)
    assert r.status_code == 403


async def test_labels_of_one_tenant_never_change_another(ws, client_for):
    tenant_id, c = ws
    other_id, other_slug = await make_workspace()
    _, admin = await login_as(tenant_id, "admin")
    _, other_admin = await login_as(other_id, "admin")

    await c.patch(
        "/api/v1/settings",
        json={"labels": {"lead": {"singular": "Patient", "plural": "Patients"}}},
        headers=admin,
    )
    other = (await client_for(other_slug).get("/api/v1/settings", headers=other_admin)).json()
    assert other["labels"]["lead"]["singular"] == "Lead"


async def test_settings_change_is_audited(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await c.patch("/api/v1/settings", json={"timezone": "UTC"}, headers=admin)
    async with tenant_session(tenant_id) as s:
        row = (await s.scalars(select(AuditLog).where(AuditLog.action == "settings.updated"))).one()
    assert row.before["timezone"] == "Asia/Kolkata" and row.after["timezone"] == "UTC"
    assert row.entity_id == uuid.UUID(str(tenant_id))

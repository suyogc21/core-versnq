from tests.factories import login_as, make_workspace


async def test_admin_reads_audit_newest_first(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await c.patch("/api/v1/settings", json={"timezone": "UTC"}, headers=admin)
    await c.patch("/api/v1/settings", json={"timezone": "Asia/Dubai"}, headers=admin)

    rows = (await c.get("/api/v1/audit", headers=admin)).json()

    assert [r["action"] for r in rows[:2]] == ["settings.updated", "settings.updated"]
    assert rows[0]["after"]["timezone"] == "Asia/Dubai"


async def test_finance_can_read_sales_user_cannot(ws):
    tenant_id, c = ws
    _, finance = await login_as(tenant_id, "finance")
    _, rep = await login_as(tenant_id, "sales_user")
    assert (await c.get("/api/v1/audit", headers=finance)).status_code == 200
    assert (await c.get("/api/v1/audit", headers=rep)).status_code == 403


async def test_audit_shows_only_own_workspace(ws, client_for):
    tenant_id, c = ws
    other, other_slug = await make_workspace()
    _, other_admin = await login_as(other, "admin")
    await client_for(other_slug).patch(
        "/api/v1/settings", json={"timezone": "UTC"}, headers=other_admin
    )
    _, admin = await login_as(tenant_id, "admin")
    assert (await c.get("/api/v1/audit", headers=admin)).json() == []

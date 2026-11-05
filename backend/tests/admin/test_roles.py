from tests.factories import login_as, make_custom_role


async def test_create_custom_role(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")

    r = await c.post(
        "/api/v1/roles",
        json={"name": "Counsellor", "scope": "own", "permissions": ["users.read"]},
        headers=admin,
    )
    listed = await c.get("/api/v1/roles", headers=admin)

    assert r.status_code == 201 and r.json()["permissions"] == ["users.read"]
    assert "Counsellor" in [x["name"] for x in listed.json()]


async def test_cannot_grant_permission_you_lack(ws):
    tenant_id, c = ws
    hr = await make_custom_role(tenant_id, "HR", permissions=("roles.manage", "users.read"))
    _, headers = await login_as(tenant_id, None, role_id=hr)

    r = await c.post(
        "/api/v1/roles",
        json={"name": "Auditor", "scope": "all", "permissions": ["audit.read"]},
        headers=headers,
    )
    assert r.status_code == 403


async def test_owner_role_is_read_only(ws):
    tenant_id, c = ws
    _, owner = await login_as(tenant_id, "owner")
    roles = (await c.get("/api/v1/roles", headers=owner)).json()
    owner_role = next(r for r in roles if r["key"] == "owner")

    edit = await c.patch(
        f"/api/v1/roles/{owner_role['id']}", json={"permissions": []}, headers=owner
    )
    delete = await c.delete(f"/api/v1/roles/{owner_role['id']}", headers=owner)
    assert edit.status_code == 403 and delete.status_code == 409


async def test_system_role_cannot_be_deleted_or_renamed(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    roles = (await c.get("/api/v1/roles", headers=admin)).json()
    sales = next(r for r in roles if r["key"] == "sales_user")

    rename = await c.patch(f"/api/v1/roles/{sales['id']}", json={"name": "X"}, headers=admin)
    delete = await c.delete(f"/api/v1/roles/{sales['id']}", headers=admin)
    assert rename.status_code == 409 and delete.status_code == 409


async def test_role_in_use_cannot_be_deleted_but_empty_one_can(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    used = await make_custom_role(tenant_id, "Used")
    await login_as(tenant_id, None, role_id=used)
    empty = await make_custom_role(tenant_id, "Empty")

    assert (await c.delete(f"/api/v1/roles/{used}", headers=admin)).status_code == 409
    assert (await c.delete(f"/api/v1/roles/{empty}", headers=admin)).status_code == 204


async def test_unknown_permission_code_422(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    r = await c.post(
        "/api/v1/roles",
        json={"name": "Bad", "scope": "all", "permissions": ["root.everything"]},
        headers=admin,
    )
    assert r.status_code == 422


async def test_permission_catalogue_listed(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    codes = [p["code"] for p in (await c.get("/api/v1/permissions", headers=admin)).json()]
    assert "users.manage" in codes and "audit.read" in codes

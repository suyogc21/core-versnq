from app.core.tenancy import tenant_session
from app.modules.teams.service import visible_user_ids
from tests.factories import login_as, make_workspace


async def _team(c, headers, name, parent=None):
    r = await c.post("/api/v1/teams", json={"name": name, "parent_id": parent}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _members(c, headers, team_id, members):
    r = await c.put(
        f"/api/v1/teams/{team_id}/members",
        json=[{"user_id": str(u), "is_manager": m} for u, m in members],
        headers=headers,
    )
    assert r.status_code == 200, r.text


async def test_manager_sees_own_and_sub_teams_only(ws):
    """North ─ North-A (rep_a)       South (rep_s)
    └─ manager of North"""
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    manager, mgr_headers = await login_as(tenant_id, "sales_manager")
    rep_n, _ = await login_as(tenant_id, "sales_user")
    rep_a, _ = await login_as(tenant_id, "sales_user")
    rep_s, _ = await login_as(tenant_id, "sales_user")
    boss, _ = await login_as(tenant_id, "sales_manager")

    top = await _team(c, admin, "Company")
    north = await _team(c, admin, "North", top)
    north_a = await _team(c, admin, "North-A", north)
    south = await _team(c, admin, "South", top)
    await _members(c, admin, top, [(boss, True)])
    await _members(c, admin, north, [(manager, True), (rep_n, False)])
    await _members(c, admin, north_a, [(rep_a, False)])
    await _members(c, admin, south, [(rep_s, False)])

    listed = await c.get("/api/v1/users", headers=mgr_headers)
    seen = {u["id"] for u in listed.json()}

    assert seen == {str(manager), str(rep_n), str(rep_a)}


async def test_visibility_scopes(ws):
    tenant_id, _ = ws
    me, _ = await login_as(tenant_id, "sales_user")
    async with tenant_session(tenant_id) as s:
        assert await visible_user_ids(s, me, "own") == {me}
        assert await visible_user_ids(s, me, "all") is None
        assert await visible_user_ids(s, me, "team") == {me}  # manages no team


async def test_team_cannot_move_under_its_own_subteam(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    parent = await _team(c, admin, "Parent")
    child = await _team(c, admin, "Child", parent)

    r1 = await c.patch(f"/api/v1/teams/{parent}", json={"parent_id": child}, headers=admin)
    r2 = await c.patch(f"/api/v1/teams/{parent}", json={"parent_id": parent}, headers=admin)
    assert r1.status_code == 422 and r2.status_code == 422


async def test_team_with_subteams_cannot_be_deleted(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    parent = await _team(c, admin, "P")
    child = await _team(c, admin, "C", parent)

    assert (await c.delete(f"/api/v1/teams/{parent}", headers=admin)).status_code == 409
    assert (await c.delete(f"/api/v1/teams/{child}", headers=admin)).status_code == 204


async def test_member_from_other_tenant_rejected(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    other_tenant, _ = await make_workspace()
    stranger, _ = await login_as(other_tenant, "sales_user")
    team = await _team(c, admin, "T")

    r = await c.put(
        f"/api/v1/teams/{team}/members",
        json=[{"user_id": str(stranger), "is_manager": False}],
        headers=admin,
    )
    assert r.status_code == 422


async def test_sales_user_cannot_manage_teams(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    r = await c.post("/api/v1/teams", json={"name": "Mine"}, headers=rep)
    assert r.status_code == 403

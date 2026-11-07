"""The users list a page at a time, with filters, sorting and visibility."""

from tests.crm.helpers import make_team
from tests.factories import login_as


async def test_paging_sorting_and_filters(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    for _ in range(5):
        await login_as(tenant_id, "sales_user")
    roles = {r["key"]: r["id"] for r in (await c.get("/api/v1/roles", headers=admin)).json()}

    first = await c.get("/api/v1/users/page?limit=4", headers=admin)
    second = await c.get("/api/v1/users/page?limit=4&offset=4", headers=admin)
    reps = await c.get(f"/api/v1/users/page?role_id={roles['sales_user']}", headers=admin)
    invited = await c.get("/api/v1/users/page?status=invited", headers=admin)
    by_login = await c.get("/api/v1/users/page?sort=last_login&dir=desc", headers=admin)

    ids = [u["id"] for u in first.json()["items"] + second.json()["items"]]
    assert first.json()["total"] == 6 and len(set(ids)) == 6
    assert reps.json()["total"] == 5 and invited.json()["total"] == 0
    assert by_login.status_code == 200
    row = first.json()["items"][0]
    assert {"role_name", "teams", "last_login_at"} <= set(row)


async def test_manager_sees_only_their_team_and_team_filter(ws):
    tenant_id, c = ws
    m_id, mgr = await login_as(tenant_id, "sales_manager")
    a_id, _ = await login_as(tenant_id, "sales_user")
    await login_as(tenant_id, "sales_user")  # outside the team
    team = await make_team(tenant_id, m_id, [a_id], name="North")
    _, admin = await login_as(tenant_id, "admin")

    seen = await c.get("/api/v1/users/page", headers=mgr)
    north = await c.get(f"/api/v1/users/page?team_id={team}", headers=admin)
    rep = await c.get("/api/v1/users/page", headers=(await login_as(tenant_id, "sales_user"))[1])

    assert {u["id"] for u in seen.json()["items"]} == {str(m_id), str(a_id)}
    assert north.json()["total"] == 2 and north.json()["items"][0]["teams"] == ["North"]
    assert rep.status_code == 403

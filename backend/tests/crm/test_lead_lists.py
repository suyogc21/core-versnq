"""List at scale: sorting, multi-value filters, paging, view counts and bulk actions."""

from datetime import UTC, datetime, timedelta

from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as


def soon(hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


async def _seed(c, h, n=6):
    stages, sources = await setup_ids(c, h)
    ids = []
    for i in range(n):
        r = await new_lead(
            c,
            h,
            sources["Website" if i % 2 else "Referral"],
            first_name=f"Lead{i:02d}",
            phone=f"98765 {43200 + i}",
        )
        ids.append(r.json()["id"])
    return stages, sources, ids


async def test_sort_paging_and_multi_value_filters(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    stages, sources, ids = await _seed(c, admin, 7)
    await c.patch(
        f"/api/v1/leads/{ids[0]}",
        json={"version": 1, "stage_id": stages["Qualified"]["id"]},
        headers=admin,
    )

    def names(r):
        return [x["display_name"] for x in r.json()["items"]]

    asc = await c.get("/api/v1/leads?sort=name&dir=asc&limit=3", headers=admin)
    page2 = await c.get("/api/v1/leads?sort=name&dir=asc&limit=3&offset=3", headers=admin)
    desc = await c.get("/api/v1/leads?sort=name&dir=desc&limit=3", headers=admin)
    by_stage = await c.get("/api/v1/leads?sort=stage&dir=desc&limit=1", headers=admin)
    two_stages = await c.get(
        f"/api/v1/leads?stage_id={stages['Qualified']['id']}&stage_id={stages['New']['id']}",
        headers=admin,
    )
    two_sources = await c.get(
        f"/api/v1/leads?source_id={sources['Website']}&source_id={sources['Referral']}",
        headers=admin,
    )

    assert names(asc) == ["Lead00", "Lead01", "Lead02"] and asc.json()["total"] == 7
    assert names(page2) == ["Lead03", "Lead04", "Lead05"]  # pages never overlap
    assert names(desc)[0] == "Lead06" and names(by_stage) == ["Lead00"]
    assert two_stages.json()["total"] == 7 and two_sources.json()["total"] == 7
    for sort in ("owner", "source", "follow_up", "last_activity", "created", "city"):
        assert (await c.get(f"/api/v1/leads?sort={sort}", headers=admin)).status_code == 200


async def test_owner_and_custom_field_filters(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    m_id, mgr = await login_as(tenant_id, "sales_manager")
    await c.post(
        "/api/v1/custom-fields",
        json={
            "key": "plan",
            "label": "Plan",
            "type": "select",
            "options": [{"value": "basic", "label": "Basic"}, {"value": "pro", "label": "Pro"}],
        },
        headers=admin,
    )
    _, sources = await setup_ids(c, admin)
    await new_lead(c, mgr, sources["Website"], first_name="Mine", custom_fields={"plan": "pro"})
    await new_lead(
        c,
        mgr,
        sources["Website"],
        first_name="Nobody",
        phone="98765 43299",
        assign_to_me=False,
        custom_fields={"plan": "basic"},
    )

    both = await c.get("/api/v1/leads?owner=me&owner=unassigned", headers=mgr)
    pro = await c.get("/api/v1/leads?cf=plan:pro", headers=mgr)
    either = await c.get("/api/v1/leads?cf=plan:pro&cf=plan:basic", headers=mgr)
    bad = await c.get("/api/v1/leads?cf=plan", headers=mgr)

    assert both.json()["total"] == 2
    assert [x["display_name"] for x in pro.json()["items"]] == ["Mine"]
    assert either.json()["total"] == 2 and bad.status_code == 422


async def test_view_counts_follow_visibility(ws):
    tenant_id, c = ws
    a_id, rep = await login_as(tenant_id, "sales_user")
    _, other = await login_as(tenant_id, "sales_user")
    m_id, mgr = await login_as(tenant_id, "sales_manager")
    await make_team(tenant_id, m_id, [a_id])
    _, sources = await setup_ids(c, rep)
    await new_lead(c, rep, sources["Website"], next_follow_up_at=soon(-2))
    await new_lead(c, rep, sources["Website"], phone="98765 43201")
    await new_lead(c, mgr, sources["Website"], phone="98765 43202", assign_to_me=False)
    await new_lead(c, other, sources["Website"], phone="98765 43203")

    mine = (await c.get("/api/v1/leads/counts", headers=rep)).json()
    team = (await c.get("/api/v1/leads/counts", headers=mgr)).json()
    assert mine == {"mine": 2, "today": 0, "overdue": 1, "none": 1, "unassigned": 0, "all": 2}
    assert team["all"] == 3 and team["unassigned"] == 1 and team["mine"] == 0


async def test_bulk_assign_stage_follow_up_and_delete(ws):
    tenant_id, c = ws
    a_id, rep = await login_as(tenant_id, "sales_user")
    b_id, _ = await login_as(tenant_id, "sales_user")
    m_id, mgr = await login_as(tenant_id, "sales_manager")
    _, admin = await login_as(tenant_id, "admin")
    await make_team(tenant_id, m_id, [a_id, b_id])
    await c.post(
        "/api/v1/custom-fields",
        json={"key": "budget", "label": "Budget", "type": "number"},
        headers=admin,
    )
    gated = (
        await c.post(
            "/api/v1/lead-stages",
            json={"name": "Proposal", "required_fields": ["budget"]},
            headers=admin,
        )
    ).json()
    stages, sources, ids = await _seed(c, rep, 4)
    await c.patch(
        f"/api/v1/leads/{ids[0]}", json={"version": 1, "custom_fields": {"budget": 9}}, headers=rep
    )
    bulk = lambda h, **body: c.post("/api/v1/leads/bulk", json=body, headers=h)  # noqa: E731

    rep_assigns = await bulk(rep, action="assign", ids=ids, owner_user_id=str(b_id))
    assigned = await bulk(mgr, action="assign", ids=ids[:2], owner_user_id=str(b_id))
    to_gated = await bulk(mgr, action="stage", ids=ids, stage_id=gated["id"])
    lost_no_reason = await bulk(mgr, action="stage", ids=ids[3:], stage_id=stages["Lost"]["id"])
    lost = await bulk(
        mgr,
        action="stage",
        ids=ids[3:],
        stage_id=stages["Lost"]["id"],
        unqualified_reason="Duplicate",
    )
    follow = await bulk(
        mgr, action="follow_up", filter={"owner": [str(b_id)]}, next_follow_up_at=soon(24)
    )
    mgr_deletes = await bulk(mgr, action="delete", ids=ids)
    both = await bulk(admin, action="delete", ids=ids, filter={})

    assert rep_assigns.status_code == 403
    assert assigned.json() == {"done": 2, "skipped": []}
    gated_body = to_gated.json()
    assert gated_body["done"] == 1 and len(gated_body["skipped"]) == 3  # only one has a budget
    assert "Budget" in gated_body["skipped"][0]["reason"]
    assert lost_no_reason.status_code == 422 and lost.json()["done"] == 1
    assert follow.json()["done"] == 2
    assert mgr_deletes.status_code == 403 and both.status_code == 422

    everything = await bulk(admin, action="delete", filter={"q": "Lead0"})
    assert everything.json()["done"] == 4
    assert (await c.get("/api/v1/leads", headers=admin)).json()["total"] == 0


async def test_bulk_never_touches_leads_you_cannot_see(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, other = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, rep)
    theirs = (await new_lead(c, other, sources["Website"])).json()["id"]

    result = await c.post(
        "/api/v1/leads/bulk",
        json={"action": "follow_up", "ids": [theirs], "next_follow_up_at": soon(5)},
        headers=rep,
    )
    assert result.json() == {"done": 0, "skipped": []}
    lead = (await c.get(f"/api/v1/leads/{theirs}", headers=other)).json()
    assert lead["next_follow_up_at"] is None

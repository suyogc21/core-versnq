"""Step 1: nothing from one company is reachable from another, through any new endpoint."""

from tests.crm.intake_helpers import capture, rule
from tests.factories import login_as, make_workspace


async def test_step1_endpoints_never_cross_companies(client_for):
    a_id, a_slug = await make_workspace()
    b_id, b_slug = await make_workspace()
    a, b = client_for(a_slug), client_for(b_slug)
    _, ah = await login_as(a_id, "admin")
    _, bh = await login_as(b_id, "admin")

    a_rep, _ = await login_as(a_id, "sales_user")
    rule_id = await rule(a_id, user_ids=[a_rep])
    _, lead_id = await capture(a_id, email="x@acme.com", owner="rules")
    sources = {s["name"]: s["id"] for s in (await a.get("/api/v1/lead-sources", headers=ah)).json()}
    form = (
        await a.post(
            "/api/v1/capture-sources",
            json={"name": "Form", "source_id": sources["Website"]},
            headers=ah,
        )
    ).json()
    imp = (
        await a.post(
            "/api/v1/imports",
            json={"file_name": "a.csv", "content": "Phone\n9876500001"},
            headers=ah,
        )
    ).json()

    for method, url in (
        ("GET", f"/api/v1/leads/{lead_id}/duplicates"),
        ("GET", f"/api/v1/leads/{lead_id}/consents"),
        ("GET", f"/api/v1/leads/{lead_id}/organisation-suggestions"),
        ("GET", f"/api/v1/leads/{lead_id}/people"),
        ("GET", f"/api/v1/imports/{imp['id']}"),
        ("GET", f"/api/v1/imports/{imp['id']}/problems"),
        ("DELETE", f"/api/v1/imports/{imp['id']}"),
        ("PATCH", f"/api/v1/assignment-rules/{rule_id}"),
        ("DELETE", f"/api/v1/assignment-rules/{rule_id}"),
        ("PATCH", f"/api/v1/capture-sources/{form['id']}"),
        ("POST", f"/api/v1/capture-sources/{form['id']}/new-key"),
    ):
        kwargs = {"json": {}} if method == "PATCH" else {}
        r = await b.request(method, url, headers=bh, **kwargs)
        assert r.status_code == 404, (method, url, r.status_code)

    assert (await b.get("/api/v1/assignment-rules", headers=bh)).json() == []
    assert (await b.get("/api/v1/capture-sources", headers=bh)).json() == []
    assert (await b.get("/api/v1/imports", headers=bh)).json() == []
    assert (await b.get("/api/v1/notifications", headers=bh)).json()["unread"] == 0
    # Company A's form key does nothing on company B's address.
    r = await b.post(f"/api/v1/capture/{form['key']}", json={"phone": "9876500002"})
    assert r.status_code == 404

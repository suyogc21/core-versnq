"""Step 7b (Decision log #36): key accounts — marking, who sees and changes them, the group
tree, roll-ups per currency, the opportunity grid, the people map and the account plan."""

import pytest

from app.core.modules import set_module
from app.core.tenancy import tenant_session
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "key_accounts", True)
    return tenant_id, client_for(slug)


async def _org(c, h, name, phone):
    _, sources = await setup_ids(c, h)
    body = {
        "kind": "organisation",
        "org_name": name,
        "identities": [{"type": "phone", "value": phone}],
        "source_id": sources["Website"],
    }
    r = await c.post("/api/v1/leads", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _person(c, h, org_id, phone, first="Asha"):
    _, sources = await setup_ids(c, h)
    p = (await new_lead(c, h, sources["Website"], phone=phone, first_name=first)).json()
    r = await c.put(
        f"/api/v1/leads/{p['id']}/organisation", json={"organisation_id": org_id}, headers=h
    )
    assert r.status_code == 200, r.text
    return p


async def _mark(c, h, org_id, **extra):
    r = await c.post("/api/v1/key-accounts", json={"org_lead_id": org_id, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _product(c, h, name, price, currency=None):
    body = {"name": name, "price_minor": price} | ({"currency": currency} if currency else {})
    r = await c.post("/api/v1/products", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _won(c, h, lead_id, amount, currency=None):
    body = {"lead_id": lead_id, "amount_minor": amount}
    if currency:
        pipe = (
            await c.post(
                "/api/v1/pipelines", json={"name": f"P {currency}", "currency": currency}, headers=h
            )
        ).json()
        body["pipeline_id"] = pipe["id"]
    deal = (await c.post("/api/v1/deals", json=body, headers=h)).json()
    pipe = next(
        p
        for p in (await c.get("/api/v1/pipelines", headers=h)).json()
        if p["id"] == deal["pipeline_id"]
    )
    won = next(s for s in pipe["stages"] if s["kind"] == "won")
    r = await c.post(
        f"/api/v1/deals/{deal['id']}/move",
        json={"version": deal["version"], "stage_id": won["id"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_mark_an_organisation_and_its_timeline(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    org = await _org(c, h, "Varanta Group", "98000 00001")
    person = await _person(c, h, org["id"], "98000 00002")
    assert (
        await c.post("/api/v1/key-accounts", json={"org_lead_id": person["id"]}, headers=h)
    ).status_code == 422
    acc = await _mark(
        c, h, org["id"], tier="strategic", target_minor=10_000_000, target_currency="inr"
    )
    assert (
        acc["name"] == "Varanta Group"
        and acc["tier"] == "strategic"
        and acc["target_currency"] == "INR"
    )
    assert "No contact in the last 30 days" in acc["hints"]
    again = await c.post("/api/v1/key-accounts", json={"org_lead_id": org["id"]}, headers=h)
    assert again.status_code == 409
    acts = (await c.get(f"/api/v1/leads/{org['id']}/activities", headers=h)).json()
    assert any(a["type_key"] == "key_account_updated" for a in acts)
    of = (await c.get(f"/api/v1/leads/{org['id']}/key-account", headers=h)).json()
    assert of["id"] == acc["id"]
    # Unmarking keeps the organisation.
    assert (await c.delete(f"/api/v1/key-accounts/{acc['id']}", headers=h)).status_code == 204
    assert (await c.get(f"/api/v1/leads/{org['id']}", headers=h)).status_code == 200


async def test_who_sees_and_changes_an_account(ws):
    tenant_id, c = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    _, other = await login_as(tenant_id, "sales_user")
    _, mgr = await login_as(tenant_id, "sales_manager")
    _, admin = await login_as(tenant_id, "admin")
    org = await _org(c, rep, "Ombrel Pharma", "98000 00011")
    assert (
        await c.post("/api/v1/key-accounts", json={"org_lead_id": org["id"]}, headers=rep)
    ).status_code == 403
    acc = await _mark(c, admin, org["id"], owner_user_id=str(rep_id))
    assert (await c.get(f"/api/v1/key-accounts/{acc['id']}", headers=other)).status_code == 404
    assert (await c.get("/api/v1/key-accounts", headers=other)).json() == []
    mine = (await c.get(f"/api/v1/key-accounts/{acc['id']}", headers=rep)).json()
    assert mine["can_edit"] is True
    r = await c.patch(
        f"/api/v1/key-accounts/{acc['id']}",
        json={"version": mine["version"], "health": "at_risk"},
        headers=rep,
    )
    assert r.status_code == 200 and r.json()["health"] == "at_risk"
    # Handing the account to someone else is for managers.
    r = await c.patch(
        f"/api/v1/key-accounts/{acc['id']}",
        json={"version": r.json()["version"], "owner_user_id": str(rep_id)},
        headers=rep,
    )
    assert r.status_code == 200  # same owner: nothing to hand over
    stale = await c.patch(
        f"/api/v1/key-accounts/{acc['id']}", json={"version": 1, "tier": "maintain"}, headers=mgr
    )
    assert stale.status_code in (404, 409)


async def test_group_tree_never_loops_and_rolls_up_per_currency(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    group = await _mark(
        c, h, (await _org(c, h, "Varanta Group", "98000 00021"))["id"], tier="strategic"
    )
    motors_org = await _org(c, h, "Varanta Motors", "98000 00022")
    motors = await _mark(c, h, motors_org["id"], parent_id=group["id"])
    retail_org = await _org(c, h, "Varanta Retail", "98000 00023")
    retail = await _mark(c, h, retail_org["id"], parent_id=motors["id"])
    r = await c.patch(
        f"/api/v1/key-accounts/{group['id']}",
        json={"version": group["version"], "parent_id": retail["id"]},
        headers=h,
    )
    assert r.status_code == 422 and "circle" in r.json()["detail"]
    await _won(c, h, motors_org["id"], 500_000)
    await _won(c, h, retail_org["id"], 70_000, currency="USD")
    detail = (await c.get(f"/api/v1/key-accounts/{group['id']}", headers=h)).json()
    assert detail["rollup"]["won_this_year"] == []  # nothing on the group company itself
    assert detail["group"]["won_this_year"] == [
        {"currency": "INR", "minor": 500_000},
        {"currency": "USD", "minor": 70_000},
    ]
    assert {n["name"] for n in detail["tree"]} == {
        "Varanta Group",
        "Varanta Motors",
        "Varanta Retail",
    }
    # Removing the middle account keeps its child in the group.
    await c.delete(f"/api/v1/key-accounts/{motors['id']}", headers=h)
    again = (await c.get(f"/api/v1/key-accounts/{retail['id']}", headers=h)).json()
    assert again["parent_id"] == group["id"]


async def test_opportunity_grid_from_deals_and_manual_cells(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    org = await _org(c, h, "Pinewyn Hospitals", "98000 00031")
    acc = await _mark(c, h, org["id"])
    hr = await _product(c, h, "Core HR", 240_000)
    payroll = await _product(c, h, "Payroll", 180_000)
    units = (
        await c.post(f"/api/v1/key-accounts/{acc['id']}/units", json={"name": "HR"}, headers=h)
    ).json()
    assert (
        await c.post(f"/api/v1/key-accounts/{acc['id']}/units", json={"name": "hr"}, headers=h)
    ).status_code == 409
    unit = units[0]["id"]
    r = await c.post(
        f"/api/v1/key-accounts/{acc['id']}/grid/deal",
        json={"unit_id": unit, "product_id": hr["id"]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    cells = {(x["unit_id"], x["product_id"]): x for x in r.json()["cells"]}
    assert cells[(unit, hr["id"])]["state"] == "open" and len(cells[(unit, hr["id"])]["deals"]) == 1
    assert cells[(unit, payroll["id"])]["state"] == "empty"
    comp = (await c.post("/api/v1/competitors", json={"name": "PayNest"}, headers=h)).json()
    bad = await c.put(
        f"/api/v1/key-accounts/{acc['id']}/grid/{unit}/{payroll['id']}",
        json={"status": "competitor"},
        headers=h,
    )
    assert bad.status_code == 422
    r = await c.put(
        f"/api/v1/key-accounts/{acc['id']}/grid/{unit}/{payroll['id']}",
        json={
            "status": "competitor",
            "competitor_id": comp["id"],
            "note": "Contract ends in March",
        },
        headers=h,
    )
    cell = next(x for x in r.json()["cells"] if x["product_id"] == payroll["id"])
    assert cell["state"] == "competitor" and cell["competitor_id"] == comp["id"]
    # A real deal beats the hand-set cell.
    deal = (await c.get(f"/api/v1/key-accounts/{acc['id']}/deals", headers=h)).json()[0]
    assert deal["status"] == "open"


async def test_people_map_only_takes_people_from_the_company(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    org = await _org(c, h, "Granvik Cement", "98000 00041")
    other = await _org(c, h, "Tidara Energy", "98000 00042")
    asha = await _person(c, h, org["id"], "98000 00043")
    stranger = await _person(c, h, other["id"], "98000 00044", first="Ravi")
    acc = await _mark(c, h, org["id"])
    r = await c.put(
        f"/api/v1/key-accounts/{acc['id']}/people/{asha['id']}",
        json={"role": "decision_maker", "stance": "champion", "strength": 5},
        headers=h,
    )
    assert r.status_code == 200
    person = next(p for p in r.json() if p["lead_id"] == asha["id"])
    assert (person["on_map"], person["role"], person["stance"]) == (
        True,
        "decision_maker",
        "champion",
    )
    r = await c.put(f"/api/v1/key-accounts/{acc['id']}/people/{stranger['id']}", json={}, headers=h)
    assert r.status_code == 422
    r = await c.put(
        f"/api/v1/key-accounts/{acc['id']}/people/{asha['id']}", json={"strength": 9}, headers=h
    )
    assert r.status_code == 422
    unit = await c.post(
        f"/api/v1/key-accounts/{acc['id']}/units",
        json={"name": "Finance", "budget_holder_lead_id": stranger["id"]},
        headers=h,
    )
    assert unit.status_code == 422


async def test_account_plan_goals(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    acc = await _mark(c, h, (await _org(c, h, "Elmora Schools", "98000 00051"))["id"])
    url = f"/api/v1/key-accounts/{acc['id']}/goals"
    assert (
        await c.post(url, json={"title": "Expand", "target_minor": 100}, headers=h)
    ).status_code == 422
    goals = (
        await c.post(
            url,
            json={
                "title": "Payroll for all 40 schools",
                "target_minor": 5_000_000,
                "currency": "INR",
            },
            headers=h,
        )
    ).json()
    g = goals[0]
    done = (
        await c.put(f"{url}/{g['id']}", json={"title": g["title"], "status": "done"}, headers=h)
    ).json()
    assert done[0]["status"] == "done"


async def test_switched_off_and_other_companies(ws, client_for):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    acc = await _mark(c, h, (await _org(c, h, "Navaro Retail", "98000 00061"))["id"])
    other_id, slug = await make_workspace()
    _, h2 = await login_as(other_id, "admin")
    c2 = client_for(slug)
    assert (await c2.get("/api/v1/key-accounts", headers=h2)).status_code == 404  # off there
    async with tenant_session(other_id) as db:
        await set_module(db, other_id, "key_accounts", True)
    assert (await c2.get(f"/api/v1/key-accounts/{acc['id']}", headers=h2)).status_code == 404
    assert (await c2.get("/api/v1/key-accounts", headers=h2)).json() == []

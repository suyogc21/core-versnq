"""Step 8 (Decision log #38): field permissions per role, and page layouts."""

import csv
import io

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.roles.models import Role
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_role, make_workspace


async def _field(c, h, entity="lead", **body):
    r = await c.post(f"/api/v1/custom-fields?entity={entity}", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _role(tenant_id, key):
    async with tenant_session(tenant_id) as db:
        return await db.scalar(select(Role.id).where(Role.key == key))


async def _restrict(c, admin, tenant_id, access, entity="lead", role="sales_user"):
    r = await c.put(
        f"/api/v1/field-access/{entity}/{await _role(tenant_id, role)}",
        json={"access": access},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _setup(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin)
    await _field(c, admin, key="budget", label="Budget", type="number")
    await _field(c, admin, key="locality", label="Locality", type="text")
    return tenant_id, c, admin, rep, sources


def _rows(r):
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


# ---------- hidden ----------
async def test_a_hidden_field_never_reaches_the_role(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"cf.budget": "hidden", "city": "hidden"})
    lead = (
        await new_lead(
            c, rep, sources["Website"], phone="98765 10001", custom_fields={"locality": "Baner"}
        )
    ).json()
    refused = await new_lead(c, rep, sources["Website"], phone="98765 10011", city="Pune")
    assert refused.status_code == 403  # a hidden field can't be filled in either
    # the rep could not have typed a budget; an admin adds it
    got = await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)
    r = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={
            "version": got.json()["version"],
            "city": "Pune",
            "custom_fields": {"budget": 5000000},
        },
        headers=admin,
    )
    assert r.status_code == 200
    seen = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    assert "budget" not in seen["custom_fields"] and seen["custom_fields"]["locality"] == "Baner"
    assert seen["city"] is None
    listed = (await c.get("/api/v1/leads", headers=rep)).json()["items"][0]
    assert "budget" not in listed["custom_fields"] and listed["city"] is None
    full = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()
    assert full["custom_fields"]["budget"] == 5000000 and full["city"] == "Pune"
    # can't filter, search or sort on it
    assert (await c.get("/api/v1/leads?cf=budget:5000000", headers=rep)).status_code == 422
    assert (await c.get("/api/v1/leads?sort=city", headers=rep)).status_code == 422


async def test_a_hidden_field_is_not_in_the_export(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"cf.budget": "hidden"}, role="sales_manager")
    _, manager = await login_as(tenant_id, "sales_manager")
    async with tenant_session(tenant_id) as db:
        from app.modules.roles.models import RolePermission

        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role_id=await _role(tenant_id, "sales_manager"),
                permission_code="leads.export",
            )
        )
    await new_lead(c, admin, sources["Website"], phone="98765 10002", custom_fields={"budget": 900})
    mine = _rows(await c.get("/api/v1/leads/export", headers=manager))
    theirs = _rows(await c.get("/api/v1/leads/export", headers=admin))
    assert "Budget" not in mine[0] and "Budget" in theirs[0] and "Locality" in mine[0]


async def test_saving_the_page_does_not_trip_over_a_hidden_field(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"city": "hidden", "cf.budget": "hidden"})
    lead = (await new_lead(c, rep, sources["Website"], phone="98765 10003")).json()
    v = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()["version"]
    await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": v, "city": "Pune", "custom_fields": {"budget": 10}},
        headers=admin,
    )
    seen = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    # the rep's form sends the hidden city back blank: that is not a change
    r = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": seen["version"], "city": None, "first_name": "Ravi",
              "custom_fields": seen["custom_fields"]},
        headers=rep,
    )  # fmt: skip
    assert r.status_code == 200, r.text
    full = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()
    assert full["city"] == "Pune" and full["custom_fields"]["budget"] == 10
    r = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": full["version"], "city": "Mumbai"},
        headers=rep,
    )
    assert r.status_code == 403


# ---------- view only ----------
async def test_view_only_cannot_be_changed_from_anywhere(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"cf.budget": "view", "phone": "view"})
    # can't fill it on create either
    r = await new_lead(c, rep, sources["Website"], phone="98765 10004", custom_fields={"budget": 1})
    assert r.status_code == 403
    lead = (await new_lead(c, rep, sources["Website"], phone="98765 10004")).json()
    v = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()["version"]
    await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": v, "custom_fields": {"budget": 70}},
        headers=admin,
    )
    seen = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    assert seen["custom_fields"]["budget"] == 70  # visible
    same = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": seen["version"], "custom_fields": {"budget": 70}},
        headers=rep,
    )
    assert same.status_code == 200
    changed = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": same.json()["version"], "custom_fields": {"budget": 71}},
        headers=rep,
    )
    assert changed.status_code == 403 and "Budget" in changed.json()["detail"]
    phone = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": same.json()["version"],
              "identities": [{"type": "phone", "value": "98765 99999", "is_primary": True}]},
        headers=rep,
    )  # fmt: skip
    assert phone.status_code == 403
    keep = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": same.json()["version"],
              "identities": [{"type": "phone", "value": "+91 98765 10004", "is_primary": True}]},
        headers=rep,
    )  # fmt: skip
    assert keep.status_code == 200, keep.text


async def test_phone_and_email_can_never_be_hidden_and_admins_are_never_restricted(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    r = await c.put(
        f"/api/v1/field-access/lead/{await _role(tenant_id, 'sales_user')}",
        json={"access": {"phone": "hidden"}},
        headers=admin,
    )
    assert r.status_code == 422
    r = await c.put(
        f"/api/v1/field-access/lead/{await _role(tenant_id, 'admin')}",
        json={"access": {"cf.budget": "hidden"}},
        headers=admin,
    )
    assert r.status_code == 422
    assert (await c.get("/api/v1/field-access/lead", headers=rep)).status_code == 403


async def test_required_field_a_role_cannot_edit_does_not_block_it(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _field(c, admin, key="pan", label="PAN", type="text", required=True)
    await _restrict(c, admin, tenant_id, {"cf.pan": "view"})
    r = await new_lead(c, rep, sources["Website"], phone="98765 10005")
    assert r.status_code == 201, r.text
    blocked = await new_lead(c, admin, sources["Website"], phone="98765 10006")
    assert blocked.status_code == 422  # still required for people who can fill it


async def test_import_into_a_locked_field_is_refused(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"cf.budget": "view"})
    async with tenant_session(tenant_id) as db:
        from app.modules.roles.models import RolePermission

        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role_id=await _role(tenant_id, "sales_user"),
                permission_code="leads.import",
            )
        )
    imp = (
        await c.post(
            "/api/v1/imports",
            json={"file_name": "a.csv", "content": "Phone,Budget\n9876500001,5"},
            headers=rep,
        )
    ).json()
    r = await c.post(
        f"/api/v1/imports/{imp['id']}/start",
        json={
            "mapping": {"Phone": "phone", "Budget": "cf.budget"},
            "source_id": sources["Website"],
        },
        headers=rep,
    )
    assert r.status_code == 422 and "Budget" in r.json()["detail"]


async def test_calculated_field_built_from_a_hidden_field_is_hidden_too(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    calc = await _field(c, admin, key="lakhs", label="Budget in lakhs", type="calculated",
                        formula="budget / 100000")  # fmt: skip
    await _restrict(c, admin, tenant_id, {"cf.budget": "hidden"})
    lead = (await new_lead(c, rep, sources["Website"], phone="98765 10007")).json()
    v = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()["version"]
    await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": v, "custom_fields": {"budget": 5000000}},
        headers=admin,
    )
    seen = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    assert "lakhs" not in seen["custom_fields"]
    await c.patch(
        f"/api/v1/custom-fields/{calc['id']}", json={"show_with_hidden_inputs": True}, headers=admin
    )
    seen = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    assert seen["custom_fields"]["lakhs"] == 50 and "budget" not in seen["custom_fields"]


async def test_an_api_key_follows_its_roles_field_access(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    role_id = await make_role(tenant_id, "Integrations", scope="all")
    async with tenant_session(tenant_id) as db:
        from app.modules.roles.models import RolePermission

        db.add(RolePermission(tenant_id=tenant_id, role_id=role_id, permission_code="leads.edit"))
    r = await c.put(
        f"/api/v1/field-access/lead/{role_id}",
        json={"access": {"cf.budget": "hidden"}},
        headers=admin,
    )
    assert r.status_code == 200
    key = (
        await c.post(
            "/api/v1/integrations/keys",
            json={"name": "Zapier", "role_id": str(role_id)},
            headers=admin,
        )
    ).json()["key"]
    await new_lead(c, admin, sources["Website"], phone="98765 10008", custom_fields={"budget": 3})
    rows = (await c.get("/api/v1/leads", headers={"Authorization": f"Bearer {key}"})).json()
    assert rows["items"] and all("budget" not in r["custom_fields"] for r in rows["items"])


# ---------- deals ----------
async def test_hidden_deal_value_is_blank_everywhere(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"amount": "hidden"}, entity="deal")
    lead = (await new_lead(c, rep, sources["Website"], phone="98765 10009")).json()
    refused = await c.post(
        "/api/v1/deals", json={"lead_id": lead["id"], "amount_minor": 500}, headers=rep
    )
    assert refused.status_code == 403
    deal = (await c.post("/api/v1/deals", json={"lead_id": lead["id"]}, headers=rep)).json()
    full = (await c.get(f"/api/v1/deals/{deal['id']}", headers=admin)).json()
    await c.patch(
        f"/api/v1/deals/{deal['id']}",
        json={"version": full["version"], "amount_minor": 250000},
        headers=admin,
    )
    seen = (await c.get(f"/api/v1/deals/{deal['id']}", headers=rep)).json()
    assert seen["amount_minor"] is None
    board = (await c.get("/api/v1/deals/board", headers=rep)).json()
    assert board["open_minor"] is None and all(
        col["amount_minor"] is None for col in board["columns"]
    )
    assert (await c.get(f"/api/v1/deals/{deal['id']}/products", headers=rep)).json() == []
    lines = await c.put(
        f"/api/v1/deals/{deal['id']}/products",
        json={"version": seen["version"], "lines": []},
        headers=rep,
    )
    assert lines.status_code == 403
    assert (await c.get("/api/v1/deals?sort=amount", headers=rep)).status_code == 422
    assert (await c.get(f"/api/v1/deals/{deal['id']}", headers=admin)).json()[
        "amount_minor"
    ] == 250000


# ---------- layouts ----------
async def test_default_layout_is_todays_page_then_saved_and_reset(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _field(c, admin, key="pan", label="PAN", type="text", group_name="Billing", required=True)
    d = (await c.get("/api/v1/layouts/lead", headers=rep)).json()
    assert d["is_default"] is True
    assert [s["name"] for s in d["sections"]] == ["Details", "Billing"]
    assert "org_name" in d["sections"][0]["fields"] and "cf.budget" in d["sections"][0]["fields"]
    body = {
        "sections": [
            {"name": "Requirement", "fields": ["cf.budget", "cf.locality"]},
            {"name": "Company", "fields": ["org_name", "city"]},
        ],
        "highlights": ["cf.budget", "cf.locality"],
        "add_form": ["cf.budget"],
    }
    assert (await c.put("/api/v1/layouts/lead", json=body, headers=rep)).status_code == 403
    saved = (await c.put("/api/v1/layouts/lead", json=body, headers=admin)).json()
    assert saved["is_default"] is False and saved["highlights"] == ["cf.budget", "cf.locality"]
    assert "cf.pan" in saved["add_form"]  # required fields are always on the add form
    dup = body | {
        "sections": [{"name": "A", "fields": ["cf.budget"]}, {"name": "B", "fields": ["cf.budget"]}]
    }
    assert (await c.put("/api/v1/layouts/lead", json=dup, headers=admin)).status_code == 422
    five = body | {"highlights": ["org_name", "city", "website", "industry", "region"]}
    assert (await c.put("/api/v1/layouts/lead", json=five, headers=admin)).status_code == 422
    unknown = body | {"add_form": ["cf.nope"]}
    assert (await c.put("/api/v1/layouts/lead", json=unknown, headers=admin)).status_code == 422
    # a deleted field drops out of the saved layout
    fields = {
        f["key"]: f["id"] for f in (await c.get("/api/v1/custom-fields", headers=admin)).json()
    }
    await c.delete(f"/api/v1/custom-fields/{fields['locality']}", headers=admin)
    after = (await c.get("/api/v1/layouts/lead", headers=rep)).json()
    assert after["sections"][0]["fields"] == ["cf.budget"] and after["highlights"] == ["cf.budget"]
    assert (await c.delete("/api/v1/layouts/lead", headers=admin)).status_code == 204
    assert (await c.get("/api/v1/layouts/lead", headers=rep)).json()["is_default"] is True


async def test_layout_tells_the_reader_what_they_may_do(ws):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"cf.budget": "view", "city": "hidden"})
    mine = (await c.get("/api/v1/layouts/lead", headers=rep)).json()["my_access"]
    assert mine == {"cf.budget": "view", "city": "hidden"}
    assert (await c.get("/api/v1/layouts/lead", headers=admin)).json()["my_access"] == {}


async def test_another_company_sees_none_of_this(ws, client_for):
    tenant_id, c, admin, rep, sources = await _setup(ws)
    await _restrict(c, admin, tenant_id, {"cf.budget": "hidden"})
    await c.put(
        "/api/v1/layouts/lead",
        json={"sections": [{"name": "Mine", "fields": ["cf.budget"]}]},
        headers=admin,
    )
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)
    theirs = (await oc.get("/api/v1/layouts/lead", headers=other_admin)).json()
    assert theirs["is_default"] is True
    grid = (await oc.get("/api/v1/field-access/lead", headers=other_admin)).json()
    assert all(r["access"] == {} for r in grid["roles"])
    r = await oc.put(
        f"/api/v1/field-access/lead/{await _role(tenant_id, 'sales_user')}",
        json={"access": {}},
        headers=other_admin,
    )
    assert r.status_code == 404

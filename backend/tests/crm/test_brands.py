"""Batch 4 (docs/plans/finish-plan.md): several brands in one company. Admins manage brands; a
new lead gets the default brand, the one chosen, or its form's; deals and invoices are of their
lead's brand and move with it; a person limited to some brands can't list, open or search the
leads, deals, invoices or customers of another brand, through the app or an API key; people who
aren't limited (and companies without brands) see everything as before; another company sees
none of it."""

import uuid

from sqlalchemy import select

from app.core.modules import set_module
from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_custom_role, make_workspace


async def _brand(c, h, name, **extra):
    r = await c.post("/api/v1/brands", json={"name": name, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _lead(c, h, phone, **extra):
    _, sources = await setup_ids(c, h)
    r = await new_lead(c, h, sources["Website"], phone=phone, **extra)
    assert r.status_code == 201, r.text
    return r.json()


async def test_admins_manage_brands_and_the_first_is_the_default(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")

    by_rep = await c.post("/api/v1/brands", json={"name": "Nope"}, headers=rep)
    first = await _brand(c, admin, "Acme Academy", colour="#112233",
                         logo_url="https://acme.example/logo.png")  # fmt: skip
    second = await _brand(c, admin, "Acme Kids")
    same = await c.post("/api/v1/brands", json={"name": "acme kids"}, headers=admin)
    made = await c.post(f"/api/v1/brands/{second['id']}/default", headers=admin)
    off = {"name": "Acme Kids", "is_active": False}
    off_default = await c.put(f"/api/v1/brands/{second['id']}", json=off, headers=admin)
    listed = (await c.get("/api/v1/brands", headers=rep)).json()

    assert by_rep.status_code == 403
    assert first["is_default"] is True and second["is_default"] is False
    assert same.status_code == 422 and same.json()["code"] == "brand_exists"
    assert made.json()["is_default"] is True
    assert off_default.json()["code"] == "brand_is_default"
    assert [b["name"] for b in listed] == ["Acme Kids", "Acme Academy"]  # the default first
    assert [b["is_default"] for b in listed] == [True, False]


async def test_new_leads_get_a_brand_and_deals_and_invoices_follow(ws):
    tenant_id, c = ws
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "money", True)
    _, admin = await login_as(tenant_id, "admin")
    plain = await _lead(c, admin, "98765 00001")  # no brands yet: works as before
    a = await _brand(c, admin, "Brand A")
    b = await _brand(c, admin, "Brand B")

    default = await _lead(c, admin, "98765 00002")
    chosen = await _lead(c, admin, "98765 00003", brand_id=b["id"])
    pipeline = (await c.get("/api/v1/pipelines", headers=admin)).json()[0]
    deal = await c.post("/api/v1/deals", json={"lead_id": chosen["id"],
                        "pipeline_id": pipeline["id"]}, headers=admin)  # fmt: skip
    customer = await c.post(f"/api/v1/leads/{chosen['id']}/customer", json={}, headers=admin)
    invoice = await c.post("/api/v1/invoices", json={"customer_id": customer.json()["id"]},
                           headers=admin)  # fmt: skip
    moved = await c.patch(f"/api/v1/leads/{chosen['id']}",
                          json={"version": chosen["version"], "brand_id": a["id"]},
                          headers=admin)  # fmt: skip
    deal_after = await c.get(f"/api/v1/deals/{deal.json()['id']}", headers=admin)
    inv_after = await c.get(f"/api/v1/invoices/{invoice.json()['id']}", headers=admin)
    only_b = await c.get("/api/v1/leads", params={"brand_id": b["id"]}, headers=admin)

    assert plain["brand_id"] is None and default["brand_id"] == a["id"]
    assert chosen["brand_id"] == b["id"]
    assert deal.status_code == 201, deal.text
    assert deal.json()["brand_id"] == b["id"]
    assert invoice.status_code == 201, invoice.text
    assert invoice.json()["brand_id"] == b["id"]
    assert moved.status_code == 200 and moved.json()["brand_id"] == a["id"]
    assert deal_after.json()["brand_id"] == a["id"] and inv_after.json()["brand_id"] == a["id"]
    assert only_b.json()["total"] == 0


async def test_a_person_limited_to_a_brand_sees_only_that_brand(ws):
    tenant_id, c = ws
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "money", True)
    admin_id, admin = await login_as(tenant_id, "admin")
    a = await _brand(c, admin, "Brand A")
    b = await _brand(c, admin, "Brand B")
    lead_a = await _lead(c, admin, "98765 10001", first_name="Asha", brand_id=a["id"])
    lead_b = await _lead(c, admin, "98765 10002", first_name="Bina", brand_id=b["id"])
    pipeline = (await c.get("/api/v1/pipelines", headers=admin)).json()[0]
    deals = {}
    for lead in (lead_a, lead_b):
        r = await c.post("/api/v1/deals", json={"lead_id": lead["id"],
                         "pipeline_id": pipeline["id"]}, headers=admin)  # fmt: skip
        deals[lead["id"]] = r.json()["id"]
    cust_b = (await c.post(f"/api/v1/leads/{lead_b['id']}/customer", json={},
                           headers=admin)).json()  # fmt: skip
    inv_b = (await c.post("/api/v1/invoices", json={"customer_id": cust_b["id"]},
                          headers=admin)).json()  # fmt: skip

    # an all-scope manager limited to brand A, and an API key whose user is limited to brand A
    role = await make_custom_role(tenant_id, "Brand manager", "all",
                                  ("leads.edit", "leads.create", "customers.read",
                                   "invoices.read"))  # fmt: skip
    limited_id, limited = await login_as(tenant_id, role_id=role)
    self_limit = await c.put(f"/api/v1/users/{admin_id}/brands",
                             json={"brand_ids": [a["id"]]}, headers=admin)  # fmt: skip
    set_ = await c.put(f"/api/v1/users/{limited_id}/brands", json={"brand_ids": [a["id"]]},
                       headers=admin)  # fmt: skip
    key = await c.post("/api/v1/integrations/keys", json={"name": "Brand A tool",
                       "role_id": str(role)}, headers=admin)  # fmt: skip
    async with tenant_session(tenant_id) as db:
        from app.modules.integrations.models import ApiKey

        key_user = await db.scalar(select(ApiKey.user_id).where(ApiKey.id == uuid.UUID(
            key.json()["id"])))  # fmt: skip
    await c.put(f"/api/v1/users/{key_user}/brands", json={"brand_ids": [a["id"]]}, headers=admin)
    api = {"Authorization": f"Bearer {key.json()['key']}"}

    for h in (limited, api):
        leads = (await c.get("/api/v1/leads", headers=h)).json()
        found = (await c.get("/api/v1/leads", params={"q": "Bina"}, headers=h)).json()
        open_b = await c.get(f"/api/v1/leads/{lead_b['id']}", headers=h)
        deal_list = (await c.get("/api/v1/deals", headers=h)).json()
        deal_b = await c.get(f"/api/v1/deals/{deals[lead_b['id']]}", headers=h)
        assert [x["id"] for x in leads["items"]] == [lead_a["id"]]
        assert found["total"] == 0 and open_b.status_code == 404
        assert [x["id"] for x in deal_list["items"]] == [deals[lead_a["id"]]]
        assert deal_b.status_code == 404
    invoices = (await c.get("/api/v1/invoices", headers=limited)).json()
    inv_open = await c.get(f"/api/v1/invoices/{inv_b['id']}", headers=limited)
    cust_open = await c.get(f"/api/v1/customers/{cust_b['id']}", headers=limited)
    other_brand = await _new(c, limited, "98765 10003", b["id"])
    own_brand = await _new(c, limited, "98765 10004", None)
    everyone = (await c.get("/api/v1/leads", headers=admin)).json()

    assert self_limit.json()["code"] == "brand_self_limit"
    assert set_.json()["brand_ids"] == [a["id"]]
    assert invoices["total"] == 0 and inv_open.status_code == 404
    assert cust_open.status_code == 404
    assert other_brand.json()["code"] == "brand_not_yours"
    assert own_brand.json()["brand_id"] == a["id"]  # their first allowed brand
    assert everyone["total"] == 3  # the admin isn't limited


async def _new(c, h, phone, brand_id):
    _, sources = await setup_ids(c, h)
    body = {"first_name": "New", "identities": [{"type": "phone", "value": phone}],
            "source_id": sources["Website"]}  # fmt: skip
    if brand_id:
        body["brand_id"] = brand_id
    return await c.post("/api/v1/leads", json=body, headers=h)


async def test_a_brands_form_and_page_and_channels(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await _brand(c, admin, "Brand A")
    b = await _brand(c, admin, "Brand B", colour="#ff0000", logo_url="https://b.example/l.png")
    _, sources = await setup_ids(c, admin)
    form = {"title": "Join", "button": "Send", "fields": [
        {"target": "first_name", "label": "Name", "required": True},
        {"target": "phone", "label": "Phone", "required": True}]}  # fmt: skip
    src = await c.post("/api/v1/capture-sources", json={"name": "B form", "source_id":
                       sources["Website"], "form": form, "hosted": True, "brand_id": b["id"]},
                       headers=admin)  # fmt: skip
    public_id = src.json()["public_id"]
    page = await c.get(f"/api/v1/forms/{public_id}")
    sent = await c.post(f"/api/v1/forms/{public_id}", json={"first_name": "Gita",
                        "phone": "98765 20001"})  # fmt: skip
    channels = await c.get("/api/v1/brands/channels", headers=admin)
    no_wa = await c.put("/api/v1/brands/channels/whatsapp", json={"brand_id": b["id"]},
                        headers=admin)  # fmt: skip

    assert src.status_code == 201, src.text
    assert page.json()["company"] == {"name": "Brand B", "logo_url": "https://b.example/l.png",
                                      "primary_color": "#ff0000"}  # fmt: skip
    assert sent.status_code == 201, sent.text
    async with tenant_session(tenant_id) as db:
        lead = await db.scalar(select(Lead).where(Lead.first_name == "Gita"))
    assert str(lead.brand_id) == b["id"]
    assert channels.json() == {"mailboxes": [], "whatsapp": None}
    assert no_wa.status_code == 404


async def test_another_company_sees_no_brands(ws, client_for):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    brand = await _brand(c, admin, "Ours")
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    other = client_for(other_slug)

    listed = await other.get("/api/v1/brands", headers=other_admin)
    edit = await other.put(f"/api/v1/brands/{brand['id']}", json={"name": "Theirs"},
                           headers=other_admin)  # fmt: skip
    use = await _new(other, other_admin, "98765 30001", brand["id"])

    assert listed.json() == [] and edit.status_code == 404
    assert use.json()["code"] == "brand_invalid"

"""Step 2: company-defined record types, records, access per role, links."""

from sqlalchemy import func, select

from app.core.events_model import Event
from app.core.tenancy import tenant_session
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as, make_workspace


async def _property_type(c, h, **extra):
    r = await c.post(
        "/api/v1/record-types",
        json={"key": "property", "singular": "Property", "plural": "Properties", "has_stages": True}
        | extra,
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _field(c, h, entity, **body):
    r = await c.post(f"/api/v1/custom-fields?entity={entity}", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _record(c, h, type_="property", **body):
    return await c.post("/api/v1/records", json={"type": type_, **body}, headers=h)


# ---------- packs ----------
async def test_edtech_starts_with_batches_linked_to_students(client_for):
    tenant_id, slug = await make_workspace(pack="edtech")
    c = client_for(slug)
    _, h = await login_as(tenant_id, "admin")
    types = (await c.get("/api/v1/record-types", headers=h)).json()
    assert [(t["key"], t["plural"], t["has_owner"]) for t in types] == [("batch", "Batches", False)]
    batch = types[0]
    stages = (await c.get(f"/api/v1/record-types/{batch['id']}/stages", headers=h)).json()
    assert [s["name"] for s in stages] == ["Upcoming", "Running", "Completed"]
    fields = (await c.get("/api/v1/custom-fields?entity=rt:batch", headers=h)).json()
    assert [f["key"] for f in fields] == ["course", "start_date", "seats", "mode"]
    links = (await c.get("/api/v1/link-types", headers=h)).json()
    assert [(x["label"], x["inverse_label"], x["to_type_id"]) for x in links] == [
        ("Enrolled in", "Students", batch["id"])
    ]


async def test_generic_pack_has_no_record_types(admin):
    c, h = admin
    assert (await c.get("/api/v1/record-types", headers=h)).json() == []


# ---------- setting up a type ----------
async def test_admin_creates_a_type_with_stages_and_default_access(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    _, mgr = await login_as(tenant_id, "sales_manager")
    rt = await _property_type(c, h)
    assert rt["my_access"] == {
        "view": True,
        "create": True,
        "edit": True,
        "delete": True,
        "scope": "all",
    }
    stages = (await c.get(f"/api/v1/record-types/{rt['id']}/stages", headers=h)).json()
    assert [(s["name"], s["is_open"]) for s in stages] == [("Open", True), ("Closed", False)]
    access = {
        a["role_name"]: a
        for a in (await c.get(f"/api/v1/record-types/{rt['id']}/access", headers=h)).json()
    }
    assert "Owner" not in access
    assert (access["Sales Manager"]["scope"], access["Sales Manager"]["delete"]) == ("team", False)
    assert (access["Sales User"]["scope"], access["Sales User"]["create"]) == ("own", True)
    assert access["Finance"]["view"] is False
    # Only configurers change types; the same key or name twice is refused.
    body = {"key": "flat", "singular": "Flat", "plural": "Flats"}
    assert (await c.post("/api/v1/record-types", json=body, headers=mgr)).status_code == 403
    dup = {"key": "property", "singular": "Other", "plural": "Others"}
    assert (await c.post("/api/v1/record-types", json=dup, headers=h)).status_code == 409
    bad = {"key": "Bad Key", "singular": "x", "plural": "y"}
    assert (await c.post("/api/v1/record-types", json=bad, headers=h)).status_code == 422


async def test_a_type_in_use_can_only_be_switched_off(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    rt = await _property_type(c, h)
    await _field(c, h, "rt:property", key="price", label="Price", type="number")
    assert (await _record(c, h, name="Villa 12")).status_code == 201
    assert (await c.delete(f"/api/v1/record-types/{rt['id']}", headers=h)).status_code == 409
    off = await c.patch(f"/api/v1/record-types/{rt['id']}", json={"is_active": False}, headers=h)
    assert off.json()["is_active"] is False
    assert (await c.get("/api/v1/record-types", headers=h)).json() == []
    assert len((await c.get("/api/v1/record-types?include_hidden=true", headers=h)).json()) == 1
    assert (await c.get("/api/v1/records?type=property", headers=h)).status_code == 404
    other = await c.post(
        "/api/v1/record-types",
        json={"key": "unit", "singular": "Unit", "plural": "Units"},
        headers=h,
    )
    await _field(c, h, "rt:unit", key="size", label="Size", type="number")
    assert (
        await c.delete(f"/api/v1/record-types/{other.json()['id']}", headers=h)
    ).status_code == 204
    assert (await c.get("/api/v1/custom-fields?entity=rt:unit", headers=h)).status_code == 422


# ---------- records ----------
async def test_records_follow_every_field_and_stage_rule(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    rt = await _property_type(c, h)
    await _field(
        c, h, "rt:property", key="ref", label="Ref no", type="text", is_unique=True, required=True
    )
    await _field(
        c, h, "rt:property", key="city", label="City", type="select",
        options=[{"value": "dxb", "label": "Dubai"}, {"value": "auh", "label": "Abu Dhabi"}],
    )  # fmt: skip
    await _field(
        c, h, "rt:property", key="area", label="Area", type="select", depends_on="city",
        options=[{"value": "marina", "label": "Marina", "parent": "dxb"}],
    )  # fmt: skip
    stages = {
        s["name"]: s
        for s in (await c.get(f"/api/v1/record-types/{rt['id']}/stages", headers=h)).json()
    }
    sold = await c.post(
        f"/api/v1/record-types/{rt['id']}/stages",
        json={"name": "Sold", "is_open": False, "required_fields": ["area"]},
        headers=h,
    )
    assert sold.status_code == 201

    assert (await _record(c, h, name="No ref")).status_code == 422  # required field
    villa = await _record(c, h, name="  Villa   12 ", custom_fields={"ref": "V-12", "city": "dxb"})
    assert villa.status_code == 201
    v = villa.json()
    assert (v["name"], v["stage_id"]) == ("Villa 12", stages["Open"]["id"])
    clash = await _record(c, h, name="Other", custom_fields={"ref": " v-12 "})
    assert clash.status_code == 409
    wrong_area = await c.patch(
        f"/api/v1/records/{v['id']}",
        json={"version": v["version"], "custom_fields": {"city": "auh", "area": "marina"}},
        headers=h,
    )
    assert wrong_area.status_code == 422
    blocked = await c.patch(
        f"/api/v1/records/{v['id']}",
        json={"version": v["version"], "stage_id": sold.json()["id"]},
        headers=h,
    )
    assert blocked.status_code == 422 and "Area" in blocked.json()["detail"]
    moved = await c.patch(
        f"/api/v1/records/{v['id']}",
        json={
            "version": v["version"],
            "stage_id": sold.json()["id"],
            "custom_fields": {"area": "marina"},
        },
        headers=h,
    )
    assert moved.status_code == 200
    stale = await c.patch(
        f"/api/v1/records/{v['id']}", json={"version": v["version"], "name": "X"}, headers=h
    )
    assert stale.status_code == 409
    timeline = [
        a["type_key"]
        for a in (await c.get(f"/api/v1/records/{v['id']}/activities", headers=h)).json()
    ]
    assert timeline == ["lead_updated", "stage_changed", "record_created"]
    async with tenant_session(tenant_id) as db:
        types = (await db.scalars(select(Event.type))).all()
    assert {"record.created", "record.updated", "record.stage_changed"} <= set(types)

    assert (await c.delete(f"/api/v1/records/{v['id']}", headers=h)).status_code == 204
    again = await _record(c, h, name="Reuse", custom_fields={"ref": "V-12"})
    assert again.status_code == 201  # the unique value was freed


async def test_lists_filter_sort_and_page(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    await _property_type(c, h)
    await _field(
        c, h, "rt:property", key="beds", label="Bedrooms", type="select",
        options=[{"value": "1", "label": "1"}, {"value": "2", "label": "2"}],
    )  # fmt: skip
    for i in range(12):
        await _record(
            c, h, name=f"Unit {i:02d}", custom_fields={"beds": "2" if i % 3 == 0 else "1"}
        )
    page = (
        await c.get("/api/v1/records?type=property&sort=name&dir=asc&limit=5&offset=5", headers=h)
    ).json()
    assert page["total"] == 12 and [r["name"] for r in page["items"]] == [
        f"Unit {i:02d}" for i in range(5, 10)
    ]
    twos = (await c.get("/api/v1/records?type=property&cf=beds:2", headers=h)).json()
    assert twos["total"] == 4
    found = (await c.get("/api/v1/records?type=property&q=unit 1", headers=h)).json()
    assert found["total"] == 2
    bulk = await c.post(
        "/api/v1/records/bulk",
        json={"action": "delete", "ids": [r["id"] for r in page["items"]]},
        headers=h,
    )
    assert bulk.json() == {"done": 5, "skipped": []}


# ---------- access ----------
async def test_access_per_role_and_scope(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    mgr_id, mgr = await login_as(tenant_id, "sales_manager")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    other_id, other = await login_as(tenant_id, "sales_user")
    _, fin = await login_as(tenant_id, "finance")
    await make_team(tenant_id, mgr_id, [rep_id])
    rt = await _property_type(c, admin)

    mine = (await _record(c, rep, name="Rep's")).json()
    assert mine["owner_user_id"] == str(rep_id)
    theirs = (await _record(c, other, name="Other's")).json()
    assert (await _record(c, rep, name="x", owner_user_id=str(other_id))).status_code == 403

    names = lambda h: c.get("/api/v1/records?type=property&sort=name&dir=asc", headers=h)  # noqa: E731
    assert [r["name"] for r in (await names(rep)).json()["items"]] == ["Rep's"]
    assert [r["name"] for r in (await names(mgr)).json()["items"]] == ["Rep's"]
    assert [r["name"] for r in (await names(admin)).json()["items"]] == ["Other's", "Rep's"]
    assert (await c.get(f"/api/v1/records/{theirs['id']}", headers=rep)).status_code == 404
    assert (await names(fin)).status_code == 404
    assert (await c.get("/api/v1/record-types", headers=fin)).json() == []
    assert (await c.delete(f"/api/v1/records/{mine['id']}", headers=rep)).status_code == 403

    # Admin makes Sales Users view-only, everything.
    access = (await c.get(f"/api/v1/record-types/{rt['id']}/access", headers=admin)).json()
    for a in access:
        if a["role_name"] == "Sales User":
            a.update(view=True, create=False, edit=False, delete=False, scope="all")
    assert (
        await c.put(f"/api/v1/record-types/{rt['id']}/access", json=access, headers=admin)
    ).status_code == 200
    assert len((await names(rep)).json()["items"]) == 2
    assert (await _record(c, rep, name="Not allowed")).status_code == 403
    edit = await c.patch(
        f"/api/v1/records/{mine['id']}", json={"version": mine["version"], "name": "x"}, headers=rep
    )
    assert edit.status_code == 403
    bad = [a | {"view": False, "edit": True} for a in access]
    assert (
        await c.put(f"/api/v1/record-types/{rt['id']}/access", json=bad, headers=admin)
    ).status_code == 422


async def test_types_without_owners_are_shared(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    await c.post(
        "/api/v1/record-types",
        json={"key": "batch", "singular": "Batch", "plural": "Batches", "has_owner": False},
        headers=admin,
    )
    made = (await _record(c, admin, type_="batch", name="DS Weekend")).json()
    assert made["owner_user_id"] is None
    seen = (await c.get("/api/v1/records?type=batch", headers=rep)).json()
    assert [r["name"] for r in seen["items"]] == ["DS Weekend"]


# ---------- links ----------
async def _setup_links(c, h, **kind):
    rt = await _property_type(c, h)
    lt = await c.post(
        "/api/v1/link-types",
        json={
            "to_type_id": rt["id"],
            "label": "Interested in",
            "inverse_label": "Interested buyers",
        }
        | kind,
        headers=h,
    )
    assert lt.status_code == 201, lt.text
    return rt, lt.json()


async def test_link_a_lead_to_a_record_both_ways(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    _, sources = await setup_ids(c, h)
    _, lt = await _setup_links(c, h)
    lead = (await new_lead(c, h, sources["Website"])).json()
    villa = (await _record(c, h, name="Villa 12")).json()
    body = {"link_type_id": lt["id"], "from_lead_id": lead["id"], "to_record_id": villa["id"]}
    made = await c.post("/api/v1/links", json=body, headers=h)
    assert made.status_code == 201
    assert (await c.post("/api/v1/links", json=body, headers=h)).status_code == 409  # once

    from_lead = (await c.get(f"/api/v1/links?lead_id={lead['id']}", headers=h)).json()
    assert [(x["label"], x["direction"], x["other"]["name"]) for x in from_lead] == [
        ("Interested in", "out", "Villa 12")
    ]
    from_villa = (await c.get(f"/api/v1/links?record_id={villa['id']}", headers=h)).json()
    assert [(x["label"], x["direction"], x["other"]["name"]) for x in from_villa] == [
        ("Interested buyers", "in", "Rahul")
    ]
    record_timeline = (await c.get(f"/api/v1/records/{villa['id']}/activities", headers=h)).json()
    assert record_timeline[0]["summary"] == "Interested buyers: Rahul"
    lead_timeline = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=h)).json()
    assert lead_timeline[0]["summary"] == "Interested in: Villa 12"

    assert (await c.delete(f"/api/v1/links/{made.json()['id']}", headers=h)).status_code == 204
    assert (await c.get(f"/api/v1/links?lead_id={lead['id']}", headers=h)).json() == []
    async with tenant_session(tenant_id) as db:
        kinds = (await db.scalars(select(Event.type).where(Event.type.like("link.%")))).all()
    assert sorted(kinds) == ["link.created", "link.deleted"]


async def test_only_one_limits_and_wrong_kinds(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    _, sources = await setup_ids(c, h)
    _, lt = await _setup_links(
        c, h, label="Booked", inverse_label="Booked by", many_to=False, many_from=False
    )
    a = (await new_lead(c, h, sources["Website"], phone="98765 10001")).json()
    b = (await new_lead(c, h, sources["Website"], phone="98765 10002")).json()
    v1 = (await _record(c, h, name="Villa 1")).json()
    v2 = (await _record(c, h, name="Villa 2")).json()
    link = lambda lead, rec: c.post(  # noqa: E731
        "/api/v1/links",
        json={"link_type_id": lt["id"], "from_lead_id": lead, "to_record_id": rec},
        headers=h,
    )
    assert (await link(a["id"], v1["id"])).status_code == 201
    assert (await link(a["id"], v2["id"])).status_code == 409  # a lead books one villa
    assert (await link(b["id"], v1["id"])).status_code == 409  # a villa is booked once
    wrong = await c.post(
        "/api/v1/links",
        json={"link_type_id": lt["id"], "from_record_id": v1["id"], "to_lead_id": b["id"]},
        headers=h,
    )
    assert wrong.status_code == 422
    # Tightening a type that already has several links per side is refused.
    viewed = (
        await c.post(
            "/api/v1/link-types",
            json={
                "to_type_id": v1["record_type_id"],
                "label": "Viewed",
                "inverse_label": "Viewed by",
            },
            headers=h,
        )
    ).json()
    for rec in (v1, v2):
        await c.post(
            "/api/v1/links",
            json={"link_type_id": viewed["id"], "from_lead_id": a["id"], "to_record_id": rec["id"]},
            headers=h,
        )
    tighten = await c.patch(
        f"/api/v1/link-types/{viewed['id']}", json={"many_to": False}, headers=h
    )
    assert tighten.status_code == 409
    fine = await c.patch(f"/api/v1/link-types/{viewed['id']}", json={"many_from": False}, headers=h)
    assert fine.status_code == 200


async def test_linking_needs_sight_of_both_ends_and_edit_on_one(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    other_id, other = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin)
    rt, lt = await _setup_links(c, admin)
    # Properties: shared, view-only for sales users.
    access = (await c.get(f"/api/v1/record-types/{rt['id']}/access", headers=admin)).json()
    for a in access:
        if a["role_name"] == "Sales User":
            a.update(view=True, create=False, edit=False, delete=False, scope="all")
    await c.put(f"/api/v1/record-types/{rt['id']}/access", json=access, headers=admin)
    villa = (await _record(c, admin, name="Villa 7")).json()
    mine = (await new_lead(c, rep, sources["Website"], phone="98765 20001")).json()
    theirs = (await new_lead(c, other, sources["Website"], phone="98765 20002")).json()

    ok = await c.post(
        "/api/v1/links",
        json={"link_type_id": lt["id"], "from_lead_id": mine["id"], "to_record_id": villa["id"]},
        headers=rep,
    )
    assert ok.status_code == 201  # edit the lead, view the property
    hidden = await c.post(
        "/api/v1/links",
        json={"link_type_id": lt["id"], "from_lead_id": theirs["id"], "to_record_id": villa["id"]},
        headers=rep,
    )
    assert hidden.status_code == 404  # cannot see the other rep's lead
    await c.post(
        "/api/v1/links",
        json={"link_type_id": lt["id"], "from_lead_id": theirs["id"], "to_record_id": villa["id"]},
        headers=admin,
    )
    # From the villa, the rep sees only the buyer they may see.
    seen = (await c.get(f"/api/v1/links?record_id={villa['id']}", headers=rep)).json()
    assert [x["other"]["name"] for x in seen] == ["Rahul"] and len(seen) == 1
    assert seen[0]["other"]["id"] == mine["id"]


async def test_deleting_either_end_removes_the_link(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    _, sources = await setup_ids(c, h)
    _, lt = await _setup_links(c, h)
    lead = (await new_lead(c, h, sources["Website"])).json()
    villa = (await _record(c, h, name="Villa 9")).json()
    await c.post(
        "/api/v1/links",
        json={"link_type_id": lt["id"], "from_lead_id": lead["id"], "to_record_id": villa["id"]},
        headers=h,
    )
    assert (await c.delete(f"/api/v1/link-types/{lt['id']}", headers=h)).status_code == 409
    assert (await c.delete(f"/api/v1/leads/{lead['id']}", headers=h)).status_code == 204
    assert (await c.get(f"/api/v1/links?record_id={villa['id']}", headers=h)).json() == []
    async with tenant_session(tenant_id) as db:
        from app.modules.crm.models import Link

        assert await db.scalar(select(func.count()).select_from(Link)) == 0


async def test_records_and_links_never_cross_companies(client_for):
    a_id, a_slug = await make_workspace()
    b_id, b_slug = await make_workspace()
    a, b = client_for(a_slug), client_for(b_slug)
    _, ah = await login_as(a_id, "admin")
    _, bh = await login_as(b_id, "admin")
    rt, lt = await _setup_links(a, ah)
    villa = (await _record(a, ah, name="Villa A")).json()
    await _property_type(b, bh)  # same key in another company is fine
    for method, url in (
        ("GET", f"/api/v1/records/{villa['id']}"),
        ("GET", f"/api/v1/records/{villa['id']}/activities"),
        ("DELETE", f"/api/v1/records/{villa['id']}"),
        ("GET", f"/api/v1/links?record_id={villa['id']}"),
        ("GET", f"/api/v1/record-types/{rt['id']}/stages"),
        ("GET", f"/api/v1/record-types/{rt['id']}/access"),
        ("PATCH", f"/api/v1/link-types/{lt['id']}"),
    ):
        kwargs = {"json": {}} if method == "PATCH" else {}
        r = await b.request(method, url, headers=bh, **kwargs)
        assert r.status_code == 404, (method, url, r.status_code)
    assert (await b.get("/api/v1/records?type=property", headers=bh)).json()["total"] == 0


async def test_tasks_on_records(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    rt = await _property_type(c, h)
    access = (await c.get(f"/api/v1/record-types/{rt['id']}/access", headers=h)).json()
    for a in access:
        if a["role_name"] == "Sales User":
            a.update(view=True, create=False, edit=False, delete=False, scope="all")
    await c.put(f"/api/v1/record-types/{rt['id']}/access", json=access, headers=h)
    villa = (await _record(c, h, name="Villa 3")).json()
    body = {"title": "Get photos", "due_at": "2030-01-01T10:00:00Z", "record_id": villa["id"]}
    task = await c.post("/api/v1/tasks", json=body, headers=h)
    assert task.status_code == 201 and task.json()["record_name"] == "Villa 3"
    assert (await c.post("/api/v1/tasks", json=body, headers=rep)).status_code == 403  # view-only
    listed = (await c.get(f"/api/v1/tasks?record_id={villa['id']}", headers=h)).json()
    assert [t["title"] for t in listed] == ["Get photos"]
    done = await c.patch(f"/api/v1/tasks/{task.json()['id']}", json={"status": "done"}, headers=h)
    assert done.status_code == 200
    timeline = (await c.get(f"/api/v1/records/{villa['id']}/activities", headers=h)).json()
    assert timeline[0]["summary"] == "Done: Get photos"

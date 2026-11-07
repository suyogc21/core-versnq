"""CRM setup API: stages, sources, custom fields, activity types."""

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.audit.models import AuditLog
from tests.factories import login_as, make_workspace


async def _ids(c, h, path):
    return {
        x["name"] if "name" in x else x["key"]: x["id"]
        for x in (await c.get(path, headers=h)).json()
    }


async def test_everyone_reads_setup_only_configurers_change_it(ws, admin):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    ac, ah = admin

    assert (await c.get("/api/v1/lead-stages", headers=rep)).status_code == 200
    denied = await c.post("/api/v1/lead-stages", json={"name": "Hot"}, headers=rep)
    made = await ac.post(
        "/api/v1/lead-stages", json={"name": "Hot", "colour": "#ff0000"}, headers=ah
    )

    assert denied.status_code == 403 and made.status_code == 201
    async with tenant_session(tenant_id) as s:
        actions = (await s.scalars(select(AuditLog.action))).all()
    assert "crm.stage_created" in actions


async def test_stage_rules(admin):
    c, h = admin
    stages = await _ids(c, h, "/api/v1/lead-stages")

    unknown = await c.post(
        "/api/v1/lead-stages", json={"name": "X", "required_fields": ["nope"]}, headers=h
    )
    open_unqualified = await c.post(
        "/api/v1/lead-stages",
        json={"name": "Y", "is_open": True, "is_unqualified": True},
        headers=h,
    )
    builtin_required = await c.post(
        "/api/v1/lead-stages", json={"name": "Z", "required_fields": ["phone", "owner"]}, headers=h
    )
    invalid = stages["Invalid"]
    reopen_invalid = await c.patch(
        f"/api/v1/lead-stages/{invalid}", json={"is_open": True}, headers=h
    )
    rename_invalid = await c.patch(
        f"/api/v1/lead-stages/{invalid}", json={"name": "Junk"}, headers=h
    )
    delete_invalid = await c.delete(f"/api/v1/lead-stages/{invalid}", headers=h)
    duplicate = await c.post("/api/v1/lead-stages", json={"name": "New"}, headers=h)

    assert (unknown.status_code, open_unqualified.status_code) == (422, 422)
    assert builtin_required.status_code == 201
    assert builtin_required.json()["required_fields"] == ["owner", "phone"]
    assert (reopen_invalid.status_code, rename_invalid.status_code) == (409, 200)
    assert delete_invalid.status_code == 409 and duplicate.status_code == 409


async def test_at_least_one_open_stage_remains(admin):
    c, h = admin
    stages = (await c.get("/api/v1/lead-stages", headers=h)).json()
    open_ids = [s["id"] for s in stages if s["is_open"]]
    results = [
        (await c.patch(f"/api/v1/lead-stages/{i}", json={"is_open": False}, headers=h)).status_code
        for i in open_ids
    ]
    assert results[:-1] == [200] * (len(open_ids) - 1) and results[-1] == 409


async def test_reorder_needs_every_item(admin):
    c, h = admin
    ids = [s["id"] for s in (await c.get("/api/v1/lead-sources", headers=h)).json()]
    partial = await c.put("/api/v1/lead-sources/order", json={"ids": ids[:2]}, headers=h)
    full = await c.put("/api/v1/lead-sources/order", json={"ids": list(reversed(ids))}, headers=h)
    assert partial.status_code == 422
    assert [s["id"] for s in full.json()] == list(reversed(ids))


async def test_custom_field_rules(admin):
    c, h = admin
    post = lambda body: c.post("/api/v1/custom-fields", json=body, headers=h)  # noqa: E731
    parent = {
        "key": "product_line",
        "label": "Product line",
        "type": "select",
        "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
    }

    assert (await post({"key": "phone", "label": "P", "type": "text"})).status_code == 422
    assert (await post({"key": "x1", "label": "X", "type": "colour"})).status_code == 422
    assert (
        await post(
            {
                "key": "x2",
                "label": "X",
                "type": "select",
                "is_unique": True,
                "options": [{"value": "a", "label": "A"}],
            }
        )
    ).status_code == 422
    assert (
        await post({"key": "x3", "label": "X", "type": "select", "options": []})
    ).status_code == 422
    assert (await post(parent)).status_code == 201
    assert (await post(parent)).status_code == 409  # same key

    orphan = await post(
        {
            "key": "variant",
            "label": "Variant",
            "type": "select",
            "depends_on": "product_line",
            "options": [{"value": "v", "label": "V"}],
        }
    )
    wrong_parent = await post(
        {
            "key": "variant",
            "label": "Variant",
            "type": "select",
            "depends_on": "product_line",
            "options": [{"value": "v", "label": "V", "parent": "zzz"}],
        }
    )
    child = await post(
        {
            "key": "variant",
            "label": "Variant",
            "type": "select",
            "depends_on": "product_line",
            "options": [
                {"value": "v1", "label": "V1", "parent": "a"},
                {"value": "v2", "label": "V2", "parent": "b"},
            ],
        }
    )
    assert (orphan.status_code, wrong_parent.status_code, child.status_code) == (422, 422, 201)

    fields = {f["key"]: f["id"] for f in (await c.get("/api/v1/custom-fields", headers=h)).json()}
    # Removing parent option "b" would orphan V2.
    drop_b = await c.patch(
        f"/api/v1/custom-fields/{fields['product_line']}",
        json={"options": [{"value": "a", "label": "A"}]},
        headers=h,
    )
    delete_parent = await c.delete(f"/api/v1/custom-fields/{fields['product_line']}", headers=h)
    relabel = await c.patch(
        f"/api/v1/custom-fields/{fields['variant']}",
        json={"label": "Model", "key": "renamed"},
        headers=h,
    )
    assert (drop_b.status_code, delete_parent.status_code) == (422, 409)
    assert relabel.json()["label"] == "Model" and relabel.json()["key"] == "variant"


async def test_field_required_by_a_stage_cannot_be_deleted(admin):
    c, h = admin
    field = (
        await c.post(
            "/api/v1/custom-fields",
            json={"key": "ref_no", "label": "Ref", "type": "text", "is_unique": True},
            headers=h,
        )
    ).json()
    await c.post(
        "/api/v1/lead-stages",
        json={"name": "Booked", "is_open": False, "required_fields": ["ref_no"]},
        headers=h,
    )
    assert (await c.delete(f"/api/v1/custom-fields/{field['id']}", headers=h)).status_code == 409


async def test_activity_type_rules(admin):
    c, h = admin
    types = await _ids(c, h, "/api/v1/activity-types")
    made = await c.post(
        "/api/v1/activity-types",
        json={
            "key": "site_visit",
            "label": "Site visit done",
            "fields": [{"key": "feedback", "label": "Feedback", "type": "text"}],
        },
        headers=h,
    )
    bad_fields = await c.post(
        "/api/v1/activity-types",
        json={
            "key": "bad",
            "label": "Bad",
            "fields": [{"key": "Bad Key", "label": "x", "type": "text"}],
        },
        headers=h,
    )
    no_outcome = await c.patch(
        f"/api/v1/activity-types/{types['call']}", json={"fields": []}, headers=h
    )
    new_outcomes = await c.patch(
        f"/api/v1/activity-types/{types['call']}",
        json={
            "fields": [
                {
                    "key": "disposition",
                    "label": "Outcome",
                    "type": "select",
                    "required": True,
                    "options": [{"value": "booked", "label": "Booked a visit"}],
                }
            ]
        },
        headers=h,
    )
    switch_off_note = await c.patch(
        f"/api/v1/activity-types/{types['note']}", json={"is_active": False}, headers=h
    )
    delete_builtin = await c.delete(f"/api/v1/activity-types/{types['note']}", headers=h)
    delete_custom = await c.delete(f"/api/v1/activity-types/{made.json()['id']}", headers=h)

    assert (made.status_code, bad_fields.status_code) == (201, 422)
    assert (no_outcome.status_code, new_outcomes.status_code) == (422, 200)
    assert (switch_off_note.status_code, delete_builtin.status_code) == (409, 409)
    assert delete_custom.status_code == 204


async def test_other_companys_setup_is_invisible(admin, client_for):
    c, h = admin
    other_id, other_slug = await make_workspace()
    _, other_h = await login_as(other_id, "admin")
    other_stage = (await client_for(other_slug).get("/api/v1/lead-stages", headers=other_h)).json()[
        0
    ]

    response = await c.patch(
        f"/api/v1/lead-stages/{other_stage['id']}", json={"name": "Mine"}, headers=h
    )
    assert response.status_code == 404

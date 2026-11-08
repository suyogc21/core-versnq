"""Leads API: rules, visibility, permissions, custom fields, stages, delete."""

from sqlalchemy import select

from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.audit.models import AuditLog
from app.modules.crm.models import Activity, Lead, Task
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as, make_workspace


async def test_rep_adds_a_lead_that_is_theirs(ws):
    tenant_id, c = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, rep)

    made = await new_lead(
        c,
        rep,
        sources["Website"],
        phone="98765 43210",
        last_name="Kumar",
        identities=[
            {"type": "phone", "value": "98765 43210", "is_whatsapp": True},
            {"type": "email", "value": "Rahul@Example.COM"},
        ],
    )
    lead = made.json()

    assert made.status_code == 201
    assert lead["display_name"] == "Rahul Kumar" and lead["owner_user_id"] == str(rep_id)
    assert lead["primary_phone"] == "+919876543210" and lead["primary_email"] == "rahul@example.com"
    assert lead["origin"] == "outside" and lead["version"] == 1
    async with tenant_session(tenant_id) as s:
        types = (
            await s.scalars(select(Activity.type_key).where(Activity.lead_id == lead["id"]))
        ).all()
        events = (await s.scalars(select(Event.type))).all()
    assert types == ["lead_created"]
    assert {"lead.created", "lead.assigned"} <= set(events)


async def test_minimum_data_rules(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, rep)
    src = sources["Website"]

    no_identity = await c.post(
        "/api/v1/leads", json={"first_name": "A", "identities": [], "source_id": src}, headers=rep
    )
    bad_phone = await new_lead(c, rep, src, phone="123")
    org_no_name = await new_lead(c, rep, src, kind="organisation")
    name_optional = await c.post(
        "/api/v1/leads",
        json={"identities": [{"type": "email", "value": "x@y.com"}], "source_id": src},
        headers=rep,
    )

    assert (no_identity.status_code, bad_phone.status_code, org_no_name.status_code) == (
        422,
        422,
        422,
    )
    assert name_optional.status_code == 201 and name_optional.json()["display_name"] == "x@y.com"


async def test_visibility_own_team_all_and_unassigned(ws):
    tenant_id, c = ws
    a_id, rep_a = await login_as(tenant_id, "sales_user")
    b_id, rep_b = await login_as(tenant_id, "sales_user")
    m_id, mgr = await login_as(tenant_id, "sales_manager")
    m2_id, mgr2 = await login_as(tenant_id, "sales_manager")
    _, admin = await login_as(tenant_id, "admin")
    await make_team(tenant_id, m_id, [a_id])
    await make_team(tenant_id, m2_id, [b_id])
    _, sources = await setup_ids(c, admin)

    lead_a = (await new_lead(c, rep_a, sources["Website"])).json()["id"]
    unassigned = (
        await new_lead(c, mgr, sources["Website"], phone="98765 43211", assign_to_me=False)
    ).json()

    def ids(r):
        return {x["id"] for x in r.json()["items"]}

    assert (await c.get(f"/api/v1/leads/{lead_a}", headers=rep_b)).status_code == 404
    assert lead_a not in ids(await c.get("/api/v1/leads", headers=rep_b))
    assert lead_a in ids(await c.get("/api/v1/leads", headers=mgr))
    assert lead_a not in ids(await c.get("/api/v1/leads", headers=mgr2))
    assert lead_a in ids(await c.get("/api/v1/leads", headers=admin))
    assert unassigned["owner_user_id"] is None
    assert unassigned["id"] in ids(await c.get("/api/v1/leads?owner=unassigned", headers=mgr2))
    assert unassigned["id"] not in ids(await c.get("/api/v1/leads", headers=rep_a))


async def test_who_may_create_for_and_assign_to_whom(ws):
    tenant_id, c = ws
    a_id, rep_a = await login_as(tenant_id, "sales_user")
    b_id, _ = await login_as(tenant_id, "sales_user")
    outsider_id, _ = await login_as(tenant_id, "sales_user")
    m_id, mgr = await login_as(tenant_id, "sales_manager")
    await make_team(tenant_id, m_id, [a_id, b_id])
    _, sources = await setup_ids(c, mgr)

    for_someone_else = await new_lead(c, rep_a, sources["Website"], owner_user_id=str(b_id))
    lead = (await new_lead(c, rep_a, sources["Website"])).json()["id"]
    rep_assigns = await c.put(
        f"/api/v1/leads/{lead}/owner", json={"owner_user_id": str(b_id)}, headers=rep_a
    )
    to_outsider = await c.put(
        f"/api/v1/leads/{lead}/owner", json={"owner_user_id": str(outsider_id)}, headers=mgr
    )
    to_teammate = await c.put(
        f"/api/v1/leads/{lead}/owner", json={"owner_user_id": str(b_id)}, headers=mgr
    )

    assert (for_someone_else.status_code, rep_assigns.status_code) == (403, 403)
    assert to_outsider.status_code == 422 and to_teammate.status_code == 200
    assert to_teammate.json()["owner_user_id"] == str(b_id)
    assert (await c.get(f"/api/v1/leads/{lead}", headers=rep_a)).status_code == 404


async def test_linked_and_unique_custom_fields(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, sources = await setup_ids(c, admin)
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
    await c.post(
        "/api/v1/custom-fields",
        json={
            "key": "tier",
            "label": "Tier",
            "type": "select",
            "depends_on": "plan",
            "options": [
                {"value": "b1", "label": "B1", "parent": "basic"},
                {"value": "p1", "label": "P1", "parent": "pro"},
            ],
        },
        headers=admin,
    )
    await c.post(
        "/api/v1/custom-fields",
        json={"key": "ref_no", "label": "Reference", "type": "text", "is_unique": True},
        headers=admin,
    )
    src = sources["Website"]

    mismatch = await new_lead(c, admin, src, custom_fields={"plan": "basic", "tier": "p1"})
    child_without_parent = await new_lead(c, admin, src, custom_fields={"tier": "b1"})
    first = await new_lead(
        c, admin, src, custom_fields={"plan": "pro", "tier": "p1", "ref_no": "AB-1"}
    )
    clash = await new_lead(c, admin, src, phone="98765 43212", custom_fields={"ref_no": " ab-1 "})
    unknown = await new_lead(c, admin, src, phone="98765 43213", custom_fields={"nope": 1})

    assert (mismatch.status_code, child_without_parent.status_code) == (422, 422)
    assert first.status_code == 201 and first.json()["custom_fields"]["tier"] == "p1"
    assert clash.status_code == 409 and unknown.status_code == 422

    await c.delete(f"/api/v1/leads/{first.json()['id']}", headers=admin)
    reuse = await new_lead(c, admin, src, phone="98765 43213", custom_fields={"ref_no": "AB-1"})
    assert reuse.status_code == 201  # deleting the lead freed the value


async def test_stage_required_fields_and_unqualified_reason(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await c.post(
        "/api/v1/custom-fields",
        json={"key": "budget", "label": "Budget", "type": "number"},
        headers=admin,
    )
    stage = (
        await c.post(
            "/api/v1/lead-stages",
            json={"name": "Proposal", "required_fields": ["budget", "email"]},
            headers=admin,
        )
    ).json()
    stages, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"])).json()

    async def patch(body):
        r = await c.patch(
            f"/api/v1/leads/{lead['id']}", json={"version": lead["version"]} | body, headers=admin
        )
        if r.status_code == 200:
            lead.update(r.json())
        return r

    blocked = await patch({"stage_id": stage["id"]})
    ok = await patch(
        {
            "stage_id": stage["id"],
            "custom_fields": {"budget": "50000"},
            "identities": [
                {"type": "phone", "value": "98765 43210"},
                {"type": "email", "value": "r@x.com"},
            ],
        }
    )
    no_reason = await patch({"stage_id": stages["Invalid"]["id"]})
    with_reason = await patch({"stage_id": stages["Invalid"]["id"], "unqualified_reason": "Spam"})

    assert blocked.status_code == 422 and "Budget" in blocked.json()["detail"]
    assert "email" in blocked.json()["detail"]
    assert ok.status_code == 200 and ok.json()["custom_fields"]["budget"] == 50000
    assert no_reason.status_code == 422 and with_reason.status_code == 200
    assert with_reason.json()["is_open"] is False


async def test_stale_edit_is_refused(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, rep)
    lead = (await new_lead(c, rep, sources["Website"])).json()

    first = await c.patch(
        f"/api/v1/leads/{lead['id']}", json={"version": 1, "city": "Pune"}, headers=rep
    )
    stale = await c.patch(
        f"/api/v1/leads/{lead['id']}", json={"version": 1, "city": "Goa"}, headers=rep
    )
    assert first.status_code == 200 and first.json()["version"] == 2
    assert stale.status_code == 409


async def test_closing_a_lead_cancels_its_follow_up(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    stages, sources = await setup_ids(c, rep)
    lead = (
        await new_lead(c, rep, sources["Website"], next_follow_up_at="2030-01-01T10:00:00Z")
    ).json()
    assert lead["next_follow_up_at"]

    lost = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={
            "version": 1,
            "stage_id": stages["Lost"]["id"],
            "unqualified_reason": "Bought elsewhere",
        },
        headers=rep,
    )
    async with tenant_session(tenant_id) as s:
        statuses = (await s.scalars(select(Task.status).where(Task.lead_id == lead["id"]))).all()
    assert lost.json()["next_follow_up_at"] is None and statuses == ["cancelled"]


async def test_delete_is_permanent_admin_only_and_audited_without_personal_data(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, admin = await login_as(tenant_id, "admin")
    _, sources = await setup_ids(c, admin)
    lead_id = (await new_lead(c, rep, sources["Website"])).json()["id"]

    rep_tries = await c.delete(f"/api/v1/leads/{lead_id}", headers=rep)
    admin_deletes = await c.delete(f"/api/v1/leads/{lead_id}", headers=admin)

    assert (rep_tries.status_code, admin_deletes.status_code) == (403, 204)
    async with tenant_session(tenant_id) as s:
        assert await s.get(Lead, lead_id) is None
        assert (await s.scalars(select(Activity).where(Activity.lead_id == lead_id))).all() == []
        row = await s.scalar(select(AuditLog).where(AuditLog.action == "lead.deleted"))
    assert str(row.entity_id) == lead_id and row.before is None and row.after is None


async def test_search_and_filters(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, rep)
    await new_lead(c, rep, sources["Website"], first_name="Ananya", phone="99887 76655")
    await new_lead(
        c,
        rep,
        sources["Referral"],
        first_name="Bhavesh",
        phone="91234 56789",
        next_follow_up_at="2020-01-01T10:00:00Z",
    )

    def names(r):
        return [x["display_name"] for x in r.json()["items"]]

    assert names(await c.get("/api/v1/leads?q=anan", headers=rep)) == ["Ananya"]
    assert names(await c.get("/api/v1/leads?q=7665", headers=rep)) == ["Ananya"]
    assert names(await c.get(f"/api/v1/leads?source_id={sources['Referral']}", headers=rep)) == [
        "Bhavesh"
    ]
    overdue = await c.get("/api/v1/leads?follow_up=overdue", headers=rep)
    assert names(overdue) == ["Bhavesh"] and overdue.json()["total"] == 1


async def test_other_companys_lead_is_invisible(ws, client_for):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)
    _, other_sources = await setup_ids(oc, other_admin)
    theirs = (await new_lead(oc, other_admin, other_sources["Website"])).json()["id"]

    assert (await c.get(f"/api/v1/leads/{theirs}", headers=admin)).status_code == 404
    assert (await c.delete(f"/api/v1/leads/{theirs}", headers=admin)).status_code == 404
    _, sources = await setup_ids(c, admin)
    their_source = await new_lead(c, admin, other_sources["Website"])
    assert their_source.status_code == 422
    assert sources  # our own setup is untouched

"""Step 1: web forms / webhooks posting leads to /api/v1/capture/<key>."""

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.crm.models import Activity, Lead
from tests.crm.intake_helpers import notifications, rule
from tests.factories import login_as, make_workspace


async def _form(c, h, **extra):
    sources = {s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources", headers=h)).json()}
    r = await c.post(
        "/api/v1/capture-sources",
        json={"name": "Contact us", "source_id": sources["Website"], **extra},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _leads(tenant_id):
    async with tenant_session(tenant_id) as db:
        return list((await db.scalars(select(Lead).order_by(Lead.created_at))).all())


async def test_a_website_posts_json_and_the_lead_is_routed(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep, _ = await login_as(tenant_id, "sales_user")
    await rule(tenant_id, strategy="user", user_ids=[rep])
    form = await _form(c, admin, consent_text="I agree to be contacted")
    assert form["key"].startswith("vqf_") and form["key_hint"] == form["key"][:8]

    r = await c.post(
        f"/api/v1/capture/{form['key']}",
        json={
            "name": "Rahul Mehta",
            "email": "rahul@example.org",
            "mobile": "098765 43210",
            "message": "Do you have weekend batches?",
            "utm_source": "google",
            "consent_email": "yes",
            "gclid": "abc123",
            "How did you hear about us": "A friend",
        },
        headers={"Origin": "https://www.client-site.com", "User-Agent": "Mozilla/5.0"},
    )
    assert r.status_code == 202 and r.json() == {"ok": True}
    assert r.headers["access-control-allow-origin"] == "*"

    (lead,) = await _leads(tenant_id)
    assert (lead.first_name, lead.last_name, lead.primary_phone) == (
        "Rahul",
        "Mehta",
        "+919876543210",
    )
    assert (lead.created_via, lead.origin, lead.owner_user_id) == ("form", "inbound", rep)
    assert lead.utm_source == "google" and lead.attribution == {"gclid": "abc123"}
    assert lead.email_consent == "opted_in"
    async with tenant_session(tenant_id) as db:
        created = await db.scalar(
            select(Activity).where(Activity.lead_id == lead.id, Activity.type_key == "lead_created")
        )
    assert created.summary == "Added via the Contact us form"
    assert (
        "weekend batches" in created.body and "How did you hear about us: A friend" in created.body
    )
    assert [k for k, _ in await notifications(tenant_id, rep)] == ["lead_assigned"]


async def test_a_plain_html_form_post_works_and_a_repeat_updates(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    form = await _form(c, admin)
    body = "first_name=Asha&phone=9876500011&city=Pune"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    assert (
        await c.post(f"/api/v1/capture/{form['key']}", content=body, headers=headers)
    ).status_code == 202
    again = "first_name=Someone&phone=%2B919876500011&last_name=Rao"
    assert (
        await c.post(f"/api/v1/capture/{form['key']}", content=again, headers=headers)
    ).status_code == 202
    (lead,) = await _leads(tenant_id)
    assert (lead.first_name, lead.last_name, lead.city) == ("Asha", "Rao", "Pune")


async def test_bad_keys_spam_and_bad_data(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    form = await _form(c, admin)
    url = f"/api/v1/capture/{form['key']}"
    assert (
        await c.post("/api/v1/capture/vqf_wrong", json={"phone": "9876500012"})
    ).status_code == 404
    spam = await c.post(url, json={"phone": "9876500013", "_gotcha": "http://spam"})
    assert spam.status_code == 202
    no_contact = await c.post(url, json={"name": "Nobody"})
    assert no_contact.status_code == 422
    bad_phone = await c.post(url, json={"phone": "12"})
    assert bad_phone.status_code == 422 and "phone" in bad_phone.json()["detail"]
    assert await _leads(tenant_id) == []


async def test_another_companys_key_does_not_work_here(ws, client_for):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    form = await _form(c, admin)
    _, other_slug = await make_workspace()
    other = client_for(other_slug)
    assert (
        await other.post(f"/api/v1/capture/{form['key']}", json={"phone": "9876500014"})
    ).status_code == 404


async def test_switched_off_and_rotated_keys_stop_working(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    form = await _form(c, admin)
    old = form["key"]
    rotated = (await c.post(f"/api/v1/capture-sources/{form['id']}/new-key", headers=admin)).json()
    assert (await c.post(f"/api/v1/capture/{old}", json={"phone": "9876500015"})).status_code == 404
    new = rotated["key"]
    assert (await c.post(f"/api/v1/capture/{new}", json={"phone": "9876500015"})).status_code == 202
    await c.patch(f"/api/v1/capture-sources/{form['id']}", json={"is_active": False}, headers=admin)
    assert (await c.post(f"/api/v1/capture/{new}", json={"phone": "9876500016"})).status_code == 404
    listed = (await c.get("/api/v1/capture-sources", headers=admin)).json()
    assert "key" not in listed[0] and listed[0]["last_used_at"] is not None


async def test_rate_limit_per_visitor(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    form = await _form(c, admin)
    codes = [
        (
            await c.post(f"/api/v1/capture/{form['key']}", json={"phone": f"98765{i:05d}"})
        ).status_code
        for i in range(21)
    ]
    assert codes[:20] == [202] * 20 and codes[20] == 429


async def test_custom_fields_by_label_and_answers_that_dont_fit_are_kept(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await c.post(
        "/api/v1/custom-fields",
        json={
            "key": "course",
            "label": "Course",
            "type": "select",
            "options": [{"value": "ds", "label": "Data Science"}],
            "required": True,
        },
        headers=admin,
    )
    form = await _form(c, admin, field_map={"Which course?": "cf.course"})
    url = f"/api/v1/capture/{form['key']}"
    assert (
        await c.post(url, json={"phone": "9876500021", "Which course?": "data science"})
    ).status_code == 202
    assert (
        await c.post(url, json={"phone": "9876500022", "Which course?": "Cooking"})
    ).status_code == 202
    assert (
        await c.post(url, json={"phone": "9876500023"})
    ).status_code == 202  # required, still kept
    leads = await _leads(tenant_id)
    assert [x.custom_fields.get("course") for x in leads] == ["ds", None, None]
    async with tenant_session(tenant_id) as db:
        body = await db.scalar(
            select(Activity.body).where(
                Activity.lead_id == leads[1].id, Activity.type_key == "lead_created"
            )
        )
    assert body == "Course: Cooking"


async def test_capture_settings_need_permission_and_valid_targets(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, mgr = await login_as(tenant_id, "sales_manager")
    sources = {
        s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources", headers=admin)).json()
    }
    body = {"name": "x", "source_id": sources["Website"]}
    assert (await c.post("/api/v1/capture-sources", json=body, headers=mgr)).status_code == 403
    bad = body | {"field_map": {"a": "cf.nope"}}
    assert (await c.post("/api/v1/capture-sources", json=bad, headers=admin)).status_code == 422
    stages = {
        s["name"]: s["id"] for s in (await c.get("/api/v1/lead-stages", headers=admin)).json()
    }
    closed = body | {"stage_id": stages["Lost"]}
    assert (await c.post("/api/v1/capture-sources", json=closed, headers=admin)).status_code == 422

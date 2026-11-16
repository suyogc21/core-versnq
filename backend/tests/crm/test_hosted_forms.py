"""Real forms (docs/plans/forms-plan.md): the builder and the hosted page /f/<public_id>.
Required answers checked, the lead made through the usual path (source, stage, consent,
duplicates), a switched-off form is closed, another company's id shows nothing, the spam trap
and rate limit work, and a form must ask for a way to reach the person."""

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead
from tests.factories import login_as, make_workspace

FORM = {
    "title": "Book a free demo",
    "intro": "Tell us a little about you.",
    "button": "Book my demo",
    "fields": [
        {"target": "full_name", "label": "Your name", "required": True},
        {"target": "phone", "label": "Mobile", "required": True},
        {"target": "email", "label": "Email", "required": False},
        {"target": "cf.course", "label": "Which course?", "required": True},
    ],
    "ask_consent": ["whatsapp"],
    "thank_you": "Thanks! We'll call you today.",
}


async def _setup(c, h, **extra):
    await c.post("/api/v1/custom-fields", json={
        "key": "course", "label": "Course", "type": "select",
        "options": [{"value": "ds", "label": "Data Science"}, {"value": "ux", "label": "UX"}],
    }, headers=h)  # fmt: skip
    sources = {s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources", headers=h)).json()}
    r = await c.post("/api/v1/capture-sources", json={
        "name": "Demo page", "source_id": sources["Website"], "form": FORM, "hosted": True,
        "consent_text": "You may message me on WhatsApp", **extra,
    }, headers=h)  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def _leads(tenant_id):
    async with tenant_session(tenant_id) as db:
        return list((await db.scalars(select(Lead).order_by(Lead.created_at))).all())


async def test_the_hosted_form_shows_its_questions_and_makes_the_lead(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    src = await _setup(c, admin)
    pid = src["public_id"]

    page = (await c.get(f"/api/v1/forms/{pid}")).json()
    sent = await c.post(f"/api/v1/forms/{pid}", json={
        "full_name": "Asha Rao", "phone": "98765 11122", "course": "Data Science",
        "consent_whatsapp": "on", "utm_source": "instagram", "sneaky": "ignored",
    })  # fmt: skip

    assert pid and len(pid) >= 10 and not page["closed"]
    assert page["title"] == "Book a free demo" and page["button"] == "Book my demo"
    assert [(f["name"], f["input"], f["required"]) for f in page["fields"]] == [
        ("full_name", "text", True), ("phone", "tel", True), ("email", "email", False),
        ("course", "select", True),
    ]  # fmt: skip
    assert page["fields"][3]["options"] == ["Data Science", "UX"]
    assert page["ask_consent"] == ["whatsapp"] and page["company"]["name"]
    assert sent.status_code == 201, sent.text
    assert sent.json() == {"ok": True, "thank_you": "Thanks! We'll call you today.",
                           "redirect_url": None}  # fmt: skip
    (lead,) = await _leads(tenant_id)
    assert (lead.first_name, lead.primary_phone) == ("Asha", "+919876511122")
    assert lead.custom_fields.get("course") == "ds" and lead.utm_source == "instagram"
    assert lead.whatsapp_consent == "opted_in" and lead.created_via == "form"


async def test_required_answers_options_and_a_way_to_reach_them(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    pid = (await _setup(c, admin))["public_id"]

    empty = await c.post(f"/api/v1/forms/{pid}", json={})
    wrong = {"full_name": "A", "phone": "9876500001", "email": "not-an-email", "course": "Cooking"}
    bad = await c.post(f"/api/v1/forms/{pid}", json=wrong)
    sources = {s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources",
                                                        headers=admin)).json()}  # fmt: skip
    no_contact = await c.post("/api/v1/capture-sources", json={
        "name": "No contact", "source_id": sources["Website"],
        "form": {**FORM, "fields": [{"target": "full_name", "label": "Name"}]},
    }, headers=admin)  # fmt: skip
    utm_question = await c.post("/api/v1/capture-sources", json={
        "name": "UTM", "source_id": sources["Website"],
        "form": {**FORM, "fields": [*FORM["fields"], {"target": "utm_source", "label": "x"}]},
    }, headers=admin)  # fmt: skip
    bare = {"name": "Bare", "source_id": sources["Website"], "hosted": True}
    page_without_form = await c.post("/api/v1/capture-sources", json=bare, headers=admin)

    assert empty.status_code == 422 and empty.json()["code"] == "form_invalid"
    assert set(empty.json()["fields"]) == {"full_name", "phone", "course"}
    assert bad.json()["fields"] == {"email": "Enter a valid email",
                                    "course": "Choose one of the options"}  # fmt: skip
    assert no_contact.status_code == 422 and utm_question.status_code == 422
    assert page_without_form.status_code == 422
    assert await _leads(tenant_id) == []


async def test_closed_hidden_other_company_spam_and_repeat(ws, client_for):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    src = await _setup(c, admin)
    pid = src["public_id"]
    other_id, other_slug = await make_workspace()
    good = {"full_name": "Ravi K", "phone": "9876500099", "course": "UX"}

    spam = await c.post(f"/api/v1/forms/{pid}", json={**good, "_gotcha": "bot"})
    elsewhere = await client_for(other_slug).get(f"/api/v1/forms/{pid}")
    first = await c.post(f"/api/v1/forms/{pid}", json=good)
    again = await c.post(f"/api/v1/forms/{pid}", json={**good, "email": "ravi@example.org"})
    await c.patch(f"/api/v1/capture-sources/{src['id']}", json={"is_active": False},
                  headers=admin)  # fmt: skip
    closed_page = (await c.get(f"/api/v1/forms/{pid}")).json()
    closed_send = await c.post(f"/api/v1/forms/{pid}", json=good)
    await c.patch(f"/api/v1/capture-sources/{src['id']}", json={"is_active": True,
                  "hosted": False}, headers=admin)  # fmt: skip
    page_off = await c.get(f"/api/v1/forms/{pid}")

    assert spam.status_code == 201 and elsewhere.status_code == 404
    assert first.status_code == 201 and again.status_code == 201
    (lead,) = await _leads(tenant_id)  # the repeat updated the same person
    assert lead.primary_email == "ravi@example.org"
    assert closed_page["closed"] is True and closed_page["fields"] == []
    assert closed_send.status_code == 422 and closed_send.json()["code"] == "form_closed"
    assert page_off.status_code == 404


async def test_rate_limit_per_visitor(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    pid = (await _setup(c, admin))["public_id"]
    codes = [(await c.post(f"/api/v1/forms/{pid}", json={})).status_code for _ in range(21)]
    assert codes[:20] == [422] * 20 and codes[20] == 422
    last = await c.post(f"/api/v1/forms/{pid}", json={})
    assert last.json()["code"] == "rate_limited"

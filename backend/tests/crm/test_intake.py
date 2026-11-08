"""Step 1: the shared intake path — duplicates, retries, races, consent, organisations."""

import asyncio

from sqlalchemy import func, select

from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead, LeadIdentity, LeadStage, Suppression
from tests.crm.helpers import new_lead, setup_ids
from tests.crm.intake_helpers import activities, capture, lead, notifications, settings
from tests.factories import login_as


# ---------- duplicates on automatic paths ----------
async def test_same_phone_in_another_format_updates_the_existing_lead(ws):
    tenant_id, _ = ws
    owner_id, _ = await login_as(tenant_id, "sales_user")
    result, first = await capture(
        tenant_id,
        phone="98765 43210",
        owner=owner_id,
        fields={"first_name": "Rahul", "city": "Pune"},
    )
    assert result == "created"

    result, again = await capture(
        tenant_id,
        phone="+91 9876543210",
        email="rahul@example.org",
        fields={"first_name": "Someone Else", "last_name": "Mehta", "city": "Mumbai"},
        message="Still interested?",
    )
    assert (result, again) == ("updated", first)
    found = await lead(tenant_id, first)
    # Blanks filled, nothing the team had is overwritten, the owner is kept.
    assert (found.first_name, found.last_name, found.city) == ("Rahul", "Mehta", "Pune")
    assert found.owner_user_id == owner_id and found.primary_email == "rahul@example.org"
    assert found.primary_phone == "+919876543210" and found.version == 2
    assert (await activities(tenant_id, first))[-1] == "re_enquiry"
    assert ("re_enquiry", "Rahul Mehta enquired again") in await notifications(tenant_id, owner_id)


async def test_a_closed_lead_that_enquires_again_is_reopened(ws):
    tenant_id, _ = ws
    _, first = await capture(tenant_id, email="asha@example.org")
    async with tenant_session(tenant_id) as db:
        lost = await db.scalar(select(LeadStage).where(LeadStage.name == "Lost"))
        row = await db.get(Lead, first)
        row.stage_id, row.is_open = lost.id, False
    await capture(tenant_id, email="ASHA@example.org ")
    found = await lead(tenant_id, first)
    assert found.is_open
    assert "stage_changed" in await activities(tenant_id, first)


async def test_flag_and_create_policies(ws):
    tenant_id, _ = ws
    _, first = await capture(tenant_id, phone="98765 00001")
    result, flagged = await capture(tenant_id, phone="98765 00001", policy="flag")
    assert result == "flagged" and flagged != first
    assert (await lead(tenant_id, flagged)).possible_duplicate_of_id == first
    result, separate = await capture(tenant_id, phone="98765 00001", policy="create")
    assert result == "created" and separate not in (first, flagged)
    assert (await capture(tenant_id, phone="98765 00001", policy="skip"))[0] == "skipped"


async def test_external_id_makes_a_retried_post_safe(ws):
    tenant_id, _ = ws
    ref = ("website", "order-77")
    _, first = await capture(tenant_id, phone="98765 00002", external=ref)
    result, again = await capture(tenant_id, phone="98765 00003", external=ref)
    assert (result, again) == ("updated", first)


async def test_two_arrivals_at_the_same_moment_create_one_lead(ws):
    tenant_id, _ = ws
    results = await asyncio.gather(*[capture(tenant_id, phone="98765 00004") for _ in range(5)])
    assert sorted(r for r, _ in results) == ["created"] + ["updated"] * 4
    async with tenant_session(tenant_id) as db:
        count = await db.scalar(
            select(func.count())
            .select_from(LeadIdentity)
            .where(LeadIdentity.value_normalized == "+919876500004")
        )
    assert count == 1


# ---------- duplicates on quick-add ----------
async def test_quick_add_refuses_a_duplicate_and_says_which(admin):
    c, h = admin
    _, sources = await setup_ids(c, h)
    first = await new_lead(c, h, sources["Website"], phone="98765 11111")
    again = await new_lead(c, h, sources["Website"], phone="+91 98765-11111")
    assert again.status_code == 409
    assert again.json()["duplicate"]["id"] == first.json()["id"]


async def test_quick_add_does_not_reveal_someone_elses_lead(ws):
    tenant_id, c = ws
    _, admin_h = await login_as(tenant_id, "admin")
    _, rep_h = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin_h)
    await new_lead(c, admin_h, sources["Website"], phone="98765 22222")
    again = await new_lead(c, rep_h, sources["Website"], phone="98765 22222")
    assert again.status_code == 409
    assert again.json()["duplicate"] is None
    assert "belongs to someone else" in again.json()["detail"]


async def test_quick_add_keeps_duplicates_when_the_company_says_so(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    _, sources = await setup_ids(c, h)
    first = await new_lead(c, h, sources["Website"], phone="98765 33333")
    await settings(tenant_id, duplicate_policy="flag")
    flagged = await new_lead(c, h, sources["Website"], phone="98765 33333")
    assert flagged.status_code == 201
    assert (await lead(tenant_id, flagged.json()["id"])).possible_duplicate_of_id is not None
    assert first.json()["id"] != flagged.json()["id"]


# ---------- consent and suppression ----------
async def test_opt_out_survives_later_imports_and_deletion(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    _, first = await capture(
        tenant_id, email="neha@example.org", consents={"email": "opted_in"}, consent_wording="Yes"
    )
    assert (await lead(tenant_id, first)).email_consent == "opted_in"

    r = await c.post(
        f"/api/v1/leads/{first}/consents",
        json={"channel": "email", "status": "opted_out"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["email_consent"] == "opted_out"

    await capture(tenant_id, email="neha@example.org", consents={"email": "opted_in"})
    assert (await lead(tenant_id, first)).email_consent == "opted_out"

    assert (await c.delete(f"/api/v1/leads/{first}", headers=h)).status_code == 204
    async with tenant_session(tenant_id) as db:
        kept = await db.scalar(
            select(Suppression.reason).where(Suppression.value_normalized == "neha@example.org")
        )
    assert kept == "opt_out"
    _, new_id = await capture(tenant_id, email="neha@example.org", consents={"email": "opted_in"})
    assert (await lead(tenant_id, new_id)).email_consent is None  # the opt-in was refused


async def test_a_person_can_record_a_fresh_opt_in_with_a_note(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "sales_manager")
    _, lead_id = await capture(tenant_id, email="ravi@example.org")
    url = f"/api/v1/leads/{lead_id}/consents"
    await c.post(url, json={"channel": "email", "status": "opted_out"}, headers=h)
    no_note = await c.post(url, json={"channel": "email", "status": "opted_in"}, headers=h)
    assert no_note.status_code == 422
    ok = await c.post(
        url,
        json={"channel": "email", "status": "opted_in", "wording": "Asked again on the phone"},
        headers=h,
    )
    assert ok.json()["email_consent"] == "opted_in"
    history = (await c.get(url, headers=h)).json()
    assert [x["status"] for x in history] == ["opted_in", "opted_out"]  # newest first
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(func.count()).select_from(Suppression)) == 0


async def test_consent_endpoints_respect_visibility(ws):
    tenant_id, c = ws
    _, rep_h = await login_as(tenant_id, "sales_user")
    _, lead_id = await capture(tenant_id, email="hidden@example.org")
    r = await c.get(f"/api/v1/leads/{lead_id}/consents", headers=rep_h)
    assert r.status_code == 404


# ---------- organisations (#14) ----------
async def _org(tenant_id, name, email=None, website=None):
    _, org_id = await capture(
        tenant_id,
        email=email or f"info@{name.lower().replace(' ', '')}.com",
        kind="organisation",
        fields={"org_name": name, "website": website},
    )
    return org_id


async def test_suggestions_by_domain_and_by_name(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    acme = await _org(tenant_id, "Acme Pvt Ltd", website="https://www.acme.com")
    await _org(tenant_id, "Globex")
    _, rahul = await capture(tenant_id, email="rahul@acme.com")
    _, priya = await capture(tenant_id, email="priya@gmail.com", fields={"org_name": "acme ltd."})
    _, free = await capture(tenant_id, email="sam@gmail.com")

    url = "/api/v1/leads/{}/organisation-suggestions"
    assert (await c.get(url.format(rahul), headers=h)).json() == []  # off by default

    await settings(tenant_id, org_grouping="suggest")
    by_domain = (await c.get(url.format(rahul), headers=h)).json()
    assert [(s["id"], s["reason"]) for s in by_domain] == [(str(acme), "domain")]
    by_name = (await c.get(url.format(priya), headers=h)).json()
    assert [(s["id"], s["reason"]) for s in by_name] == [(str(acme), "name")]
    assert (await c.get(url.format(free), headers=h)).json() == []

    dismissed = await c.post(
        f"/api/v1/leads/{priya}/organisation-suggestions/{acme}/dismiss", headers=h
    )
    assert dismissed.status_code == 204
    assert (await c.get(url.format(priya), headers=h)).json() == []

    linked = await c.put(
        f"/api/v1/leads/{rahul}/organisation", json={"organisation_id": str(acme)}, headers=h
    )
    assert linked.status_code == 200 and linked.json()["organisation_id"] == str(acme)
    people = (await c.get(f"/api/v1/leads/{acme}/people", headers=h)).json()
    assert [p["id"] for p in people] == [str(rahul)]


async def test_auto_link_on_capture_only_for_a_single_domain_match(ws):
    tenant_id, _ = ws
    await settings(tenant_id, org_grouping="auto")
    acme = await _org(tenant_id, "Acme", email="hello@acme.com")
    _, rahul = await capture(tenant_id, email="rahul@acme.com")
    assert (await lead(tenant_id, rahul)).organisation_id == acme
    assert "organisation_linked" in await activities(tenant_id, rahul)
    _, by_name = await capture(tenant_id, email="x@gmail.com", fields={"org_name": "Acme"})
    assert (await lead(tenant_id, by_name)).organisation_id is None  # names only suggest

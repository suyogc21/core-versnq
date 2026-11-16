"""Batch 5d: lead ads. A Facebook Page or a Google Ads lead form is connected in Settings → Lead
ads; Meta's one-time check needs the company's verify token; Meta's lead notices are refused
without the app secret's signature; the lead's answers are read (a fake Graph API here) and go
through the normal intake; a repeat is ignored; a failed read is retried by the worker; Google's
leads need the company's own key; another company can't use them."""

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.crm.models import Activity, Lead, LeadSource
from app.modules.leadads import service as S
from app.modules.leadads.models import LeadAdLead
from tests.factories import login_as, make_workspace

SECRET = "versnq-meta-app-secret-1"
PAGE = "1234567890"
ANSWERS = {
    "id": "LG1",
    "form_id": "F9",
    "ad_id": "AD7",
    "campaign_id": "C3",
    "field_data": [
        {"name": "full_name", "values": ["Neha Kapoor"]},
        {"name": "email", "values": ["neha@example.com"]},
        {"name": "phone_number", "values": ["+91 98111 22334"]},
        {"name": "which_course_are_you_interested_in?", "values": ["Data science"]},
    ],
}


@pytest.fixture
def meta(monkeypatch):
    monkeypatch.setattr(get_settings(), "meta_leads_app_secret", SECRET)
    calls: list[str] = []

    async def lead(self, leadgen_id):
        calls.append(leadgen_id)
        if leadgen_id == "BROKEN":
            raise RuntimeError("Meta said: temporarily unavailable")
        return {**ANSWERS, "id": leadgen_id}

    monkeypatch.setattr(S.TestGraph, "lead", lead)
    return calls


def _notice(leadgen_id: str, page: str = PAGE) -> bytes:
    return json.dumps(
        {
            "object": "page",
            "entry": [
                {
                    "id": page,
                    "changes": [
                        {
                            "field": "leadgen",
                            "value": {
                                "leadgen_id": leadgen_id,
                                "page_id": page,
                                "form_id": "F9",
                                "ad_id": "AD7",
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()


def _signed(raw: bytes, secret: str = SECRET) -> dict:
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"}


async def _facebook(c, admin):
    body = {
        "provider": "facebook",
        "name": "Main page",
        "page_id": PAGE,
        "page_token": "page-token-" + "x" * 20,
    }
    r = await c.post("/api/v1/lead-ads/sources", json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


async def test_connecting_a_page_needs_permission_and_a_good_token(ws, meta):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    body = {"provider": "facebook", "name": "P", "page_id": PAGE, "page_token": "wrong-token"}

    by_rep = await c.post("/api/v1/lead-ads/sources", json=body, headers=rep)
    wrong = await c.post(
        "/api/v1/lead-ads/sources",
        json={**body, "page_token": "wrong-token" + "x" * 10},
        headers=admin,
    )
    ok = await _facebook(c, admin)
    again = await c.post(
        "/api/v1/lead-ads/sources",
        headers=admin,
        json={**body, "page_token": "another-token-" + "y" * 10},
    )

    assert by_rep.status_code == 403
    assert wrong.status_code == 422 and wrong.json()["code"] == "lead_ads_failed"
    assert ok["verify_token"] and ok["webhook_url"].endswith("/api/v1/lead-ads/facebook/webhook")
    assert "page-token-" not in json.dumps(ok)  # the token is never shown back
    assert again.status_code == 422  # the same Page twice


async def test_meta_check_and_signed_notices_make_one_lead(ws, meta):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    src = await _facebook(c, admin)
    url = "/api/v1/lead-ads/facebook/webhook"

    check = await c.get(
        url,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": src["verify_token"],
            "hub.challenge": "abc123",
        },
    )
    bad_check = await c.get(
        url, params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "abc123"}
    )
    raw = _notice("LG1")
    forged = await c.post(url, content=raw, headers=_signed(raw, "not-the-secret"))
    first = await c.post(url, content=raw, headers=_signed(raw))
    repeat = await c.post(url, content=raw, headers=_signed(raw))

    assert check.text == "abc123" and bad_check.status_code == 404
    assert forged.status_code == 403
    assert first.json() == {"accepted": 1} and repeat.json() == {"accepted": 0}
    assert meta == ["LG1"]  # read from Meta once
    async with tenant_session(tenant_id) as db:
        row = await db.scalar(select(LeadAdLead).where(LeadAdLead.provider_lead_id == "LG1"))
        lead = await db.get(Lead, row.lead_id)
        source = await db.get(LeadSource, lead.source_id)
        note = await db.scalar(
            select(Activity.body).where(Activity.lead_id == lead.id, Activity.body.is_not(None))
        )
    assert row.status == "done" and source.name == "Facebook ads"
    assert (lead.display_name, lead.primary_email) == ("Neha Kapoor", "neha@example.com")
    assert lead.primary_phone == "+919811122334"
    assert (
        lead.attribution.get("campaign_id") == "C3"
        and lead.attribution.get("ad_network") == "facebook"
    )
    assert "Data science" in (note or "")


async def test_a_failed_read_is_retried_by_the_worker(ws, meta, monkeypatch):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await _facebook(c, admin)
    raw = _notice("BROKEN")
    r = await c.post("/api/v1/lead-ads/facebook/webhook", content=raw, headers=_signed(raw))
    async with tenant_session(tenant_id) as db:
        row = await db.scalar(select(LeadAdLead).where(LeadAdLead.provider_lead_id == "BROKEN"))
        assert (row.status, row.tries) == ("pending", 1) and "unavailable" in row.error

    async def works(self, leadgen_id):
        return {**ANSWERS, "id": leadgen_id}

    monkeypatch.setattr(S.TestGraph, "lead", works)
    async with tenant_session(tenant_id) as db:
        assert await S.retry_pending(db) == 1
    async with tenant_session(tenant_id) as db:
        row = await db.scalar(select(LeadAdLead).where(LeadAdLead.provider_lead_id == "BROKEN"))
    assert r.json() == {"accepted": 1} and row.status == "done" and row.lead_id


async def test_google_leads_need_the_company_key_and_count_once(ws, client_for):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    created = await c.post(
        "/api/v1/lead-ads/sources",
        headers=admin,
        json={"provider": "google", "name": "Search campaign"},
    )
    key = created.json()["google_key"]
    listed = (await c.get("/api/v1/lead-ads/sources", headers=admin)).json()
    lead = {
        "lead_id": "G-1",
        "google_key": key,
        "campaign_id": 55,
        "user_column_data": [
            {"column_id": "FULL_NAME", "string_value": "Arjun Rao"},
            {"column_id": "EMAIL", "string_value": "arjun@example.com"},
            {"column_id": "PHONE_NUMBER", "string_value": "+919822233344"},
            {"column_name": "Budget", "string_value": "5 lakh"},
        ],
    }
    url = "/api/v1/lead-ads/google/webhook"
    wrong = await c.post(url, json={**lead, "google_key": "guess"})
    ok = await c.post(url, json=lead)
    repeat = await c.post(url, json=lead)
    other_id, other_slug = await make_workspace()
    elsewhere = await client_for(other_slug).post(url, json={**lead, "lead_id": "G-2"})

    assert created.status_code == 201 and key and "google_key" not in listed[0]
    assert wrong.status_code == 403 and elsewhere.status_code == 403
    assert ok.json() == {"accepted": 1} and repeat.json() == {"accepted": 0}
    async with tenant_session(tenant_id) as db:
        n = await db.scalar(
            select(func.count()).select_from(Lead).where(Lead.primary_email == "arjun@example.com")
        )
        row = await db.scalar(select(LeadAdLead).where(LeadAdLead.provider_lead_id == "G-1"))
        lead_row = await db.get(Lead, row.lead_id)
        source = await db.get(LeadSource, lead_row.source_id)
    assert n == 1 and lead_row.display_name == "Arjun Rao" and source.name == "Google ads"
    assert lead_row.attribution.get("campaign_id") == "55"
    assert uuid.UUID(str(row.lead_id))

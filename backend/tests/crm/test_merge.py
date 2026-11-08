"""Step 1: finding duplicates and merging two leads."""

from datetime import timedelta

from sqlalchemy import func, select

from app.core.tenancy import tenant_session
from app.modules.crm import leads as L
from app.modules.crm.models import Activity, Consent, Lead, LeadMerge, Task
from tests.crm.intake_helpers import capture, lead, settings
from tests.factories import login_as


async def _pair(tenant_id, owner=None):
    """Two leads for the same person: one by phone, one by email (flagged as duplicate)."""
    await settings(tenant_id, duplicate_policy="flag")
    _, a = await capture(
        tenant_id,
        owner=owner,
        phone="98765 12345",
        fields={"first_name": "Rahul", "city": "Pune"},
        next_follow_up_at=L.now() + timedelta(days=2),
    )
    _, b = await capture(
        tenant_id,
        owner=owner,
        phone="98765 12345",
        policy="flag",
        email="rahul@example.org",
        fields={"first_name": "Rahul K", "last_name": "Kumar", "city": "Mumbai"},
        consents={"email": "opted_in"},
        next_follow_up_at=L.now() + timedelta(days=1),
    )
    return a, b


async def test_duplicates_are_listed_both_ways(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    a, b = await _pair(tenant_id)
    assert [d["id"] for d in (await c.get(f"/api/v1/leads/{a}/duplicates", headers=h)).json()] == [
        str(b)
    ]
    assert [d["id"] for d in (await c.get(f"/api/v1/leads/{b}/duplicates", headers=h)).json()] == [
        str(a)
    ]


async def test_merge_moves_everything_and_keeps_chosen_values(ws):
    tenant_id, c = ws
    mgr, h = await login_as(tenant_id, "sales_manager")
    a, b = await _pair(tenant_id, owner=mgr)
    la, lb = await lead(tenant_id, a), await lead(tenant_id, b)
    r = await c.post(
        "/api/v1/leads/merge",
        json={
            "survivor_id": str(a),
            "survivor_version": la.version,
            "other_id": str(b),
            "other_version": lb.version,
            "take_from_other": ["city"],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    # Chosen value from the other lead, the survivor's own value elsewhere, blanks filled.
    assert (out["city"], out["first_name"], out["last_name"]) == ("Mumbai", "Rahul", "Kumar")
    assert out["primary_email"] == "rahul@example.org" and out["email_consent"] == "opted_in"
    assert out["possible_duplicate_of_id"] is None
    assert (await c.get(f"/api/v1/leads/{b}", headers=h)).status_code == 404
    assert (await c.get(f"/api/v1/leads/{b}/merged-into", headers=h)).json() == {"lead_id": str(a)}

    async with tenant_session(tenant_id) as db:
        types = (await db.scalars(select(Activity.type_key).where(Activity.lead_id == a))).all()
        open_follow_ups = await db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.lead_id == a, Task.is_follow_up.is_(True), Task.status == "open")
        )
        consents = await db.scalar(
            select(func.count()).select_from(Consent).where(Consent.lead_id == a)
        )
        snapshot = await db.scalar(select(LeadMerge.snapshot).where(LeadMerge.survivor_id == a))
        survivor = await db.get(Lead, a)
    assert types.count("lead_created") == 2 and "lead_merged" in types
    assert open_follow_ups == 1 and consents == 1
    assert snapshot["display_name"] == "Rahul K Kumar"
    assert survivor.next_follow_up_at is not None


async def test_merge_needs_permission_fresh_versions_and_visibility(ws):
    tenant_id, c = ws
    _, rep_h = await login_as(tenant_id, "sales_user")
    _, admin_h = await login_as(tenant_id, "admin")
    a, b = await _pair(tenant_id)
    la, lb = await lead(tenant_id, a), await lead(tenant_id, b)
    body = {
        "survivor_id": str(a),
        "survivor_version": la.version,
        "other_id": str(b),
        "other_version": lb.version,
    }
    assert (await c.post("/api/v1/leads/merge", json=body, headers=rep_h)).status_code == 403
    stale = body | {"other_version": lb.version - 1}
    assert (await c.post("/api/v1/leads/merge", json=stale, headers=admin_h)).status_code == 409
    same = body | {"other_id": str(a), "other_version": la.version}
    assert (await c.post("/api/v1/leads/merge", json=same, headers=admin_h)).status_code == 422
    bad = body | {"take_from_other": ["password"]}
    assert (await c.post("/api/v1/leads/merge", json=bad, headers=admin_h)).status_code == 422


async def test_an_opt_out_on_either_lead_wins(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    a, b = await _pair(tenant_id)
    await c.post(
        f"/api/v1/leads/{a}/consents", json={"channel": "email", "status": "opted_out"}, headers=h
    )
    la, lb = await lead(tenant_id, a), await lead(tenant_id, b)
    r = await c.post(
        "/api/v1/leads/merge",
        json={
            "survivor_id": str(b),
            "survivor_version": lb.version,
            "other_id": str(a),
            "other_version": la.version,
        },
        headers=h,
    )
    assert r.json()["email_consent"] == "opted_out"


async def test_unassigned_leads_keep_their_follow_up_date(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    a, b = await _pair(tenant_id)
    la, lb = await lead(tenant_id, a), await lead(tenant_id, b)
    r = await c.post(
        "/api/v1/leads/merge",
        json={
            "survivor_id": str(a),
            "survivor_version": la.version,
            "other_id": str(b),
            "other_version": lb.version,
        },
        headers=h,
    )
    assert r.json()["next_follow_up_at"] is not None

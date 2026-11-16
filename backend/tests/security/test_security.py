"""Batch 1 of the finishing plan: security.

Sign-in history (successes and failures, for the person and for admins); an alert email after 5
failed tries; the company's IP allowlist (it can't lock the admin out, and it applies to
sign-in, renewal and every request); idle sign-out; signing out one device, one person or the
whole company (at once, not after 15 minutes); export everything (no secrets in it); erasing a
person (DPDP / GDPR)."""

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.core.events_model import Event
from app.core.security import create_access_token
from app.core.tenancy import tenant_session
from app.modules.auth.models import UserSession
from app.modules.calls.models import Call
from app.modules.crm.models import Activity, Lead, LeadIdentity
from app.modules.security import service as S
from app.modules.security.models import DataExport
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import PASSWORD, login_as, make_user, make_workspace
from tests.http_fixtures import bearer, sign_in

LOGIN = "/api/v1/auth/login"


async def _company(client_for):
    tenant_id, slug = await make_workspace()
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, client_for(slug), admin


async def _set(tenant_id, **security):
    async with tenant_session(tenant_id) as db:
        row = await db.get(TenantSettings, tenant_id)
        row.security = {**(row.security or {}), **security}


async def test_sign_in_history_for_the_person_and_admins(client_for):
    tenant_id, c, admin = await _company(client_for)
    _, email = await make_user(tenant_id)

    bad = await c.post(LOGIN, json={"email": email, "password": "wrong-password-1"})
    good = await sign_in(c, email, PASSWORD)
    mine = await c.get("/api/v1/me/sign-ins", headers=bearer(good.json()["access_token"]))
    everyone = await c.get("/api/v1/security/sign-ins", headers=admin)
    failed = await c.get("/api/v1/security/sign-ins?failed=true", headers=admin)
    _, rep = await login_as(tenant_id, "sales_user")
    by_rep = await c.get("/api/v1/security/sign-ins", headers=rep)

    assert bad.status_code == 401 and good.status_code == 200
    assert [(s["success"], s["reason"]) for s in mine.json()] == [
        (True, None),
        (False, "wrong_password"),
    ]
    assert {s["email"] for s in everyone.json()} == {email}
    assert [s["reason"] for s in failed.json()] == ["wrong_password"]
    assert by_rep.status_code == 403


async def test_five_failed_tries_email_the_person_and_admins(client_for, mailer):
    tenant_id, c, _ = await _company(client_for)
    _, owner_email = await make_user(tenant_id, role_key="owner")
    _, email = await make_user(tenant_id)
    for _ in range(5):
        await c.post(LOGIN, json={"email": email, "password": "wrong-password-1"})
    alerts = [m for m in mailer.sent if m.subject == "Failed sign-in attempts"]
    assert {m.to for m in alerts} >= {email, owner_email}
    assert all("wrong-password" not in m.body for m in alerts)


async def test_ip_allowlist_cant_lock_the_admin_out_and_applies_everywhere(client_for):
    tenant_id, c, admin = await _company(client_for)
    _, email = await make_user(tenant_id)
    _, rep = await login_as(tenant_id, "sales_user")
    you = (await c.get("/api/v1/security/settings", headers=admin)).json()["your_ip"]

    locked = await c.put("/api/v1/security/settings", headers=admin,
                         json={"ip_allowlist": ["203.0.113.0/24"]})  # fmt: skip
    ok = await c.put("/api/v1/security/settings", headers=admin,
                     json={"ip_allowlist": [you, "203.0.113.0/24"]})  # fmt: skip
    junk = await c.put("/api/v1/security/settings", headers=admin, json={"ip_allowlist": ["x"]})
    allowed = await c.get("/api/v1/auth/me", headers=rep)
    await _set(tenant_id, ip_allowlist=["203.0.113.0/24"])  # elsewhere: this address is out
    refused_request = await c.get("/api/v1/auth/me", headers=rep)
    refused_login = await c.post(LOGIN, json={"email": email, "password": PASSWORD})

    assert locked.status_code == 422 and locked.json()["code"] == "would_lock_you_out"
    assert ok.status_code == 200 and junk.status_code == 422
    assert allowed.status_code == 200
    assert refused_request.status_code == 403 and refused_login.status_code == 403


async def test_idle_sign_out_ends_a_session_nobody_renewed(client_for):
    tenant_id, c, admin = await _company(client_for)
    _, email = await make_user(tenant_id)
    first = await sign_in(c, email, PASSWORD)
    refresh = first.cookies["user_refresh"]
    bad_idle = await c.put("/api/v1/security/settings", headers=admin, json={"idle_minutes": 5})
    await c.put("/api/v1/security/settings", headers=admin, json={"idle_minutes": 30})
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(UserSession).values(created_at=datetime.now(UTC) - timedelta(minutes=45))
        )
    r = await c.post("/api/v1/auth/refresh", headers={"Cookie": f"user_refresh={refresh}"})
    assert bad_idle.status_code == 422 and r.status_code == 401


async def test_signing_out_a_person_or_everyone_works_at_once(client_for):
    tenant_id, c, admin = await _company(client_for)
    rep_id, _ = await login_as(tenant_id, "sales_user")
    earlier = datetime.now(UTC) - timedelta(seconds=5)
    rep = bearer(create_access_token(rep_id, "user", tenant_id, now=earlier))
    _, other = await login_as(tenant_id, "sales_user")

    before = await c.get("/api/v1/auth/me", headers=rep)
    by_rep = await c.post("/api/v1/security/sign-out-everyone", headers=other)
    one = await c.post(f"/api/v1/security/users/{rep_id}/sign-out", headers=admin)
    after = await c.get("/api/v1/auth/me", headers=rep)

    assert before.status_code == 200 and by_rep.status_code == 403
    assert one.status_code == 204 and after.status_code == 401


async def test_my_devices_and_signing_one_out(client_for):
    tenant_id, c, _ = await _company(client_for)
    _, email = await make_user(tenant_id)
    phone = await sign_in(c, email, PASSWORD)
    laptop = await sign_in(c, email, PASSWORD)
    headers = {**bearer(laptop.json()["access_token"]),
               "Cookie": f"user_refresh={laptop.cookies['user_refresh']}"}  # fmt: skip
    devices = (await c.get("/api/v1/me/devices", headers=headers)).json()
    other = next(d for d in devices if not d["this_device"])
    await c.post(f"/api/v1/me/devices/{other['id']}/sign-out", headers=headers)
    phone_cookie = {"Cookie": f"user_refresh={phone.cookies['user_refresh']}"}
    renewed = await c.post("/api/v1/auth/refresh", headers=phone_cookie)
    assert len(devices) == 2 and sum(d["this_device"] for d in devices) == 1
    assert renewed.status_code == 401


async def test_export_everything_has_the_data_and_no_secrets(client_for):
    tenant_id, c, admin = await _company(client_for)
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"], first_name="Zoya")
    _, rep = await login_as(tenant_id, "sales_user")

    by_rep = await c.post("/api/v1/data-exports", headers=rep)
    r = await c.post("/api/v1/data-exports", headers=admin)
    again = await c.post("/api/v1/data-exports", headers=admin)
    await S.build_export(tenant_id, uuid.UUID(r.json()["id"]))
    listed = (await c.get("/api/v1/data-exports", headers=admin)).json()
    zip_ = await c.get(f"/api/v1/data-exports/{r.json()['id']}/download", headers=admin)

    assert by_rep.status_code == 403 and r.status_code == 201
    assert again.json()["code"] == "export_running"
    assert listed[0]["status"] == "ready"
    z = zipfile.ZipFile(io.BytesIO(zip_.content))
    names = z.namelist()
    assert "data/leads.jsonl" in names and "data/users.jsonl" in names
    assert "data/user_sessions.jsonl" not in names
    leads = [json.loads(line) for line in z.read("data/leads.jsonl").splitlines()]
    assert any(lead["first_name"] == "Zoya" for lead in leads)
    users = z.read("data/users.jsonl").decode()
    assert "password_hash" not in users and "totp_secret" not in users
    async with tenant_session(tenant_id) as db:
        row = await db.get(DataExport, uuid.UUID(r.json()["id"]))
    S.export_file(row.path).unlink()


async def test_erasing_a_person_removes_their_data_and_tells_connected_systems(client_for):
    tenant_id, c, admin = await _company(client_for)
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], first_name="Ravi")).json()
    await c.post(f"/api/v1/leads/{lead['id']}/notes", json={"body": "Ravi's notes"}, headers=admin)
    await c.post("/api/v1/calls", headers=admin, json={
        "external_id": "x1", "direction": "out", "status": "answered", "number": "98765 43210",
        "started_at": datetime.now(UTC).isoformat(), "duration_seconds": 30})  # fmt: skip
    _, rep = await login_as(tenant_id, "sales_user")

    by_rep = await c.post(
        f"/api/v1/leads/{lead['id']}/erase", json={"confirm": "ERASE"}, headers=rep
    )
    unsure = await c.post(
        f"/api/v1/leads/{lead['id']}/erase", json={"confirm": "yes"}, headers=admin
    )
    r = await c.post(f"/api/v1/leads/{lead['id']}/erase", json={"confirm": "ERASE"}, headers=admin)
    twice = await c.post(
        f"/api/v1/leads/{lead['id']}/erase", json={"confirm": "ERASE"}, headers=admin
    )

    assert by_rep.status_code == 403 and unsure.status_code == 422
    assert r.status_code == 204 and twice.status_code == 409
    lid = uuid.UUID(lead["id"])
    async with tenant_session(tenant_id) as db:
        row = await db.get(Lead, lid)
        left = [
            await db.scalar(select(func.count()).select_from(m).where(m.lead_id == lid))
            for m in (Activity, LeadIdentity, Call)
        ]
        events = (await db.scalars(select(Event.type).where(Event.type == "lead.erased"))).all()
    assert row.display_name == "Erased person" and row.first_name is None and row.erased_at
    assert row.primary_phone is None and left == [0, 0, 0] and events == ["lead.erased"]


async def test_a_persons_data_for_their_access_request(client_for):
    tenant_id, c, admin = await _company(client_for)
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], first_name="Meera")).json()
    _, rep = await login_as(tenant_id, "sales_user")

    r = await c.get(f"/api/v1/leads/{lead['id']}/personal-data", headers=admin)
    by_rep = await c.get(f"/api/v1/leads/{lead['id']}/personal-data", headers=rep)

    assert r.status_code == 200 and by_rep.status_code == 403
    body = r.json()
    assert body["person"]["first_name"] == "Meera" and "tenant_id" not in body["person"]
    assert body["contact_points"] and any(a["type_key"] for a in body["timeline"])

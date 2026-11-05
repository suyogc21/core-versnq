import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.factories import staff_headers


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _bearer(t):
    return {"Authorization": f"Bearer {t}"}


async def _create(client, headers, email="new.staff@versnq.in"):
    return await client.post(
        "/platform/staff", json={"email": email, "name": "New Staff"}, headers=headers
    )


async def test_new_staff_must_change_password_then_set_up_2fa(client):
    admin = await staff_headers()
    created = await _create(client, admin)
    temp = created.json()["temporary_password"]

    token = (
        await client.post(
            "/platform/auth/login", json={"email": "new.staff@versnq.in", "password": temp}
        )
    ).json()["access_token"]
    first = await client.get("/platform/tenants", headers=_bearer(token))
    me = await client.get("/platform/auth/me", headers=_bearer(token))
    assert created.status_code == 201
    assert first.json()["detail"] == "password_change_required"
    assert me.json()["restrictions"] == ["password_change_required", "two_factor_setup_required"]

    changed = await client.post(
        "/platform/auth/password/change",
        json={"current_password": temp, "new_password": "my-own-staff-pass-1"},
        headers=_bearer(token),
    )
    token = (
        await client.post(
            "/platform/auth/login",
            json={"email": "new.staff@versnq.in", "password": "my-own-staff-pass-1"},
        )
    ).json()["access_token"]
    second = await client.get("/platform/tenants", headers=_bearer(token))
    secret = (await client.post("/platform/auth/2fa/setup", headers=_bearer(token))).json()[
        "secret"
    ]
    await client.post(
        "/platform/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=_bearer(token)
    )
    third = await client.get("/platform/tenants", headers=_bearer(token))

    assert changed.status_code == 204
    assert second.json()["detail"] == "two_factor_setup_required"
    assert third.status_code == 200


async def test_duplicate_staff_email_409(client):
    admin = await staff_headers()
    await _create(client, admin, "dup@versnq.in")
    assert (await _create(client, admin, "DUP@versnq.in")).status_code == 409


async def test_deactivated_staff_cannot_log_in_and_listing_works(client):
    admin = await staff_headers()
    created = (await _create(client, admin, "leaver@versnq.in")).json()

    r = await client.patch(
        f"/platform/staff/{created['id']}", json={"is_active": False}, headers=admin
    )
    login = await client.post(
        "/platform/auth/login",
        json={"email": "leaver@versnq.in", "password": created["temporary_password"]},
    )
    listed = await client.get("/platform/staff", headers=admin)

    assert r.status_code == 200 and r.json()["is_active"] is False
    assert login.status_code == 401
    assert "leaver@versnq.in" in [s["email"] for s in listed.json()]


async def test_staff_cannot_deactivate_themselves(client):
    admin = await staff_headers()
    me = (await client.get("/platform/auth/me", headers=admin)).json()
    r = await client.patch(f"/platform/staff/{me['id']}", json={"is_active": False}, headers=admin)
    assert r.status_code == 403


async def test_staff_changes_are_audited_without_passwords(client):
    admin = await staff_headers()
    created = (await _create(client, admin, "audited@versnq.in")).json()
    await client.patch(f"/platform/staff/{created['id']}", json={"name": "Renamed"}, headers=admin)

    audit = await client.get("/platform/audit", params={"target_id": created["id"]}, headers=admin)
    assert sorted(a["action"] for a in audit.json()) == ["staff.created", "staff.updated"]
    assert created["temporary_password"] not in audit.text

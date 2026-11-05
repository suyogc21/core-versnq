import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app
from tests.factories import make_staff

LOGIN = "/platform/auth/login"
REFRESH = "/platform/auth/refresh"
LOGOUT = "/platform/auth/logout"
ME = "/platform/auth/me"
GENERIC_401 = "Invalid email or password"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _refresh_cookie(response) -> str:
    return response.cookies["staff_refresh"]


async def _login(client, email, password="s3cret-pass-123"):
    return await client.post(LOGIN, json={"email": email, "password": password})


async def _refresh(client, token):
    return await client.post(REFRESH, headers={"Cookie": f"staff_refresh={token}"})


async def test_staff_login_returns_tokens(client):
    email = await make_staff()
    r = await _login(client, email)

    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert r.json()["access_token"]
    assert _refresh_cookie(r)


async def test_wrong_password_and_unknown_email_same_401_message(client):
    email = await make_staff()
    wrong_pw = await _login(client, email, "nope-nope-nope")
    unknown = await _login(client, f"ghost-{uuid.uuid4().hex}@versnq.in")

    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"] == GENERIC_401


async def test_email_is_case_insensitive(client):
    email = await make_staff()
    assert (await _login(client, email.upper())).status_code == 200


async def test_inactive_staff_cannot_login(client):
    email = await make_staff(is_active=False)
    r = await _login(client, email)
    assert r.status_code == 401
    assert r.json()["detail"] == GENERIC_401


async def test_me_returns_staff(client):
    email = await make_staff()
    token = (await _login(client, email)).json()["access_token"]
    r = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == email


async def test_refresh_rotates_token(client):
    email = await make_staff()
    old = _refresh_cookie(await _login(client, email))

    r = await _refresh(client, old)

    assert r.status_code == 200
    assert r.json()["access_token"]
    assert _refresh_cookie(r) != old


async def test_reused_refresh_token_revokes_all_sessions(client):
    email = await make_staff()
    session_1 = _refresh_cookie(await _login(client, email))
    session_2 = _refresh_cookie(await _login(client, email))
    session_1_new = _refresh_cookie(await _refresh(client, session_1))

    reuse = await _refresh(client, session_1)  # a thief replays the old token

    assert reuse.status_code == 401
    assert (await _refresh(client, session_1_new)).status_code == 401
    assert (await _refresh(client, session_2)).status_code == 401


async def test_logout_revokes_session(client):
    email = await make_staff()
    token = _refresh_cookie(await _login(client, email))

    out = await client.post(LOGOUT, headers={"Cookie": f"staff_refresh={token}"})

    assert out.status_code == 204
    assert (await _refresh(client, token)).status_code == 401


async def test_user_typ_token_rejected_on_platform_routes(client):
    user_token = create_access_token(uuid.uuid4(), "user", uuid.uuid4())
    r = await client.get(ME, headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 401


async def test_me_without_token_is_401(client):
    assert (await client.get(ME)).status_code == 401

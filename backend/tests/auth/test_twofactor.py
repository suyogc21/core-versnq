import pyotp
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.core.twofactor import decrypt_secret, new_secret
from app.modules.users.models import User
from tests.auth.conftest import bearer
from tests.factories import PASSWORD, make_staff, make_user, make_workspace, staff_headers


async def _login(c, email, password=PASSWORD):
    return await c.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_owner_without_2fa_is_limited_to_setup(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, role_key="owner")
    c = client_for(slug)
    token = (await _login(c, email)).json()["access_token"]

    blocked = await c.get("/api/v1/settings", headers=bearer(token))
    me = await c.get("/api/v1/auth/me", headers=bearer(token))

    assert blocked.status_code == 403 and blocked.json()["detail"] == "two_factor_setup_required"
    assert me.json()["restrictions"] == ["two_factor_setup_required"]


async def test_sales_user_without_2fa_is_not_limited(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, role_key="sales_user")
    c = client_for(slug)
    token = (await _login(c, email)).json()["access_token"]
    assert (await c.get("/api/v1/settings", headers=bearer(token))).status_code == 200


async def test_setup_and_enable_2fa_unlocks_owner(client_for):
    tenant_id, slug = await make_workspace()
    user_id, email = await make_user(tenant_id, role_key="owner")
    c = client_for(slug)
    token = (await _login(c, email)).json()["access_token"]

    setup = await c.post("/api/v1/auth/2fa/setup", headers=bearer(token))
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")

    wrong = await c.post("/api/v1/auth/2fa/enable", json={"code": "000000"}, headers=bearer(token))
    right = await c.post(
        "/api/v1/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=bearer(token)
    )

    assert wrong.status_code == 400 and right.status_code == 204
    assert (await c.get("/api/v1/settings", headers=bearer(token))).status_code == 200
    async with tenant_session(tenant_id) as s:
        stored = (await s.scalars(select(User.totp_secret_enc).where(User.id == user_id))).one()
    assert stored != secret and decrypt_secret(stored) == secret


async def test_login_with_2fa_needs_code(client_for):
    secret = new_secret()
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, role_key="owner", totp_secret=secret)
    c = client_for(slug)

    first = await _login(c, email)
    body = first.json()
    assert body["two_factor_required"] is True and body.get("access_token") is None
    challenge = body["challenge_token"]

    # the challenge token is not an access token
    assert (await c.get("/api/v1/auth/me", headers=bearer(challenge))).status_code == 401
    bad = await c.post(
        "/api/v1/auth/2fa/verify", json={"challenge_token": challenge, "code": "000000"}
    )
    good = await c.post(
        "/api/v1/auth/2fa/verify",
        json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
    )

    assert bad.status_code == 401
    assert good.status_code == 200 and good.cookies["user_refresh"]
    me = await c.get("/api/v1/auth/me", headers=bearer(good.json()["access_token"]))
    assert me.json()["restrictions"] == []


async def test_cannot_replace_enabled_2fa_via_setup(client_for):
    secret = new_secret()
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, role_key="owner", totp_secret=secret)
    c = client_for(slug)
    challenge = (await _login(c, email)).json()["challenge_token"]
    token = (
        await c.post(
            "/api/v1/auth/2fa/verify",
            json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
        )
    ).json()["access_token"]

    assert (await c.post("/api/v1/auth/2fa/setup", headers=bearer(token))).status_code == 409


async def test_staff_without_2fa_blocked_from_tenant_management(client_for):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        limited = await c.get("/platform/tenants", headers=await staff_headers(two_factor=False))
        full = await c.get("/platform/tenants", headers=await staff_headers(two_factor=True))
    assert limited.status_code == 403 and limited.json()["detail"] == "two_factor_setup_required"
    assert full.status_code == 200


async def test_staff_login_with_2fa_needs_code():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    secret = new_secret()
    email = await make_staff(totp_secret=secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        first = await c.post(
            "/platform/auth/login", json={"email": email, "password": "s3cret-pass-123"}
        )
        challenge = first.json()["challenge_token"]
        good = await c.post(
            "/platform/auth/2fa/verify",
            json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
        )
    assert first.json()["two_factor_required"] is True
    assert good.status_code == 200 and good.json()["access_token"]


async def test_staff_can_set_up_2fa():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    headers = await staff_headers(two_factor=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        secret = (await c.post("/platform/auth/2fa/setup", headers=headers)).json()["secret"]
        r = await c.post(
            "/platform/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=headers
        )
        after = await c.get("/platform/tenants", headers=headers)
    assert r.status_code == 204 and after.status_code == 200

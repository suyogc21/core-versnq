import pyotp
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.core.twofactor import decrypt_secret, new_secret
from app.modules.users.models import User
from tests.auth.conftest import bearer
from tests.factories import PASSWORD, make_staff, make_user, make_workspace, staff_headers
from tests.http_fixtures import sign_in


async def _login(c, email, password=PASSWORD):
    return await sign_in(c, email, password)


async def test_owner_without_the_app_is_not_limited(client_for):
    """The authenticator app is optional for every role (Decision #45)."""
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, role_key="owner")
    c = client_for(slug)
    token = (await _login(c, email)).json()["access_token"]

    me = await c.get("/api/v1/auth/me", headers=bearer(token))

    assert (await c.get("/api/v1/settings", headers=bearer(token))).status_code == 200
    assert me.json()["restrictions"] == []


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


async def _signed_in_with_2fa(client_for, role_key="owner"):
    secret = new_secret()
    tenant_id, slug = await make_workspace()
    user_id, email = await make_user(tenant_id, role_key=role_key, totp_secret=secret)
    c = client_for(slug)
    challenge = (await _login(c, email)).json()["challenge_token"]
    token = (
        await c.post(
            "/api/v1/auth/2fa/verify",
            json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()},
        )
    ).json()["access_token"]
    return c, token, secret, tenant_id, user_id


async def test_turning_off_2fa_needs_password_and_current_code(client_for):
    c, token, secret, tenant_id, user_id = await _signed_in_with_2fa(client_for)
    off = "/api/v1/auth/2fa/disable"
    code = pyotp.TOTP(secret).now()

    wrong_pw = await c.post(off, json={"password": "wrong", "code": code}, headers=bearer(token))
    wrong_code = await c.post(
        off, json={"password": PASSWORD, "code": "000000"}, headers=bearer(token)
    )
    ok = await c.post(off, json={"password": PASSWORD, "code": code}, headers=bearer(token))
    again = await c.post(off, json={"password": PASSWORD, "code": code}, headers=bearer(token))

    assert (wrong_pw.status_code, wrong_code.status_code) == (400, 400)
    assert ok.status_code == 204 and again.status_code == 409
    async with tenant_session(tenant_id) as s:
        user = await s.get(User, user_id)
    assert user.totp_enabled is False and user.totp_secret_enc is None


async def test_owner_who_turns_off_2fa_keeps_working(client_for):
    """Turning the app off is allowed for every role; sign-in then asks for an emailed code."""
    c, token, secret, *_ = await _signed_in_with_2fa(client_for)
    await c.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        headers=bearer(token),
    )
    me = await c.get("/api/v1/auth/me", headers=bearer(token))
    assert me.json()["restrictions"] == []
    assert (await c.get("/api/v1/settings", headers=bearer(token))).status_code == 200


async def test_turning_off_2fa_is_audited_and_rate_limited(client_for):
    from app.modules.audit.models import AuditLog

    c, token, secret, tenant_id, user_id = await _signed_in_with_2fa(client_for, "sales_user")
    for _ in range(5):
        await c.post(
            "/api/v1/auth/2fa/disable",
            json={"password": PASSWORD, "code": "000000"},
            headers=bearer(token),
        )
    locked = await c.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        headers=bearer(token),
    )
    assert locked.status_code == 429

    from app.core import ratelimit

    await ratelimit.clear(f"rl:2fa-off:{user_id}")
    await c.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        headers=bearer(token),
    )
    async with tenant_session(tenant_id) as s:
        actions = (
            await s.scalars(select(AuditLog.action).where(AuditLog.entity_id == user_id))
        ).all()
    assert "user.2fa_disabled" in actions

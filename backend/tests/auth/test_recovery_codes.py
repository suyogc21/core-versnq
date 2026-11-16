"""Go-live G-4, lost phone: 10 one-time backup codes when the app is turned on (stored hashed,
each works once, the person is emailed when one is used), new codes need the password and the
app, an Owner / Admin resets a member's app (not their own, Admins not an Owner's), Versnq staff
reset an Owner's (audited), staff have backup codes too, another company's codes never work."""

import pyotp
from sqlalchemy import func, select

from app.core.tenancy import tenant_session
from app.modules.auth.models import UserRecoveryCode, UserSession
from app.modules.users.models import User
from tests.auth.conftest import bearer
from tests.factories import PASSWORD, login_as, make_staff, make_user, make_workspace, staff_headers
from tests.http_fixtures import sign_in

VERIFY = "/api/v1/auth/2fa/verify"


async def _with_app(c, tenant_id, role_key="sales_user"):
    """A person signed in who turns the app on; returns (user_id, email, token, secret, codes)."""
    user_id, email = await make_user(tenant_id, role_key=role_key)
    token = (await sign_in(c, email, PASSWORD)).json()["access_token"]
    secret = (await c.post("/api/v1/auth/2fa/setup", headers=bearer(token))).json()["secret"]
    r = await c.post("/api/v1/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()},
                     headers=bearer(token))  # fmt: skip
    assert r.status_code == 200, r.text
    return user_id, email, token, secret, r.json()["recovery_codes"]


async def _challenge(c, email):
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.json()["two_factor_method"] == "app"
    return r.json()["challenge_token"]


async def test_backup_codes_work_once_and_are_stored_hashed(client_for, mailer):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    user_id, email, _, _, codes = await _with_app(c, tenant_id)

    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(x) == 9 for x in codes)
    ok = await c.post(VERIFY, json={"challenge_token": await _challenge(c, email),
                                    "code": codes[0].upper()})  # fmt: skip
    again = await c.post(VERIFY, json={"challenge_token": await _challenge(c, email),
                                       "code": codes[0]})  # fmt: skip
    me = await c.get("/api/v1/auth/me", headers=bearer(ok.json()["access_token"]))

    assert ok.status_code == 200 and again.status_code == 401
    assert me.json()["recovery_codes_left"] == 9
    assert any("backup code was used" in m.subject for m in mailer.sent if m.to == email)
    async with tenant_session(tenant_id) as db:
        stored = (await db.scalars(select(UserRecoveryCode.code_hash))).all()
    assert len(stored) == 10 and not any(
        code.replace("-", "") in h for code in codes for h in stored
    )


async def test_new_codes_need_the_password_and_the_app(client_for):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    _, email, token, secret, old = await _with_app(c, tenant_id)
    url = "/api/v1/auth/2fa/recovery-codes"

    wrong = await c.post(url, json={"password": "nope", "code": pyotp.TOTP(secret).now()},
                         headers=bearer(token))  # fmt: skip
    fresh = await c.post(url, json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
                         headers=bearer(token))  # fmt: skip
    stale = await c.post(VERIFY, json={"challenge_token": await _challenge(c, email),
                                       "code": old[1]})  # fmt: skip

    assert wrong.status_code == 400
    assert fresh.status_code == 200 and set(fresh.json()["recovery_codes"]).isdisjoint(old)
    assert stale.status_code == 401  # the old codes stopped working


async def test_an_admin_resets_a_members_app_but_not_their_own_or_an_owners(client_for, mailer):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    rep_id, rep_email, *_ = await _with_app(c, tenant_id)
    owner_id, *_ = await _with_app(c, tenant_id, "owner")
    admin_id, admin = await login_as(tenant_id, "admin")
    _, rep_headers = await login_as(tenant_id, "sales_user")

    by_rep = await c.post(f"/api/v1/users/{rep_id}/2fa/reset", headers=rep_headers)
    owner = await c.post(f"/api/v1/users/{owner_id}/2fa/reset", headers=admin)
    own = await c.post(f"/api/v1/users/{admin_id}/2fa/reset", headers=admin)
    ok = await c.post(f"/api/v1/users/{rep_id}/2fa/reset", headers=admin)

    assert by_rep.status_code == 403 and owner.status_code == 403 and own.status_code == 403
    assert ok.status_code == 200 and ok.json()["totp_enabled"] is False
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(func.count()).select_from(UserRecoveryCode).where(
            UserRecoveryCode.user_id == rep_id)) == 0  # fmt: skip
    async with tenant_session(tenant_id) as db:  # signed out everywhere (sessions ended)
        open_ = await db.scalar(select(func.count()).select_from(UserSession).where(
            UserSession.user_id == rep_id, UserSession.revoked_at.is_(None)))  # fmt: skip
    assert open_ == 0
    after = await c.post("/api/v1/auth/login", json={"email": rep_email, "password": PASSWORD})
    assert after.json()["two_factor_method"] == "email"
    assert any("authenticator app was reset" in m.subject for m in mailer.sent if m.to == rep_email)


async def test_staff_reset_an_owners_app_and_it_is_audited(client_for, mailer):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    _, owner_email, *_ = await _with_app(c, tenant_id, "owner")
    _, rep_email, *_ = await _with_app(c, tenant_id)
    headers = await staff_headers()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as s:
        url = f"/platform/tenants/{tenant_id}/owner-2fa-reset"
        not_owner = await s.post(url, json={"email": rep_email}, headers=headers)
        ok = await s.post(url, json={"email": owner_email.upper()}, headers=headers)
        no_staff = await s.post(url, json={"email": owner_email})
        log = (await s.get("/platform/audit", headers=headers)).json()

    assert not_owner.status_code == 404 and ok.status_code == 204 and no_staff.status_code == 401
    assert any(e["action"] == "tenant.owner_2fa_reset" for e in log)
    async with tenant_session(tenant_id) as db:
        owner = await db.scalar(select(User).where(User.email == owner_email))
    assert owner.totp_enabled is False


async def test_staff_get_backup_codes_too():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    email = await make_staff()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as s:
        login = await s.post("/platform/auth/login",
                             json={"email": email, "password": "s3cret-pass-123"})  # fmt: skip
        token = login.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        secret = (await s.post("/platform/auth/2fa/setup", headers=h)).json()["secret"]
        codes = (await s.post("/platform/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()},
                              headers=h)).json()["recovery_codes"]  # fmt: skip

        async def challenge():
            r = await s.post("/platform/auth/login",
                             json={"email": email, "password": "s3cret-pass-123"})  # fmt: skip
            return r.json()["challenge_token"]

        v = "/platform/auth/2fa/verify"
        ok = await s.post(v, json={"challenge_token": await challenge(), "code": codes[3]})
        again = await s.post(v, json={"challenge_token": await challenge(), "code": codes[3]})
    assert len(codes) == 10 and ok.status_code == 200 and again.status_code == 401


async def test_another_companys_code_never_works(client_for):
    tenant_a, slug_a = await make_workspace()
    tenant_b, slug_b = await make_workspace()
    a, b = client_for(slug_a), client_for(slug_b)
    *_, codes_a = await _with_app(a, tenant_a)
    _, email_b, *_ = await _with_app(b, tenant_b)

    r = await b.post(VERIFY, json={"challenge_token": await _challenge(b, email_b),
                                   "code": codes_a[0]})  # fmt: skip
    assert r.status_code == 401


async def test_staff_with_the_app_but_no_codes_get_new_ones_and_it_is_audited():
    """A staff member who turned the app on before G-4 has no codes: password + app makes 10."""
    from httpx import ASGITransport, AsyncClient

    from app.core.tenancy import platform_session
    from app.main import app
    from app.platform.audit import PlatformAuditLog

    secret = pyotp.random_base32()
    email = await make_staff(totp_secret=secret)
    url = "/platform/auth/2fa/recovery-codes"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as s:
        login = await s.post("/platform/auth/login",
                             json={"email": email, "password": "s3cret-pass-123"})  # fmt: skip
        challenge = login.json()["challenge_token"]
        body = {"challenge_token": challenge, "code": pyotp.TOTP(secret).now()}
        r = await s.post("/platform/auth/2fa/verify", json=body)
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        before = (await s.get("/platform/auth/me", headers=h)).json()["recovery_codes_left"]
        wrong = await s.post(url, json={"password": "nope-nope", "code": pyotp.TOTP(secret).now()},
                             headers=h)  # fmt: skip
        ok = await s.post(url, json={"password": "s3cret-pass-123",
                                     "code": pyotp.TOTP(secret).now()}, headers=h)  # fmt: skip
        after = (await s.get("/platform/auth/me", headers=h)).json()["recovery_codes_left"]
        no_token = await s.post(url, json={"password": "s3cret-pass-123", "code": "123456"})
    async with platform_session() as db:
        logged = await db.scalar(
            select(func.count())
            .select_from(PlatformAuditLog)
            .where(PlatformAuditLog.action == "staff.2fa_backup_codes_renewed")  # fmt: skip
        )
    assert before == 0 and wrong.status_code == 400 and no_token.status_code == 401
    assert ok.status_code == 200 and len(ok.json()["recovery_codes"]) == 10 and after == 10
    assert logged >= 1

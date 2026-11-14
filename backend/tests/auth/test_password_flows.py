from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.tenancy import tenant_session
from app.modules.auth.models import AuthToken
from app.modules.auth.service import issue_link_token
from app.modules.users.models import User
from tests.auth.conftest import bearer, cookie
from tests.factories import PASSWORD, make_user, make_workspace
from tests.http_fixtures import sign_in

NEW_PW = "brand-new-pass-456"


async def _invite(tenant_id, user_id, hours=72):
    async with tenant_session(tenant_id) as s:
        return await issue_link_token(s, tenant_id, user_id, "invite", timedelta(hours=hours))


def _token_from(mail) -> str:
    return mail.body.split("token=")[1].split()[0]


async def test_accept_invite_sets_password_and_activates(client_for):
    tenant_id, slug = await make_workspace()
    user_id, email = await make_user(tenant_id, status="invited", password=None)
    plain = await _invite(tenant_id, user_id)
    c = client_for(slug)

    r = await c.post("/api/v1/auth/invite/accept", json={"token": plain, "password": NEW_PW})

    assert r.status_code == 204
    login = await sign_in(c, email, NEW_PW)
    assert login.status_code == 200
    again = await c.post("/api/v1/auth/invite/accept", json={"token": plain, "password": NEW_PW})
    assert again.status_code == 400  # single use


async def test_expired_invite_rejected(client_for):
    tenant_id, slug = await make_workspace()
    user_id, _ = await make_user(tenant_id, status="invited", password=None)
    plain = await _invite(tenant_id, user_id, hours=-1)

    r = await client_for(slug).post(
        "/api/v1/auth/invite/accept", json={"token": plain, "password": NEW_PW}
    )
    assert r.status_code == 400


async def test_invite_of_other_tenant_rejected(client_for):
    a, _ = await make_workspace()
    _, slug_b = await make_workspace()
    user_id, _ = await make_user(a, status="invited", password=None)
    plain = await _invite(a, user_id)

    r = await client_for(slug_b).post(
        "/api/v1/auth/invite/accept", json={"token": plain, "password": NEW_PW}
    )
    assert r.status_code == 400


async def test_short_password_rejected(client_for):
    tenant_id, slug = await make_workspace()
    user_id, _ = await make_user(tenant_id, status="invited", password=None)
    plain = await _invite(tenant_id, user_id)
    r = await client_for(slug).post(
        "/api/v1/auth/invite/accept", json={"token": plain, "password": "short"}
    )
    assert r.status_code == 422


async def test_forgot_unknown_email_202_and_no_mail(client_for, mailer):
    _, slug = await make_workspace()
    r = await client_for(slug).post("/api/v1/auth/password/forgot", json={"email": "x@y.com"})
    assert r.status_code == 202 and mailer.sent == []


async def test_reset_flow_changes_password_and_revokes_sessions(client_for, mailer, settings):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    old_refresh = (await sign_in(c, email, PASSWORD)).cookies["user_refresh"]

    assert (await c.post("/api/v1/auth/password/forgot", json={"email": email})).status_code == 202
    assert f"https://{slug}.{settings.base_domain}/reset-password?token=" in mailer.sent[0].body
    plain = _token_from(mailer.sent[0])

    r = await c.post("/api/v1/auth/password/reset", json={"token": plain, "password": NEW_PW})

    assert r.status_code == 204
    assert (await c.post("/api/v1/auth/refresh", headers=cookie(old_refresh))).status_code == 401
    login = await sign_in(c, email, NEW_PW)
    assert login.status_code == 200


async def test_new_reset_link_invalidates_old(client_for, mailer):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    await c.post("/api/v1/auth/password/forgot", json={"email": email})
    await c.post("/api/v1/auth/password/forgot", json={"email": email})
    first, second = _token_from(mailer.sent[0]), _token_from(mailer.sent[1])

    old = await c.post("/api/v1/auth/password/reset", json={"token": first, "password": NEW_PW})
    new = await c.post("/api/v1/auth/password/reset", json={"token": second, "password": NEW_PW})

    assert old.status_code == 400 and new.status_code == 204


async def test_reset_tokens_stored_hashed(client_for, mailer):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    await client_for(slug).post("/api/v1/auth/password/forgot", json={"email": email})
    plain = _token_from(mailer.sent[0])

    async with tenant_session(tenant_id) as s:
        hashes = (await s.scalars(select(AuthToken.token_hash))).all()
        expires = (await s.scalars(select(AuthToken.expires_at))).one()
    assert plain not in hashes
    assert expires - datetime.now(UTC) <= timedelta(minutes=60)


async def test_change_password_requires_current_and_revokes_sessions(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    login = await sign_in(c, email, PASSWORD)
    token, refresh = login.json()["access_token"], login.cookies["user_refresh"]

    wrong = await c.post(
        "/api/v1/auth/password/change",
        json={"current_password": "not-it-1234", "new_password": NEW_PW},
        headers=bearer(token),
    )
    ok = await c.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PW},
        headers=bearer(token),
    )

    assert wrong.status_code == 400 and ok.status_code == 204
    assert (await c.post("/api/v1/auth/refresh", headers=cookie(refresh))).status_code == 401


async def test_temporary_password_blocks_until_changed(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, must_change_password=True)
    c = client_for(slug)
    token = (await sign_in(c, email, PASSWORD)).json()["access_token"]

    blocked = await c.get("/api/v1/settings", headers=bearer(token))
    me = await c.get("/api/v1/auth/me", headers=bearer(token))
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"
    assert me.json()["restrictions"] == ["password_change_required"]

    await c.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PW},
        headers=bearer(token),
    )
    token = (await sign_in(c, email, NEW_PW)).json()["access_token"]
    assert (await c.get("/api/v1/settings", headers=bearer(token))).status_code == 200


async def test_disabled_user_cannot_use_reset_link(client_for, mailer):
    tenant_id, slug = await make_workspace()
    user_id, email = await make_user(tenant_id)
    c = client_for(slug)
    await c.post("/api/v1/auth/password/forgot", json={"email": email})
    async with tenant_session(tenant_id) as s:
        await s.execute(update(User).where(User.id == user_id).values(status="disabled"))

    r = await c.post(
        "/api/v1/auth/password/reset",
        json={"token": _token_from(mailer.sent[0]), "password": NEW_PW},
    )
    assert r.status_code == 400

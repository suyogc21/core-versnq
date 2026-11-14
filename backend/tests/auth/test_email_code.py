"""Email sign-in codes (Decision log #45): no authenticator app -> a 6-digit code by email,
unless this browser passed one in the last 30 days."""

import pyotp

from app.core.tenancy import tenant_session
from app.core.twofactor import new_secret
from app.modules.users.models import User
from tests.auth.conftest import bearer
from tests.factories import PASSWORD, make_user, make_workspace

LOGIN, VERIFY, RESEND = "/api/v1/auth/login", "/api/v1/auth/2fa/verify", "/api/v1/auth/2fa/resend"


def _code(mail) -> str:
    return mail.body.split("code is ")[1][:6]


async def _password(c, email, password=PASSWORD):
    return await c.post(LOGIN, json={"email": email, "password": password})


async def test_password_alone_asks_for_an_emailed_code(client_for, mailer):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, role_key="owner")
    c = client_for(slug)

    first = (await _password(c, email)).json()
    challenge = first["challenge_token"]

    assert first["two_factor_required"] is True and first["two_factor_method"] == "email"
    assert first.get("access_token") is None
    assert (await c.get("/api/v1/auth/me", headers=bearer(challenge))).status_code == 401
    assert [m.to for m in mailer.sent] == [email]
    code = _code(mailer.sent[0])
    assert code.isdigit() and len(code) == 6
    assert code not in mailer.sent[0].subject  # subjects are logged

    wrong = await c.post(VERIFY, json={"challenge_token": challenge, "code": "000000"})
    right = await c.post(VERIFY, json={"challenge_token": challenge, "code": code})
    reused = await c.post(VERIFY, json={"challenge_token": challenge, "code": code})

    assert wrong.status_code == 401 and reused.status_code == 401
    assert right.status_code == 200 and right.json()["access_token"]
    assert right.cookies["user_refresh"] and right.cookies["user_device"]


async def test_a_remembered_browser_skips_the_code_for_that_person_only(client_for, mailer):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    _, other = await make_user(tenant_id)
    c = client_for(slug)
    challenge = (await _password(c, email)).json()["challenge_token"]
    await c.post(VERIFY, json={"challenge_token": challenge, "code": _code(mailer.sent[-1])})

    again = await _password(c, email)  # same browser: the cookie is sent
    someone_else = await _password(c, other)
    new_browser = await _password(client_for(slug), email)

    assert again.json()["access_token"] and again.json()["two_factor_required"] is False
    assert someone_else.json()["two_factor_method"] == "email"
    assert new_browser.json()["two_factor_method"] == "email"


async def test_changing_the_password_forgets_remembered_browsers(client_for, mailer):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    challenge = (await _password(c, email)).json()["challenge_token"]
    token = (
        await c.post(VERIFY, json={"challenge_token": challenge, "code": _code(mailer.sent[-1])})
    ).json()["access_token"]
    new_pw = "another-pass-789"
    await c.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": new_pw},
        headers=bearer(token),
    )

    assert (await _password(c, email, new_pw)).json()["two_factor_method"] == "email"


async def test_people_with_the_app_use_it_and_get_no_email(client_for, mailer):
    secret = new_secret()
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, totp_secret=secret)
    c = client_for(slug)

    first = (await _password(c, email)).json()
    ok = await c.post(
        VERIFY, json={"challenge_token": first["challenge_token"], "code": pyotp.TOTP(secret).now()}
    )
    resend = await c.post(RESEND, json={"challenge_token": first["challenge_token"]})

    assert first["two_factor_method"] == "app" and mailer.sent == []
    assert ok.status_code == 200 and "user_device" not in ok.cookies
    assert resend.status_code == 401


async def test_invented_demo_addresses_get_no_code(client_for, mailer):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id, email="rep@acme.demo")

    r = await _password(client_for(slug), email)

    assert r.json()["access_token"] and mailer.sent == []


async def test_resend_replaces_the_code_once_a_minute(client_for, mailer):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    challenge = (await _password(c, email)).json()["challenge_token"]
    old = _code(mailer.sent[-1])

    first = await c.post(RESEND, json={"challenge_token": challenge})
    too_soon = await c.post(RESEND, json={"challenge_token": challenge})
    new = _code(mailer.sent[-1])

    assert first.status_code == 202 and too_soon.status_code == 429
    assert len(mailer.sent) == 2
    if old != new:  # one in a million they match
        assert (
            await c.post(VERIFY, json={"challenge_token": challenge, "code": old})
        ).status_code == 401
    assert (
        await c.post(VERIFY, json={"challenge_token": challenge, "code": new})
    ).status_code == 200


async def test_a_challenge_from_another_company_is_refused(client_for, mailer):
    tenant_a, slug_a = await make_workspace()
    _, slug_b = await make_workspace()
    _, email = await make_user(tenant_a)
    challenge = (await _password(client_for(slug_a), email)).json()["challenge_token"]

    r = await client_for(slug_b).post(
        VERIFY, json={"challenge_token": challenge, "code": _code(mailer.sent[-1])}
    )

    assert r.status_code == 401


async def test_disabled_person_cannot_finish_with_the_code(client_for, mailer):
    tenant_id, slug = await make_workspace()
    user_id, email = await make_user(tenant_id)
    c = client_for(slug)
    challenge = (await _password(c, email)).json()["challenge_token"]
    async with tenant_session(tenant_id) as s:
        (await s.get(User, user_id)).status = "disabled"

    r = await c.post(VERIFY, json={"challenge_token": challenge, "code": _code(mailer.sent[-1])})

    assert r.status_code == 401

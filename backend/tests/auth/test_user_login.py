import uuid

from app.core.security import create_access_token
from tests.auth.conftest import bearer, cookie
from tests.factories import PASSWORD, make_user, make_workspace, staff_headers
from tests.http_fixtures import sign_in

LOGIN, REFRESH, LOGOUT, LOGOUT_ALL, ME = (
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/logout-all",
    "/api/v1/auth/me",
)
GENERIC_401 = "Invalid email or password"


async def _login(client, email, password=PASSWORD):
    return await sign_in(client, email, password)


async def test_login_returns_tokens_and_me_works(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)

    r = await _login(c, email)
    me = await c.get(ME, headers=bearer(r.json()["access_token"]))

    assert r.status_code == 200 and r.cookies["user_refresh"]
    assert me.json()["email"] == email
    assert me.json()["role"]["key"] == "sales_user"
    assert me.json()["tenant"]["slug"] == slug


async def test_same_401_for_every_kind_of_failure(client_for):
    tenant_id, slug = await make_workspace()
    _, active = await make_user(tenant_id)
    _, invited = await make_user(tenant_id, status="invited", password=None)
    _, disabled = await make_user(tenant_id, status="disabled")
    c = client_for(slug)

    results = [
        await _login(c, active, "wrong-password-1"),
        await _login(c, "nobody@client.com"),
        await _login(c, invited),
        await _login(c, disabled),
    ]
    assert {r.status_code for r in results} == {401}
    assert {r.json()["detail"] for r in results} == {GENERIC_401}


async def test_email_is_case_insensitive(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    assert (await _login(client_for(slug), email.upper())).status_code == 200


async def test_refresh_rotates_and_reuse_revokes_all(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    s1 = (await _login(c, email)).cookies["user_refresh"]
    s2 = (await _login(c, email)).cookies["user_refresh"]

    rotated = await c.post(REFRESH, headers=cookie(s1))
    assert rotated.status_code == 200
    s1_new = rotated.cookies["user_refresh"]
    assert s1_new != s1

    assert (await c.post(REFRESH, headers=cookie(s1))).status_code == 401  # replay
    assert (await c.post(REFRESH, headers=cookie(s1_new))).status_code == 401
    assert (await c.post(REFRESH, headers=cookie(s2))).status_code == 401


async def test_logout_and_logout_all(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    first = await _login(c, email)
    second = await _login(c, email)

    assert (await c.post(LOGOUT, headers=cookie(first.cookies["user_refresh"]))).status_code == 204
    assert (await c.post(REFRESH, headers=cookie(first.cookies["user_refresh"]))).status_code == 401

    third = await _login(c, email)
    r = await c.post(LOGOUT_ALL, headers=bearer(third.json()["access_token"]))
    assert r.status_code == 204
    for resp in (second, third):
        assert (
            await c.post(REFRESH, headers=cookie(resp.cookies["user_refresh"]))
        ).status_code == 401


async def test_token_of_tenant_a_rejected_on_tenant_b_address(client_for):
    a, slug_a = await make_workspace()
    _, slug_b = await make_workspace()
    _, email = await make_user(a)
    token = (await _login(client_for(slug_a), email)).json()["access_token"]

    r = await client_for(slug_b).get(ME, headers=bearer(token))

    assert r.status_code == 401


async def test_refresh_cookie_of_tenant_a_rejected_on_tenant_b(client_for):
    a, slug_a = await make_workspace()
    _, slug_b = await make_workspace()
    _, email = await make_user(a)
    refresh = (await _login(client_for(slug_a), email)).cookies["user_refresh"]

    assert (await client_for(slug_b).post(REFRESH, headers=cookie(refresh))).status_code == 401


async def test_user_of_a_cannot_log_in_on_b(client_for):
    a, _ = await make_workspace()
    _, slug_b = await make_workspace()
    _, email = await make_user(a)
    assert (await _login(client_for(slug_b), email)).status_code == 401


async def test_staff_token_rejected_on_tenant_routes(client_for):
    _, slug = await make_workspace()
    r = await client_for(slug).get(ME, headers=await staff_headers())
    assert r.status_code == 401


async def test_user_token_for_unknown_user_rejected(client_for):
    tenant_id, slug = await make_workspace()
    token = create_access_token(uuid.uuid4(), "user", tenant_id)
    assert (await client_for(slug).get(ME, headers=bearer(token))).status_code == 401


async def test_suspending_a_tenant_blocks_existing_tokens(client_for):
    from app.core.tenancy import platform_session
    from app.platform.models import Tenant

    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)
    token = (await _login(c, email)).json()["access_token"]
    async with platform_session() as s:
        (await s.get(Tenant, tenant_id)).status = "suspended"

    assert (await c.get(ME, headers=bearer(token))).status_code == 403

from tests.factories import PASSWORD, make_user, make_workspace


async def test_sixth_failed_login_on_one_account_is_429(client_for):
    tenant_id, slug = await make_workspace()
    _, email = await make_user(tenant_id)
    c = client_for(slug)

    for _ in range(5):
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"})
        assert r.status_code == 401
    locked = await c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})

    assert locked.status_code == 429  # even the right password waits


async def test_eleventh_login_from_one_ip_in_a_minute_is_429(client_for):
    _, slug = await make_workspace()
    c = client_for(slug)
    codes = [
        (
            await c.post("/api/v1/auth/login", json={"email": f"n{i}@x.com", "password": "p" * 10})
        ).status_code
        for i in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[10] == 429


async def test_forgot_password_is_limited_per_ip(client_for, mailer):
    _, slug = await make_workspace()
    c = client_for(slug)
    codes = [
        (await c.post("/api/v1/auth/password/forgot", json={"email": "a@b.com"})).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [202] * 5 and codes[5] == 429

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


async def test_sixty_first_login_from_one_ip_in_a_minute_is_429(client_for):
    _, slug = await make_workspace()
    c = client_for(slug)
    codes = [
        (
            await c.post("/api/v1/auth/login", json={"email": f"n{i}@x.com", "password": "p" * 10})
        ).status_code
        for i in range(61)
    ]
    # Generous per address (a whole office can share one); guessing is stopped per account.
    assert codes[:60] == [401] * 60 and codes[60] == 429


async def test_forgot_password_is_limited_per_ip(client_for, mailer):
    _, slug = await make_workspace()
    c = client_for(slug)
    codes = [
        (await c.post("/api/v1/auth/password/forgot", json={"email": "a@b.com"})).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [202] * 5 and codes[5] == 429


async def test_behind_the_proxy_each_visitor_has_their_own_limit(client_for, monkeypatch):
    """The proxy's address is shared by everyone; the visitor's own address (the entry our
    proxy adds last to X-Forwarded-For) is what is limited. A faked first entry is ignored."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "trust_proxy_headers", True)
    _, slug = await make_workspace()
    c = client_for(slug)

    tries = iter(range(1000))

    async def login(xff: str) -> int:  # a new account each time: only the address limit applies
        r = await c.post(
            "/api/v1/auth/login",
            json={"email": f"n{next(tries)}@x.com", "password": "p" * 10},
            headers={"X-Forwarded-For": xff},
        )
        return r.status_code

    first = [await login(f"1.2.3.{i % 3}, 10.0.0.1") for i in range(60)]
    assert first == [401] * 60
    assert await login("9.9.9.9, 10.0.0.1") == 429  # same visitor, faked first entry
    assert await login("10.0.0.2") == 401  # another visitor is not blocked

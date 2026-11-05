from tests.factories import make_workspace

LOGIN = "/api/v1/auth/login"
BODY = {"email": "a@b.com", "password": "whatever-123"}


async def test_unknown_workspace_404(client_for):
    r = await client_for("no-such-co").post(LOGIN, json=BODY)
    assert r.status_code == 404


async def test_suspended_workspace_403(client_for):
    _, slug = await make_workspace(status="suspended")
    r = await client_for(slug).post(LOGIN, json=BODY)
    assert r.status_code == 403


async def test_host_outside_base_domain_404(client_for):
    r = await client_for("x", host="evil.example.com").post(LOGIN, json=BODY)
    assert r.status_code == 404


async def test_nested_subdomain_404(client_for, settings):
    _, slug = await make_workspace()
    r = await client_for("x", host=f"a.{slug}.{settings.base_domain}").post(LOGIN, json=BODY)
    assert r.status_code == 404


async def test_port_in_host_is_ignored(client_for, settings):
    _, slug = await make_workspace()
    r = await client_for("x", host=f"{slug}.{settings.base_domain}:8000").post(LOGIN, json=BODY)
    assert r.status_code == 401  # workspace found; credentials wrong

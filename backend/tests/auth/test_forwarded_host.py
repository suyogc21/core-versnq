from app.core.config import get_settings
from tests.factories import make_workspace

LOGIN = "/api/v1/auth/login"
BODY = {"email": "a@b.com", "password": "whatever-123"}


async def test_forwarded_host_ignored_by_default(client_for, settings):
    _, slug = await make_workspace()
    c = client_for("x", host=f"unknown.{settings.base_domain}")
    r = await c.post(
        LOGIN, json=BODY, headers={"X-Forwarded-Host": f"{slug}.{settings.base_domain}"}
    )
    assert r.status_code == 404  # still uses Host


async def test_forwarded_host_used_when_trusted(client_for, settings, monkeypatch):
    monkeypatch.setattr(get_settings(), "trust_proxy_headers", True)
    _, slug = await make_workspace()
    c = client_for("x", host="localhost:8000")
    r = await c.post(
        LOGIN, json=BODY, headers={"X-Forwarded-Host": f"{slug}.{settings.base_domain}:3000"}
    )
    assert r.status_code == 401  # workspace found via the forwarded host; credentials wrong

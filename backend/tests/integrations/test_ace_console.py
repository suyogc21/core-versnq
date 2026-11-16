"""C13 (docs/plans/ace-c13-c14-plan.md): Sign in with Core for ACE's console. A person with
ace.use gets a one-time code (2 minutes, works once); ACE's key (ace.console_login) swaps it for
who they are, in the same company only; refusals code_invalid, code_expired, code_used,
user_inactive, not_allowed; audited; nobody holds ace.console_login by default."""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.audit.models import AuditLog
from app.modules.integrations import ace_console
from app.modules.users.models import User
from tests.factories import login_as, make_custom_role, make_workspace

CODE_URL, LOGIN_URL = "/api/v1/ace/console-code", "/api/v1/ace/console-login"


@pytest.fixture
def ace_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "ace_console_url", "https://ace.example/")


async def _company(client_for):
    tenant_id, slug = await make_workspace()
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, slug, client_for(slug), admin


async def _key(c, admin, tenant_id, perms=("ace.console_login",)):
    role = await make_custom_role(tenant_id, f"ACE {uuid.uuid4().hex[:4]}", "all", perms)
    r = await c.post("/api/v1/integrations/keys", json={"name": "ACE", "role_id": str(role)},
                     headers=admin)  # fmt: skip
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['key']}"}


async def _code(c, h) -> str:
    r = await c.post(CODE_URL, headers=h)
    assert r.status_code == 200, r.text
    return parse_qs(urlparse(r.json()["url"]).query)["code"][0]


async def test_open_ace_signs_the_person_in_once_and_is_audited(client_for, ace_url):
    tenant_id, slug, c, admin = await _company(client_for)
    ace = await _key(c, admin, tenant_id)
    me = (await c.get("/api/v1/auth/me", headers=admin)).json()

    r = await c.post(CODE_URL, headers=admin)
    url = urlparse(r.json()["url"])
    code = parse_qs(url.query)["code"][0]
    ok = await c.post(LOGIN_URL, json={"code": code}, headers=ace)
    again = await c.post(LOGIN_URL, json={"code": code}, headers=ace)

    assert me["ace_console"] is True and r.json()["expires_in"] == 120
    assert (url.scheme, url.netloc, url.path) == ("https", "ace.example", "/sign-in/core")
    assert parse_qs(url.query)["company"] == [slug]
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["id"] == me["id"] and ok.json()["user"]["role"]["key"] == "admin"
    assert ok.json()["company"]["slug"] == slug and "ace.use" in ok.json()["user"]["permissions"]
    assert "token" not in ok.text
    assert again.status_code == 422 and again.json()["code"] == "code_used"
    async with tenant_session(tenant_id) as db:
        row = await db.scalar(select(AuditLog).where(AuditLog.action == "ace.console_login"))
    assert row is not None and str(row.actor_id) == me["id"]


async def test_wrong_expired_and_inactive_are_refused(client_for, ace_url, monkeypatch):
    tenant_id, _, c, admin = await _company(client_for)
    ace = await _key(c, admin, tenant_id)
    wrong = await c.post(LOGIN_URL, json={"code": "not-a-real-code-at-all"}, headers=ace)

    expired_code = await _code(c, admin)
    real_time = ace_console.time.time
    monkeypatch.setattr(ace_console.time, "time", lambda: real_time() + 121)
    expired = await c.post(LOGIN_URL, json={"code": expired_code}, headers=ace)
    monkeypatch.setattr(ace_console.time, "time", real_time)

    user_id, person = await login_as(tenant_id, "admin")
    code = await _code(c, person)
    async with tenant_session(tenant_id) as db:
        (await db.get(User, user_id)).status = "disabled"
    inactive = await c.post(LOGIN_URL, json={"code": code}, headers=ace)

    assert wrong.status_code == 422 and wrong.json()["code"] == "code_invalid"
    assert expired.status_code == 422 and expired.json()["code"] == "code_expired"
    assert inactive.status_code == 422 and inactive.json()["code"] == "user_inactive"


async def test_only_aces_key_of_the_same_company_may_swap(client_for, ace_url):
    tenant_id, _, c, admin = await _company(client_for)
    plain_key = await _key(c, admin, tenant_id, perms=("leads.create",))
    other_id, _, oc, other_admin = await _company(client_for)
    other_ace = await _key(oc, other_admin, other_id)
    code = await _code(c, admin)

    by_person = await c.post(LOGIN_URL, json={"code": code}, headers=admin)
    by_plain_key = await c.post(LOGIN_URL, json={"code": code}, headers=plain_key)
    by_other_company = await oc.post(LOGIN_URL, json={"code": code}, headers=other_ace)

    for r in (by_person, by_plain_key, by_other_company):
        assert r.status_code == 403 and r.json()["code"] == "not_allowed", r.text


async def test_who_sees_open_ace(client_for, monkeypatch):
    tenant_id, _, c, admin = await _company(client_for)
    _, sales = await login_as(tenant_id, "sales_user")
    ace = await _key(c, admin, tenant_id)

    not_set_up = await c.post(CODE_URL, headers=admin)
    monkeypatch.setattr(get_settings(), "ace_console_url", "https://ace.example")
    sales_me = (await c.get("/api/v1/auth/me", headers=sales)).json()
    sales_code = await c.post(CODE_URL, headers=sales)
    key_code = await c.post(CODE_URL, headers=ace)

    assert not_set_up.status_code == 404 and not_set_up.json()["code"] == "ace_not_configured"
    assert sales_me["ace_console"] is False and sales_code.status_code == 403
    assert key_code.status_code == 403  # a key never gets a code for itself

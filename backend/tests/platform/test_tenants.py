import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.mailer import Email, get_mailer
from app.core.tenancy import platform_session, tenant_session
from app.main import app
from app.modules.auth.models import AuthToken
from app.modules.roles.models import Role
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User
from app.platform import audit
from app.platform.models import Tenant
from app.platform.tenants import service
from tests.factories import staff_headers


class RecordingMailer:
    def __init__(self, fail: bool = False):
        self.sent: list[Email] = []
        self.fail = fail

    async def send(self, email: Email) -> None:
        if self.fail:
            raise ConnectionError("mail server down")
        self.sent.append(email)


@pytest.fixture
def mailer():
    m = RecordingMailer()
    app.dependency_overrides[get_mailer] = lambda: m
    yield m
    app.dependency_overrides.pop(get_mailer, None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def staff():
    return await staff_headers()


def payload(**over):
    slug = over.pop("slug", f"co{uuid.uuid4().hex[:8]}")
    return {
        "name": "Acme Academy",
        "slug": slug,
        "industry_pack": "edtech",
        "timezone": "Asia/Kolkata",
        "default_country": "IN",
        "owner_name": "Riya Owner",
        "owner_email": f"owner-{slug}@acme.com",
    } | over


async def _create(client, staff, **over):
    return await client.post("/platform/tenants", json=payload(**over), headers=staff)


async def test_provision_creates_tenant_settings_roles_and_invited_owner(client, staff, mailer):
    r = await _create(client, staff)
    assert r.status_code == 201
    tenant_id = uuid.UUID(r.json()["id"])

    async with tenant_session(tenant_id) as s:
        settings = await s.get(TenantSettings, tenant_id)
        roles = {r.key: r.scope for r in (await s.scalars(select(Role))).all()}
        owner = (await s.scalars(select(User))).one()
        owner_role = await s.get(Role, owner.role_id)

    assert settings.timezone == "Asia/Kolkata" and settings.default_country == "IN"
    assert roles == {
        "owner": "all",
        "admin": "all",
        "sales_manager": "team",
        "sales_user": "own",
        "finance": "own",
    }
    assert owner.status == "invited" and owner.password_hash is None
    assert owner_role.key == "owner"


async def test_edtech_pack_labels_applied(client, staff, mailer):
    tenant_id = uuid.UUID((await _create(client, staff)).json()["id"])
    async with tenant_session(tenant_id) as s:
        settings = await s.get(TenantSettings, tenant_id)
    assert settings.labels["lead"]["singular"] == "Student"


async def test_owner_invite_email_links_to_slug_subdomain(client, staff, mailer, settings):
    r = await _create(client, staff, slug="acme-invite")

    assert r.json()["invite_sent"] is True
    assert len(mailer.sent) == 1
    assert mailer.sent[0].to == "owner-acme-invite@acme.com"
    assert f"https://acme-invite.{settings.base_domain}/invite?token=" in mailer.sent[0].body


async def test_invite_token_stored_hashed_and_expires_in_72h(client, staff, mailer):
    tenant_id = uuid.UUID((await _create(client, staff)).json()["id"])
    plain = mailer.sent[0].body.split("token=")[1].split()[0]

    async with tenant_session(tenant_id) as s:
        token = (await s.scalars(select(AuthToken))).one()

    assert token.kind == "invite" and token.token_hash != plain
    remaining = token.expires_at - datetime.now(UTC)
    assert timedelta(hours=71) < remaining <= timedelta(hours=72)


async def test_duplicate_slug_rejected_409(client, staff, mailer):
    await _create(client, staff, slug="dupe-co")
    r = await _create(client, staff, slug="dupe-co")
    assert r.status_code == 409


@pytest.mark.parametrize(
    "field,value",
    [
        ("slug", "Admin"),
        ("industry_pack", "nope"),
        ("timezone", "Mars/Base"),
        ("default_country", "XX1"),
    ],
)
async def test_invalid_input_rejected_422(client, staff, mailer, field, value):
    r = await _create(client, staff, **{field: value})
    assert r.status_code == 422


async def test_failure_midway_leaves_nothing(client, staff, mailer, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_seed_roles", boom)

    with pytest.raises(RuntimeError):
        await _create(client, staff, slug="half-made")

    async with platform_session() as s:
        assert await s.scalar(select(func.count()).where(Tenant.slug == "half-made")) == 0


async def test_mail_failure_keeps_tenant_and_reports_invite_not_sent(client, staff):
    app.dependency_overrides[get_mailer] = lambda: RecordingMailer(fail=True)
    try:
        r = await _create(client, staff)
    finally:
        app.dependency_overrides.pop(get_mailer, None)

    assert r.status_code == 201
    assert r.json()["invite_sent"] is False


async def test_resend_invite_replaces_old_token(client, staff, mailer):
    tenant_id = (await _create(client, staff)).json()["id"]

    r = await client.post(f"/platform/tenants/{tenant_id}/resend-owner-invite", headers=staff)

    assert r.status_code == 200 and r.json()["invite_sent"] is True
    async with tenant_session(uuid.UUID(tenant_id)) as s:
        tokens = (await s.scalars(select(AuthToken).order_by(AuthToken.created_at))).all()
    assert len(tokens) == 2
    assert tokens[0].used_at is not None  # old link no longer works
    assert tokens[1].used_at is None


async def test_suspend_and_reactivate_change_status(client, staff, mailer):
    tenant_id = (await _create(client, staff)).json()["id"]

    r1 = await client.post(f"/platform/tenants/{tenant_id}/suspend", headers=staff)
    r2 = await client.post(f"/platform/tenants/{tenant_id}/reactivate", headers=staff)

    assert r1.json()["status"] == "suspended"
    assert r2.json()["status"] == "active"


async def test_list_and_get_tenants(client, staff, mailer):
    created = (await _create(client, staff, name="Listable Co")).json()

    listed = await client.get("/platform/tenants", params={"q": "Listable"}, headers=staff)
    got = await client.get(f"/platform/tenants/{created['id']}", headers=staff)

    assert created["id"] in [t["id"] for t in listed.json()]
    assert got.json()["slug"] == created["slug"]


async def test_rename_tenant(client, staff, mailer):
    tenant_id = (await _create(client, staff)).json()["id"]
    r = await client.patch(
        f"/platform/tenants/{tenant_id}", json={"name": "New Name"}, headers=staff
    )
    assert r.json()["name"] == "New Name"


async def test_every_staff_write_creates_platform_audit_row(client, staff, mailer):
    tenant_id = (await _create(client, staff)).json()["id"]
    await client.patch(f"/platform/tenants/{tenant_id}", json={"name": "Renamed"}, headers=staff)
    await client.post(f"/platform/tenants/{tenant_id}/suspend", headers=staff)
    await client.post(f"/platform/tenants/{tenant_id}/reactivate", headers=staff)
    await client.post(f"/platform/tenants/{tenant_id}/resend-owner-invite", headers=staff)

    r = await client.get("/platform/audit", params={"target_id": tenant_id}, headers=staff)
    actions = sorted(row["action"] for row in r.json())

    assert actions == sorted(
        [
            "tenant.created",
            "tenant.updated",
            "tenant.suspended",
            "tenant.reactivated",
            "tenant.owner_invite_resent",
        ]
    )


async def test_audit_rows_never_contain_tokens(client, staff, mailer):
    tenant_id = (await _create(client, staff)).json()["id"]
    plain = mailer.sent[0].body.split("token=")[1].split()[0]
    r = await client.get("/platform/audit", params={"target_id": tenant_id}, headers=staff)
    assert plain not in r.text


async def test_audit_log_is_append_only():
    async with platform_session() as s:
        await audit.record(s, staff_id=None, action="test.event", target_type="t", target_id=None)

    with pytest.raises(DBAPIError, match="permission denied"):
        async with platform_session() as s:
            await s.execute(text("UPDATE platform_audit_log SET action = 'tampered'"))


async def test_tenant_routes_require_staff_token(client, mailer):
    assert (await client.get("/platform/tenants")).status_code == 401
    assert (await client.post("/platform/tenants", json=payload())).status_code == 401


async def test_unknown_tenant_id_404(client, staff):
    r = await client.get(f"/platform/tenants/{uuid.uuid4()}", headers=staff)
    assert r.status_code == 404

import uuid

from sqlalchemy import select, text

from app.core.tenancy import tenant_session
from app.modules.audit.models import AuditLog
from tests.factories import login_as, make_workspace
from tests.http_fixtures import sign_in

INVITE = "/api/v1/users"


async def _role_id(c, headers, key):
    return next(
        r["id"] for r in (await c.get("/api/v1/roles", headers=headers)).json() if r["key"] == key
    )


async def test_invite_creates_invited_user_and_emails_workspace_link(ws, mailer, settings):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    role = await _role_id(c, admin, "sales_user")

    r = await c.post(
        INVITE,
        json={"email": "new.rep@client.com", "name": "New Rep", "role_id": role},
        headers=admin,
    )

    assert r.status_code == 201 and r.json()["status"] == "invited"
    assert r.json()["invite_sent"] is True
    assert mailer.sent[0].to == "new.rep@client.com"
    assert f".{settings.base_domain}/invite?token=" in mailer.sent[0].body


async def test_duplicate_email_409(ws, mailer):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    role = await _role_id(c, admin, "sales_user")
    body = {"email": "Same@client.com", "name": "A", "role_id": role}
    await c.post(INVITE, json=body, headers=admin)
    r = await c.post(INVITE, json=body | {"email": "same@CLIENT.com"}, headers=admin)
    assert r.status_code == 409


async def test_cannot_change_own_role(ws):
    tenant_id, c = ws
    me, admin = await login_as(tenant_id, "admin")
    role = await _role_id(c, admin, "sales_user")
    r = await c.patch(f"/api/v1/users/{me}", json={"role_id": role}, headers=admin)
    assert r.status_code == 403


async def test_admin_cannot_touch_owner_but_owner_can(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    owner_2, _ = await login_as(tenant_id, "owner")
    _, owner = await login_as(tenant_id, "owner")

    by_admin = await c.post(f"/api/v1/users/{owner_2}/disable", headers=admin)
    by_owner = await c.post(f"/api/v1/users/{owner_2}/disable", headers=owner)
    assert by_admin.status_code == 403 and by_owner.status_code == 200


async def test_admin_cannot_assign_owner_role(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep, _ = await login_as(tenant_id, "sales_user")
    owner_role = await _role_id(c, admin, "owner")
    r = await c.patch(f"/api/v1/users/{rep}", json={"role_id": owner_role}, headers=admin)
    assert r.status_code == 403


async def test_cannot_assign_role_with_more_permissions_than_you(ws):
    tenant_id, c = ws
    from tests.factories import make_custom_role

    limited = await make_custom_role(tenant_id, "Lead", permissions=("users.manage", "users.read"))
    _, headers = await login_as(tenant_id, None, role_id=limited)
    rep, _ = await login_as(tenant_id, "sales_user")
    admin_role = await _role_id(c, (await login_as(tenant_id, "admin"))[1], "admin")

    r = await c.patch(f"/api/v1/users/{rep}", json={"role_id": admin_role}, headers=headers)
    assert r.status_code == 403


async def test_last_active_owner_protected(ws):
    tenant_id, c = ws
    owner_a, a_h = await login_as(tenant_id, "owner")
    owner_b, _ = await login_as(tenant_id, "owner")
    role = await _role_id(c, a_h, "admin")

    first = await c.patch(f"/api/v1/users/{owner_b}", json={"role_id": role}, headers=a_h)
    assert first.status_code == 200  # two owners → one may be demoted
    # now owner_a is the only owner; another owner is needed to act on them, so assert via service
    from app.modules.users.service import LastOwner, ensure_not_last_owner

    async with tenant_session(tenant_id) as s:
        try:
            await ensure_not_last_owner(s, owner_a)
            raised = False
        except LastOwner:
            raised = True
    assert raised


async def test_disable_revokes_sessions_and_blocks_login(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    role = await _role_id(c, admin, "sales_user")
    from tests.factories import PASSWORD, make_user

    rep, email = await make_user(tenant_id)
    login = await sign_in(c, email, PASSWORD)
    refresh = login.cookies["user_refresh"]

    assert (await c.post(f"/api/v1/users/{rep}/disable", headers=admin)).json()["status"] == (
        "disabled"
    )
    assert (
        await c.post("/api/v1/auth/refresh", headers={"Cookie": f"user_refresh={refresh}"})
    ).status_code == 401
    assert (await sign_in(c, email, PASSWORD)).status_code == 401
    enabled = await c.post(f"/api/v1/users/{rep}/enable", headers=admin)
    assert enabled.json()["status"] == "active" and role


async def test_cannot_disable_yourself(ws):
    tenant_id, c = ws
    me, admin = await login_as(tenant_id, "admin")
    assert (await c.post(f"/api/v1/users/{me}/disable", headers=admin)).status_code == 403


async def test_temporary_password_restricts_user(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    from tests.factories import make_user

    rep, email = await make_user(tenant_id)
    r = await c.post(f"/api/v1/users/{rep}/temporary-password", headers=admin)
    temp = r.json()["temporary_password"]

    login = await sign_in(c, email, temp)
    me = await c.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert r.status_code == 200 and len(temp) >= 12
    assert me.json()["restrictions"] == ["password_change_required"]


async def test_other_tenant_user_id_is_404(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    other, _ = await make_workspace()
    stranger, _ = await login_as(other, "sales_user")

    assert (await c.get(f"/api/v1/users/{stranger}", headers=admin)).status_code == 404
    assert (
        await c.patch(f"/api/v1/users/{stranger}", json={"name": "x"}, headers=admin)
    ).status_code == 404
    assert (await c.get(f"/api/v1/users/{uuid.uuid4()}", headers=admin)).status_code == 404


async def test_other_tenant_role_id_rejected(ws, client_for):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep, _ = await login_as(tenant_id, "sales_user")
    other, other_slug = await make_workspace()
    _, other_admin = await login_as(other, "admin")
    foreign_role = await _role_id(client_for(other_slug), other_admin, "admin")
    r = await c.patch(f"/api/v1/users/{rep}", json={"role_id": foreign_role}, headers=admin)
    assert r.status_code == 422


async def test_every_admin_write_is_audited_without_secrets(ws, mailer):
    import pytest
    from sqlalchemy.exc import DBAPIError

    from tests.factories import make_user

    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    role = await _role_id(c, admin, "sales_user")
    invited = (
        await c.post(INVITE, json={"email": "a@c.com", "name": "A", "role_id": role}, headers=admin)
    ).json()["id"]
    await c.patch(f"/api/v1/users/{invited}", json={"name": "B"}, headers=admin)
    active, _ = await make_user(tenant_id)
    temp = (await c.post(f"/api/v1/users/{active}/temporary-password", headers=admin)).json()

    async with tenant_session(tenant_id) as s:
        rows = (
            await s.scalars(
                select(AuditLog).where(AuditLog.entity_id.in_([uuid.UUID(invited), active]))
            )
        ).all()
    actions = sorted(r.action for r in rows)
    blob = str([(r.before, r.after) for r in rows])

    assert actions == sorted(["user.invited", "user.updated", "user.temporary_password_set"])
    assert temp["temporary_password"] not in blob and "token" not in blob
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(tenant_id) as s:
            await s.execute(text("DELETE FROM audit_log"))


async def test_temporary_password_refused_for_invited_user(ws, mailer):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    role = await _role_id(c, admin, "sales_user")
    invited = (
        await c.post(INVITE, json={"email": "i@c.com", "name": "I", "role_id": role}, headers=admin)
    ).json()["id"]
    r = await c.post(f"/api/v1/users/{invited}/temporary-password", headers=admin)
    assert r.status_code == 409


async def test_sales_manager_cannot_edit_users(ws):
    tenant_id, c = ws
    _, mgr = await login_as(tenant_id, "sales_manager")
    rep, _ = await login_as(tenant_id, "sales_user")
    assert (
        await c.patch(f"/api/v1/users/{rep}", json={"name": "X"}, headers=mgr)
    ).status_code == 403

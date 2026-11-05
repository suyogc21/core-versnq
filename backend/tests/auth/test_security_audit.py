"""Self-service security actions leave an audit trail (never with secrets)."""

import pyotp
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.audit.models import AuditLog
from tests.auth.conftest import bearer
from tests.factories import PASSWORD, make_user, make_workspace

NEW_PW = "another-good-pass-9"


async def _actions(tenant_id, user_id):
    async with tenant_session(tenant_id) as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.entity_id == user_id))).all()
    return sorted(r.action for r in rows), str([(r.before, r.after) for r in rows])


async def test_password_change_and_2fa_enable_are_audited(client_for):
    tenant_id, slug = await make_workspace()
    user_id, email = await make_user(tenant_id, role_key="owner")
    c = client_for(slug)
    token = (
        await c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).json()["access_token"]
    secret = (await c.post("/api/v1/auth/2fa/setup", headers=bearer(token))).json()["secret"]
    await c.post(
        "/api/v1/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=bearer(token)
    )
    await c.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PW},
        headers=bearer(token),
    )

    actions, blob = await _actions(tenant_id, user_id)
    assert actions == ["user.2fa_enabled", "user.password_changed"]
    assert secret not in blob and NEW_PW not in blob


async def test_reset_and_invite_accept_are_audited(client_for, mailer):
    from datetime import timedelta

    from app.modules.auth.service import issue_link_token

    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    invited_id, _ = await make_user(tenant_id, status="invited", password=None)
    async with tenant_session(tenant_id) as s:
        plain = await issue_link_token(s, tenant_id, invited_id, "invite", timedelta(hours=1))
    await c.post("/api/v1/auth/invite/accept", json={"token": plain, "password": NEW_PW})

    active_id, email = await make_user(tenant_id)
    await c.post("/api/v1/auth/password/forgot", json={"email": email})
    reset = mailer.sent[0].body.split("token=")[1].split()[0]
    await c.post("/api/v1/auth/password/reset", json={"token": reset, "password": NEW_PW})

    assert (await _actions(tenant_id, invited_id))[0] == ["user.invite_accepted"]
    assert (await _actions(tenant_id, active_id))[0] == ["user.password_reset"]

"""Phone notifications (calls plan, step C2): a person turns them on for a browser/phone; every
new in-app notification goes to their phones once; nothing old is sent; a phone that's gone is
forgotten; another company can't touch the subscription; nothing happens until the server has
its keys."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.crm.models import Notification
from app.modules.crm.notify import notify
from app.modules.push import service as P
from app.modules.push.models import PushSubscription
from tests.factories import login_as, make_workspace

SUB = {
    "endpoint": "https://push.example.com/send/abc123",
    "keys": {"p256dh": "B" * 87, "auth": "A" * 22},
}


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(get_settings(), "vapid_public_key", "BPublicKeyForTests")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private-key-for-tests")


@pytest.fixture
def sent(monkeypatch):
    out: list[tuple[str, dict]] = []

    async def fake(sub, payload):
        out.append((sub.endpoint, payload))
        return None if "gone" in sub.endpoint else True

    monkeypatch.setattr(P, "deliver", fake)
    return out


async def test_off_until_the_server_has_keys(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "sales_user")
    assert (await c.get("/api/v1/push/key", headers=h)).json() == {"public_key": None}
    r = await c.post("/api/v1/push/subscriptions", json=SUB, headers=h)
    assert r.status_code == 404 and r.json()["code"] == "push_not_configured"


async def test_a_new_notification_goes_to_the_phone_once(ws, keys, sent):
    tenant_id, c = ws
    user_id, h = await login_as(tenant_id, "sales_user")
    on = await c.post("/api/v1/push/subscriptions", json=SUB, headers=h)
    devices = (await c.get("/api/v1/push/subscriptions", headers=h)).json()
    async with tenant_session(tenant_id) as db:
        await notify(db, tenant_id, [user_id], "missed_call", "Missed call from Asha")
        hour_ago = datetime.now(UTC) - timedelta(hours=1)
        db.add(Notification(tenant_id=tenant_id, user_id=user_id, kind="lead_assigned",
                            title="Old one", created_at=hour_ago))  # fmt: skip
    async with tenant_session(tenant_id) as db:
        first = await P.send_pending(db)
    async with tenant_session(tenant_id) as db:
        second = await P.send_pending(db)

    assert on.status_code == 204 and devices == {"devices": 1}
    assert first == 1 and second == 0
    assert sent == [(SUB["endpoint"], {"title": "Missed call from Asha", "url": "/",
                                       "tag": sent[0][1]["tag"]})]  # fmt: skip


async def test_a_phone_that_is_gone_is_forgotten_and_turning_off_works(ws, keys, sent):
    tenant_id, c = ws
    user_id, h = await login_as(tenant_id, "sales_user")
    gone = {**SUB, "endpoint": "https://push.example.com/send/gone-1"}
    await c.post("/api/v1/push/subscriptions", json=gone, headers=h)
    await c.post("/api/v1/push/subscriptions", json=SUB, headers=h)
    async with tenant_session(tenant_id) as db:
        await notify(db, tenant_id, [user_id], "task_due", "Call Ravi now")
    async with tenant_session(tenant_id) as db:
        await P.send_pending(db)
    left = (await c.get("/api/v1/push/subscriptions", headers=h)).json()
    off = await c.post("/api/v1/push/subscriptions/off", json={"endpoint": SUB["endpoint"]},
                       headers=h)  # fmt: skip

    assert len(sent) == 2 and left == {"devices": 1}  # the gone phone was removed
    assert off.status_code == 204
    assert (await c.get("/api/v1/push/subscriptions", headers=h)).json() == {"devices": 0}


async def test_another_company_cannot_touch_it(ws, keys, client_for):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "sales_user")
    await c.post("/api/v1/push/subscriptions", json=SUB, headers=h)
    other_id, other_slug = await make_workspace()
    _, oh = await login_as(other_id, "sales_user")
    oc = client_for(other_slug)

    await oc.post("/api/v1/push/subscriptions/off", json={"endpoint": SUB["endpoint"]}, headers=oh)
    same_browser = await oc.post("/api/v1/push/subscriptions", json=SUB, headers=oh)

    assert same_browser.status_code == 204  # one browser can be signed in to two companies
    assert (await c.get("/api/v1/push/subscriptions", headers=h)).json() == {"devices": 1}
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(func.count()).select_from(PushSubscription)) == 1

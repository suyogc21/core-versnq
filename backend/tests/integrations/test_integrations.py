"""Milestone 4 (Decision log #37): API keys, webhooks, logs and the lead endpoints ACE uses."""

import gzip
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.crm.models import Notification
from app.modules.integrations import keys as K
from app.modules.integrations import logs as LG
from app.modules.integrations import webhooks as W
from app.modules.integrations.models import ApiRequestLog, WebhookDelivery, WebhookEndpoint
from app.modules.roles.models import Role
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

HOOK = "https://hooks.example.com/versnq"


@pytest.fixture(autouse=True)
def files_dir(tmp_path):
    s = get_settings()
    old = s.files_dir
    s.files_dir = str(tmp_path / "files")
    yield
    s.files_dir = old


class Receiver:
    """Stands in for the customer's server."""

    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status, text="ok")


@pytest.fixture
def receiver(monkeypatch):
    r = Receiver()
    monkeypatch.setattr(
        W, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(r.handler))
    )
    monkeypatch.setattr(W, "check_url", lambda url: url)  # no DNS in tests
    return r


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, client_for(slug), admin


async def _role_id(tenant_id, key):
    async with tenant_session(tenant_id) as db:
        return await db.scalar(select(Role.id).where(Role.key == key))


async def _key(c, admin, tenant_id, role="admin", name=None) -> dict:
    r = await c.post(
        "/api/v1/integrations/keys",
        json={
            "name": name or f"Key {uuid.uuid4().hex[:6]}",
            "role_id": str(await _role_id(tenant_id, role)),
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def bearer(key: dict) -> dict:
    return {"Authorization": f"Bearer {key['key']}"}


# ---------- keys ----------
async def test_key_works_shown_once_and_revoke_is_instant(ws):
    tenant_id, c, admin = ws
    key = await _key(c, admin, tenant_id)
    assert key["key"].startswith("vq_live_") and key["role_name"] == "Admin"
    listed = (await c.get("/api/v1/integrations/keys", headers=admin)).json()
    assert "key" not in listed[0] and listed[0]["prefix"] == key["key"][:14]
    assert (await c.get("/api/v1/leads", headers=bearer(key))).status_code == 200
    r = await c.post(f"/api/v1/integrations/keys/{key['id']}/revoke", headers=admin)
    assert r.json()["revoked_at"]
    assert (await c.get("/api/v1/leads", headers=bearer(key))).status_code == 401


async def test_key_only_sees_its_own_company(ws, client_for):
    tenant_id, c, admin = ws
    key = await _key(c, admin, tenant_id)
    other_id, other_slug = await make_workspace()
    other = client_for(other_slug)
    assert (await other.get("/api/v1/leads", headers=bearer(key))).status_code == 401


async def test_key_follows_its_role(ws):
    tenant_id, c, admin = ws
    _, sources = await setup_ids(c, admin)
    assert (await new_lead(c, admin, sources["Website"], phone="98765 11111")).status_code == 201
    rep = await _key(c, admin, tenant_id, role="sales_user")
    rows = (await c.get("/api/v1/leads", headers=bearer(rep))).json()["items"]
    assert rows == []  # a Sales User key sees only leads its own user owns
    assert (await c.get("/api/v1/integrations/keys", headers=bearer(rep))).status_code == 403
    r = await c.post(
        "/api/v1/integrations/keys",
        json={"name": "Owner key", "role_id": str(await _role_id(tenant_id, "owner"))},
        headers=admin,
    )
    assert r.status_code == 422


async def test_a_key_cannot_manage_keys_even_as_admin(ws):
    tenant_id, c, admin = ws
    key = await _key(c, admin, tenant_id)
    assert (await c.get("/api/v1/integrations/keys", headers=bearer(key))).status_code == 403


async def test_integration_users_are_not_team_members_and_cannot_sign_in(ws):
    tenant_id, c, admin = ws
    await _key(c, admin, tenant_id, name="Website")
    users = (await c.get("/api/v1/users", headers=admin)).json()
    names = [u["name"] for u in (users["items"] if isinstance(users, dict) else users)]
    assert not any(n.startswith("API ·") for n in names)


async def test_rate_limit_answers_429_with_retry_after(ws, monkeypatch):
    tenant_id, c, admin = ws
    monkeypatch.setattr(K, "RATE_LIMIT", 3)
    key = await _key(c, admin, tenant_id)
    codes = [(await c.get("/api/v1/leads", headers=bearer(key))).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    r = await c.get("/api/v1/leads", headers=bearer(key))
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 0


async def test_every_key_request_is_in_the_api_log(ws):
    tenant_id, c, admin = ws
    key = await _key(c, admin, tenant_id)
    await c.get("/api/v1/leads?limit=5", headers=bearer(key))
    await c.get(f"/api/v1/leads/{uuid.uuid4()}", headers=bearer(key))
    log = (await c.get(f"/api/v1/integrations/api-log?key_id={key['id']}", headers=admin)).json()
    assert [r["status"] for r in log] == [404, 200]
    assert log[1]["path"] == "/api/v1/leads?limit=5"
    errors = (await c.get("/api/v1/integrations/api-log?errors_only=true", headers=admin)).json()
    assert [r["status"] for r in errors] == [404]


# ---------- webhooks ----------
async def _hook(c, admin, events=("lead.created",)) -> dict:
    r = await c.post(
        "/api/v1/integrations/webhooks",
        json={"name": "CRM sync", "url": HOOK, "events": list(events)},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_at_most_ten_webhooks(ws, monkeypatch):
    _, c, admin = ws
    from app.modules.integrations import router as R

    monkeypatch.setattr(R, "MAX_WEBHOOKS", 2)
    await _hook(c, admin)
    await _hook(c, admin)
    r = await c.post(
        "/api/v1/integrations/webhooks",
        json={"name": "Third", "url": HOOK, "events": ["*"]},
        headers=admin,
    )
    assert r.status_code == 422 and "up to 2" in r.json()["detail"]


async def test_private_addresses_are_refused(ws):
    _, c, admin = ws
    for url in ("http://hooks.example.com", "https://127.0.0.1/x", "https://localhost/x"):
        r = await c.post(
            "/api/v1/integrations/webhooks",
            json={"name": "x", "url": url, "events": ["*"]},
            headers=admin,
        )
        assert r.status_code == 422, url


async def test_event_becomes_a_signed_delivery_only_for_endpoints_that_asked(ws, receiver):
    tenant_id, c, admin = ws
    hook = await _hook(c, admin, events=["lead.created"])
    other = await _hook(c, admin, events=["deal.won"])
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], phone="98765 22222")).json()
    await W.run_all([tenant_id])
    assert len(receiver.calls) == 1
    req = receiver.calls[0]
    body = req.content.decode()
    ts = req.headers["x-versnq-timestamp"]
    good = hmac.new(hook["secret"].encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    assert req.headers["x-versnq-signature"] == f"sha256={good}"
    assert req.headers["x-versnq-event"] == "lead.created"
    sent = json.loads(body)
    assert sent["type"] == "lead.created" and sent["data"]["lead_id"] == lead["id"]
    log = (await c.get("/api/v1/integrations/deliveries", headers=admin)).json()
    assert {d["endpoint_id"] for d in log} == {hook["id"]} and log[0]["status"] == "ok"
    assert other["id"] not in {d["endpoint_id"] for d in log}
    await W.run_all([tenant_id])
    assert len(receiver.calls) == 1  # never sent twice


async def test_retries_follow_the_schedule_then_fail(ws, receiver):
    tenant_id, c, admin = ws
    receiver.status = 500
    await _hook(c, admin)
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"], phone="98765 33333")
    await W.run_all([tenant_id])
    async with tenant_session(tenant_id) as db:
        d = await db.scalar(select(WebhookDelivery))
        assert d.attempts == 1 and d.status == "pending" and d.last_status_code == 500
        gap = (d.next_try_at - datetime.now(UTC)).total_seconds()
        assert 50 < gap <= 60
    for _ in range(2, W.MAX_TRIES + 1):
        async with tenant_session(tenant_id) as db:
            await db.execute(update(WebhookDelivery).values(next_try_at=datetime.now(UTC)))
        await W.send_due(tenant_id)
    async with tenant_session(tenant_id) as db:
        d = await db.scalar(select(WebhookDelivery))
        assert d.attempts == 8 and d.status == "failed" and d.next_try_at is None
    assert len(receiver.calls) == 8


async def test_endpoint_failing_three_days_is_switched_off_and_admins_told(ws, receiver):
    tenant_id, c, admin = ws
    receiver.status = 503
    hook = await _hook(c, admin)
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"], phone="98765 44444")
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(WebhookEndpoint).values(
                failing_since=datetime.now(UTC) - timedelta(days=3, minutes=1)
            )
        )
    await W.run_all([tenant_id])
    async with tenant_session(tenant_id) as db:
        ep = await db.get(WebhookEndpoint, uuid.UUID(hook["id"]))
        assert ep.is_active is False and "failing since" in ep.switched_off_reason
        titles = (await db.scalars(select(Notification.title))).all()
        assert any("Webhook switched off" in t for t in titles)
    r = await c.patch(
        f"/api/v1/integrations/webhooks/{hook['id']}", json={"is_active": True}, headers=admin
    )
    assert r.json()["is_active"] is True and r.json()["failing_since"] is None


async def test_send_test_and_resend(ws, receiver):
    tenant_id, c, admin = ws
    hook = await _hook(c, admin)
    r = await c.post(f"/api/v1/integrations/webhooks/{hook['id']}/test", headers=admin)
    assert r.json()["status"] == "ok" and json.loads(r.json()["body"])["type"] == "ping"
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"], phone="98765 55555")
    await W.run_all([tenant_id])
    real = [
        d
        for d in (await c.get("/api/v1/integrations/deliveries", headers=admin)).json()
        if d["event_type"] != "ping"
    ][0]
    again = await c.post(f"/api/v1/integrations/deliveries/{real['id']}/resend", headers=admin)
    assert again.status_code == 200 and again.json()["status"] == "pending"
    await W.run_all([tenant_id])
    assert len(receiver.calls) == 3
    secret = (
        await c.get(f"/api/v1/integrations/webhooks/{hook['id']}/secret", headers=admin)
    ).json()
    assert secret["secret"] == hook["secret"]


async def test_events_with_no_endpoint_are_just_marked_handled(ws, receiver):
    tenant_id, c, admin = ws
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"], phone="98765 66666")
    await W.run_all([tenant_id])
    await _hook(c, admin)  # added later: old events are not sent to it
    await W.run_all([tenant_id])
    assert receiver.calls == []


async def test_another_company_never_gets_our_deliveries(ws, client_for, receiver):
    tenant_id, c, admin = ws
    await _hook(c, admin)
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)
    assert (await oc.get("/api/v1/integrations/webhooks", headers=other_admin)).json() == []
    assert (await oc.get("/api/v1/integrations/deliveries", headers=other_admin)).json() == []


# ---------- logs archive ----------
async def test_logs_older_than_30_days_move_to_an_archive_file(ws):
    tenant_id, c, admin = ws
    key = await _key(c, admin, tenant_id)
    await c.get("/api/v1/leads", headers=bearer(key))
    old = datetime.now(UTC) - timedelta(days=31)
    async with tenant_session(tenant_id) as db:
        await db.execute(update(ApiRequestLog).values(at=old))
    done = await LG.archive_tenant(tenant_id)
    assert done["api"] == 1
    assert (await c.get("/api/v1/integrations/api-log", headers=admin)).json() == []
    files = (await c.get("/api/v1/integrations/archives", headers=admin)).json()
    assert files[0]["kind"] == "api" and files[0]["month"] == f"{old:%Y-%m}"
    r = await c.get(f"/api/v1/integrations/archives/{files[0]['name']}", headers=admin)
    rows = [json.loads(x) for x in gzip.decompress(r.content).decode().splitlines()]
    assert rows[0]["path"] == "/api/v1/leads" and rows[0]["status"] == 200
    bad = await c.get("/api/v1/integrations/archives/..%2F..%2Fsecret.jsonl.gz", headers=admin)
    assert bad.status_code == 404


async def test_archive_files_older_than_12_months_are_deleted(ws):
    tenant_id, _, _ = ws
    folder = LG.folder(tenant_id)
    folder.mkdir(parents=True)
    today = datetime.now(UTC).date()
    old = f"{today.year - 2}-01"
    (folder / f"api-{old}.jsonl.gz").write_bytes(gzip.compress(b"{}\n"))
    (folder / f"api-{today:%Y-%m}.jsonl.gz").write_bytes(gzip.compress(b"{}\n"))
    assert LG._drop_old_files(tenant_id, today) == 1
    assert [a["month"] for a in LG.archives(tenant_id)] == [f"{today:%Y-%m}"]


# ---------- lead endpoints (ACE) ----------
async def test_upsert_creates_then_finds_by_phone_or_email(ws):
    tenant_id, c, admin = ws
    key = await _key(c, admin, tenant_id, name="ACE")
    body = {
        "phones": ["98765 77777"],
        "emails": ["neha@example.com"],
        "first_name": "Neha",
        "source": "website",
        "origin": "outbound_ace",
        "intent": {"intent": "hot", "reason": "Asked for pricing"},
        "conversation": {
            "channel": "whatsapp",
            "summary": "Wants a demo next week",
            "external_id": "conv-1",
            "messages": [
                {"sender": "us", "text": "Hi Neha, still interested?"},
                {"sender": "lead", "text": "Yes, send pricing"},
            ],
        },
    }
    first = await c.post("/api/v1/leads/upsert", json=body, headers=bearer(key))
    assert first.status_code == 200, first.text
    assert first.json()["result"] == "created"
    lead_id = first.json()["lead_id"]
    by_email = await c.post(
        "/api/v1/leads/upsert",
        json={"emails": ["NEHA@example.com"], "source": "Website"},
        headers=bearer(key),
    )
    by_phone = await c.post(
        "/api/v1/leads/upsert",
        json={"phones": ["+91 98765 77777"], "source": "Website"},
        headers=bearer(key),
    )
    assert (
        by_email.json()
        == by_phone.json()
        == {"result": "existing", "lead_id": lead_id, "name": "Neha"}
    )
    lead = (await c.get(f"/api/v1/leads/{lead_id}", headers=admin)).json()
    assert lead["intent"] == "hot"
    timeline = (await c.get(f"/api/v1/leads/{lead_id}/activities", headers=admin)).json()
    items = timeline["items"] if isinstance(timeline, dict) else timeline
    kinds = [a["type_key"] for a in items]
    assert "api_conversation" in kinds and "intent_changed" in kinds
    conv = next(a for a in items if a["type_key"] == "api_conversation")
    assert conv["summary"] == "WhatsApp conversation · 2 messages"
    assert conv["actor_name"] == "API · ACE"


async def test_conversation_retry_is_safe_and_intent_emits_event(ws):
    tenant_id, c, admin = ws
    key = await _key(c, admin, tenant_id, name="ACE")
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], phone="98765 88888")).json()
    conv = {
        "channel": "email",
        "external_id": "t-9",
        "messages": [{"sender": "lead", "text": "Hello"}],
    }
    a = await c.post(f"/api/v1/leads/{lead['id']}/conversation", json=conv, headers=bearer(key))
    b = await c.post(f"/api/v1/leads/{lead['id']}/conversation", json=conv, headers=bearer(key))
    assert a.json()["created"] is True and b.json() == {
        "activity_id": a.json()["activity_id"],
        "created": False,
    }
    i1 = await c.put(
        f"/api/v1/leads/{lead['id']}/intent", json={"intent": "warm"}, headers=bearer(key)
    )
    i2 = await c.put(
        f"/api/v1/leads/{lead['id']}/intent", json={"intent": "warm"}, headers=bearer(key)
    )
    assert i1.json()["changed"] is True and i2.json()["changed"] is False
    from app.core.events_model import Event

    async with tenant_session(tenant_id) as db:
        types = (
            await db.scalars(select(Event.type).where(Event.type == "lead.intent_changed"))
        ).all()
    assert len(types) == 1


async def test_upsert_never_reveals_a_lead_the_key_cannot_see(ws):
    tenant_id, c, admin = ws
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"], phone="98765 99999")
    rep = await _key(c, admin, tenant_id, role="sales_user")
    r = await c.post(
        "/api/v1/leads/upsert",
        json={"phones": ["98765 99999"], "source": "Website", "intent": {"intent": "cold"}},
        headers=bearer(rep),
    )
    assert r.json() == {"result": "existing", "lead_id": None, "name": None}


async def test_deliveries_say_who_caused_the_event_and_key_writes_are_api(ws, receiver):
    from app.core.events import automation_context, emit
    from app.modules.crm.models import Activity

    tenant_id, c, _ = ws
    admin_id, admin = await login_as(tenant_id, "admin")
    await _hook(c, admin, events=["lead.created", "lead.updated"])
    key = await _key(c, admin, tenant_id)
    _, sources = await setup_ids(c, admin)
    by_person = (await new_lead(c, admin, sources["Website"], phone="98765 33333")).json()
    r = await new_lead(
        c, bearer(key), sources["Website"], phone="98765 44444", owner_user_id=str(admin_id)
    )
    assert r.status_code == 201, r.text
    by_key = r.json()
    async with tenant_session(tenant_id) as db:  # Core itself, then an automation
        await emit(db, tenant_id, "lead.updated", {"lead_id": by_person["id"]})
        t = automation_context.set({"id": "a", "name": "Auto", "chain": ["a"], "depth": 1})
        try:
            await emit(db, tenant_id, "lead.updated", {"lead_id": by_person["id"]})
        finally:
            automation_context.reset(t)
    await W.run_all([tenant_id])
    got = [json.loads(r.content)["data"] for r in receiver.calls]
    who = {(d["lead_id"], d["actor_type"], d["actor_user_id"]) for d in got}
    from app.modules.integrations.models import ApiKey

    async with tenant_session(tenant_id) as db:
        key_user = str(await db.scalar(select(ApiKey.user_id).where(ApiKey.id == key["id"])))
    assert who == {
        (by_person["id"], "user", str(admin_id)),
        (by_key["id"], "integration", key_user),
        (by_person["id"], "system", None),
        (by_person["id"], "automation", None),
    }
    assert all("_actor" not in d and "_via" not in d for d in got)
    async with tenant_session(tenant_id) as db:
        kinds = set(
            (
                await db.scalars(
                    select(Activity.actor_type).where(Activity.lead_id == uuid.UUID(by_key["id"]))
                )
            ).all()
        )
    assert kinds == {"api"}

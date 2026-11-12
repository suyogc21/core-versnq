"""Step 10a (Decision log #41): the reps' own WhatsApp through the Versnq Chrome extension —
connect codes, a token that works only on the extension's endpoints, lookup within what the rep
may see, logging once, replies stop sequences, create / link leads, notes and follow-ups,
revoking, isolation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.engage.models import Conversation, Enrolment, ExtensionToken, Message
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace


@pytest.fixture(autouse=True)
async def no_rate_limit(monkeypatch):
    from app.core import ratelimit

    async def ok(*a, **k):
        return None

    monkeypatch.setattr(ratelimit, "enforce", ok)


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, client_for(slug), admin


async def _connect(c, h):
    code = (await c.post("/api/v1/me/extension/code", headers=h)).json()["code"]
    r = await c.post("/api/v1/extension/connect", json={"code": code, "device": "Chrome on Mac"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _lead(c, h, phone="98765 43210", name="Asha"):
    _, sources = await setup_ids(c, h)
    r = await new_lead(c, h, sources["Website"], phone=phone, first_name=name)
    assert r.status_code == 201, r.text
    return r.json()


def _msgs(*items):
    return [
        {
            "id": i,
            "from_me": me,
            "text": t,
            "at": (datetime.now(UTC) - timedelta(minutes=m)).isoformat(),
        }
        for i, me, t, m in items
    ]


async def test_codes_work_once_and_tokens_only_open_the_extension(ws):
    tenant_id, c, _ = ws
    _, rep = await login_as(tenant_id, "sales_user")
    code = (await c.post("/api/v1/me/extension/code", headers=rep)).json()["code"]
    ok = await c.post("/api/v1/extension/connect", json={"code": code})
    assert ok.status_code == 200 and ok.json()["token"].startswith("vq_ext_")
    again = await c.post("/api/v1/extension/connect", json={"code": code})
    assert again.status_code == 401
    ext = {"Authorization": f"Bearer {ok.json()['token']}"}
    assert (await c.get("/api/v1/extension/me", headers=ext)).status_code == 200
    assert (await c.get("/api/v1/leads", headers=ext)).status_code == 401  # nothing else
    assert (await c.get("/api/v1/auth/me", headers=ext)).status_code == 401

    # an expired code
    late = (await c.post("/api/v1/me/extension/code", headers=rep)).json()["code"]
    async with tenant_session(tenant_id) as db:
        for row in (
            await db.scalars(select(ExtensionToken).where(ExtensionToken.code_hash.is_not(None)))
        ).all():
            row.code_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert (await c.post("/api/v1/extension/connect", json={"code": late})).status_code == 401

    # revoke from My account
    [mine] = (await c.get("/api/v1/me/extensions", headers=rep)).json()
    assert mine["device"] is None and mine["connected"]
    await c.post(f"/api/v1/extensions/{mine['id']}/revoke", headers=rep)
    assert (await c.get("/api/v1/extension/me", headers=ext)).status_code == 401


async def test_lookup_only_finds_leads_the_rep_may_see(ws):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, other = await login_as(tenant_id, "sales_user")
    mine = await _lead(c, rep, "98765 43210")
    await _lead(c, other, "91234 56789", "Ravi")
    ext = await _connect(c, rep)
    found = (
        await c.get("/api/v1/extension/lookup", params={"phone": "+91 98765 43210"}, headers=ext)
    ).json()
    assert found["lead"]["id"] == mine["id"] and found["lead"]["is_yours"]
    assert found["phone"] == "+919876543210"
    hidden = (
        await c.get("/api/v1/extension/lookup", params={"phone": "919123456789"}, headers=ext)
    ).json()
    assert hidden["lead"] is None  # someone else's lead
    unknown = (
        await c.get("/api/v1/extension/lookup", params={"phone": "+1 650 253 0000"}, headers=ext)
    ).json()
    assert unknown["lead"] is None and unknown["phone"] == "+16502530000"


async def test_messages_log_once_on_one_whatsapp_conversation(ws):
    tenant_id, c, _ = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep)
    ext = await _connect(c, rep)
    batch = _msgs(
        ("w1", False, "Hi, is the course still open?", 10),
        ("w2", True, "Yes! Batch starts Monday.", 5),
    )
    r = (
        await c.post(
            "/api/v1/extension/messages",
            json={"lead_id": lead["id"], "messages": batch},
            headers=ext,
        )
    ).json()
    assert r == {"logged": 2, "skipped": 0}
    r = (
        await c.post(
            "/api/v1/extension/messages",
            json={"lead_id": lead["id"], "messages": batch + _msgs(("w3", False, "", 1))},
            headers=ext,
        )
    ).json()
    assert r == {"logged": 1, "skipped": 2}
    async with tenant_session(tenant_id) as db:
        rows = (await db.scalars(select(Message).order_by(Message.sent_at))).all()
        assert [(m.direction, m.channel) for m in rows] == [
            ("in", "whatsapp"),
            ("out", "whatsapp"),
            ("in", "whatsapp"),
        ]
        assert rows[2].body == "[message]" and rows[1].sent_by_user_id == rep_id
        assert len({m.conversation_id for m in rows}) == 1
        conv = await db.get(Conversation, rows[0].conversation_id)
        assert conv.channel == "whatsapp"
    inbox = (await c.get("/api/v1/inbox", params={"view": "all"}, headers=rep)).json()
    assert [r["subject"] for r in inbox] == ["WhatsApp"] and inbox[0]["waiting"]
    no = await c.post(
        f"/api/v1/conversations/{inbox[0]['id']}/reply", json={"body": "x"}, headers=rep
    )
    assert no.status_code == 422 and "WhatsApp" in no.text
    detail = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    assert detail["last_contacted_at"] is not None  # a sent WhatsApp counts as contact
    timeline = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)).json()
    items = timeline["items"] if isinstance(timeline, dict) else timeline
    assert {"whatsapp_sent", "whatsapp_received"} <= {i["type_key"] for i in items}


async def test_a_whatsapp_reply_stops_sequences(ws):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep)
    t = (
        await c.post(
            "/api/v1/templates", json={"name": "T", "subject": "Hi", "body": "Hi"}, headers=admin
        )
    ).json()
    s = (await c.post("/api/v1/sequences", json={"name": "S"}, headers=admin)).json()
    await c.put(
        f"/api/v1/sequences/{s['id']}/steps",
        json=[{"kind": "wait", "hours": 48}, {"kind": "email", "template_id": t["id"]}],
        headers=admin,
    )
    await c.patch(f"/api/v1/sequences/{s['id']}", json={"is_active": True}, headers=admin)
    await c.post(
        f"/api/v1/sequences/{s['id']}/enrol", json={"lead_ids": [lead["id"]]}, headers=admin
    )
    ext = await _connect(c, rep)
    old = _msgs(("old", False, "from last week", 60 * 24 * 7))
    await c.post(
        "/api/v1/extension/messages", json={"lead_id": lead["id"], "messages": old}, headers=ext
    )
    async with tenant_session(tenant_id) as db:
        assert (await db.scalar(select(Enrolment))).status == "active"  # an old message doesn't
    await c.post(
        "/api/v1/extension/messages",
        json={"lead_id": lead["id"], "messages": _msgs(("new", False, "ok call me", 1))},
        headers=ext,
    )
    async with tenant_session(tenant_id) as db:
        e = await db.scalar(select(Enrolment))
        assert e.status == "stopped" and e.ended_reason == "reply"


async def test_create_and_link_leads_note_and_follow_up(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    ext = await _connect(c, rep)
    made = await c.post(
        "/api/v1/extension/leads", json={"phone": "919988776655", "name": "Neha Joshi"}, headers=ext
    )
    assert made.status_code == 201, made.text
    lead = made.json()["lead"]
    assert lead["name"] == "Neha Joshi" and lead["is_yours"]
    dup = await c.post(
        "/api/v1/extension/leads", json={"phone": "+91 99887 76655", "name": "Neha"}, headers=ext
    )
    assert dup.status_code == 409  # same rules as quick-add

    # a chat with no number visible: link it once, found by its key afterwards
    other = await _lead(c, rep, "98111 22233", "Kiran")
    hits = (await c.get("/api/v1/extension/search", params={"q": "kir"}, headers=ext)).json()
    assert [h["id"] for h in hits] == [other["id"]]
    await c.post(
        "/api/v1/extension/link",
        json={"chat_key": "Kiran (school)", "lead_id": other["id"]},
        headers=ext,
    )
    found = (
        await c.get("/api/v1/extension/lookup", params={"chat_key": "Kiran (school)"}, headers=ext)
    ).json()
    assert found["lead"]["id"] == other["id"]

    noted = await c.post(
        f"/api/v1/extension/leads/{lead['id']}/note",
        json={"body": "Wants weekend batch"},
        headers=ext,
    )
    assert noted.status_code == 200
    when = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    fu = (
        await c.put(
            f"/api/v1/extension/leads/{lead['id']}/follow-up", json={"at": when}, headers=ext
        )
    ).json()
    assert fu["lead"]["next_follow_up_at"] is not None


async def test_admin_sees_and_revokes_and_companies_are_apart(ws, client_for):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    ext = await _connect(c, rep)
    listed = (await c.get("/api/v1/extensions", headers=admin)).json()
    assert len(listed) == 1 and listed[0]["connected"]
    assert (await c.get("/api/v1/extensions", headers=rep)).status_code == 403
    await c.post(f"/api/v1/extensions/{listed[0]['id']}/revoke", headers=admin)
    assert (await c.get("/api/v1/extension/me", headers=ext)).status_code == 401

    ext2 = await _connect(c, rep)
    other_id, other_slug = await make_workspace()
    oc = client_for(other_slug)
    assert (await oc.get("/api/v1/extension/me", headers=ext2)).status_code == 401  # other company
    _, other_admin = await login_as(other_id, "admin")
    code = (await oc.post("/api/v1/me/extension/code", headers=other_admin)).json()["code"]
    assert (await c.post("/api/v1/extension/connect", json={"code": code})).status_code == 401
    lead = await _lead(oc, other_admin)
    r = await c.post(
        "/api/v1/extension/messages",
        json={"lead_id": lead["id"], "messages": _msgs(("x", True, "hi", 1))},
        headers=ext2,
    )
    assert r.status_code == 404
    assert uuid.UUID(lead["id"])

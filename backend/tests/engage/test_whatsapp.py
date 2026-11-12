"""Step 10b (Decision log #41): the official WhatsApp number — connecting, signed webhooks,
incoming messages, unknown number → lead, the 24-hour window, templates and their rules,
STOP, delivery receipts, the autoresponder, and isolation. Meta is never called."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead, Notification
from app.modules.engage import whatsapp as WA
from app.modules.engage.models import Conversation, Enrolment, Message, WhatsAppAccount
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

SECRET = "app-secret-123"
ALWAYS = {"from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "daily_cap": 200}
NEVER = {"from": "09:00", "to": "09:01", "days": [], "daily_cap": 200}


class Recorder(WA.TestClient):
    sent: list = []
    submitted: list = []
    status = "APPROVED"

    async def send(self, payload):
        Recorder.sent.append(payload)
        return await super().send(payload)

    async def submit_template(self, payload):
        Recorder.submitted.append(payload)
        return {"id": f"T{uuid.uuid4().hex[:6]}", "status": Recorder.status}


@pytest.fixture(autouse=True)
def fake_meta(monkeypatch):
    Recorder.sent, Recorder.submitted, Recorder.status = [], [], "APPROVED"
    monkeypatch.setattr(WA, "client", lambda acct: Recorder(acct))


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = dict(ALWAYS)
    _, admin = await login_as(tenant_id, "admin")
    c = client_for(slug)
    r = await c.put(
        "/api/v1/whatsapp/account",
        json={
            "phone_number_id": "1111111",
            "waba_id": "2222222",
            "access_token": "tok",
            "app_secret": SECRET,
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    return tenant_id, c, admin


def _payload(*messages, statuses=(), name="Asha Rao", phone_id="1111111"):
    contacts = [{"wa_id": m["from"], "profile": {"name": name}} for m in messages]
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone_id},
                            "contacts": contacts,
                            "messages": list(messages),
                            "statuses": list(statuses),
                        },
                    }
                ]
            }
        ],
    }


def _text(frm, body, wamid=None, ago_min=0):
    ts = int((datetime.now(UTC) - timedelta(minutes=ago_min)).timestamp())
    return {
        "from": frm,
        "id": wamid or f"wamid.{uuid.uuid4().hex}",
        "timestamp": str(ts),
        "type": "text",
        "text": {"body": body},
    }


async def _deliver(c, payload):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = await c.post(
        "/api/v1/whatsapp/webhook",
        content=raw,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    return r.json()["kept"]


async def _lead(c, h, phone="98765 43210", **extra):
    _, sources = await setup_ids(c, h)
    r = await new_lead(c, h, sources["Website"], phone=phone, first_name="Asha", **extra)
    assert r.status_code == 201, r.text
    return r.json()


async def _template(
    c,
    h,
    body="Hi {{lead.first_name|there}}, your demo is confirmed.",
    category="utility",
    name="demo confirm",
):
    r = await c.post(
        "/api/v1/whatsapp/templates",
        json={"name": name, "category": category, "body": body},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- connecting and the webhook ----------
async def test_connect_is_admin_only_and_the_webhook_is_signed(ws):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    assert (await c.get("/api/v1/whatsapp/account", headers=rep)).status_code == 403
    out = (await c.get("/api/v1/whatsapp/account", headers=admin)).json()
    assert (
        out["connected"]
        and out["test_mode"]
        and out["webhook_url"].endswith("/api/v1/whatsapp/webhook")
    )
    async with tenant_session(tenant_id) as db:
        acct = await db.scalar(select(WhatsAppAccount))
        assert SECRET not in acct.app_secret_enc and "tok" != acct.access_token_enc
    ok = await c.get(
        "/api/v1/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": out["verify_token"],
            "hub.challenge": "42",
        },
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = await c.get(
        "/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
    )
    assert bad.status_code == 403
    unsigned = await c.post(
        "/api/v1/whatsapp/webhook", content=json.dumps(_payload(_text("919876543210", "hi")))
    )
    assert unsigned.status_code == 401
    forged = await c.post(
        "/api/v1/whatsapp/webhook",
        content=json.dumps(_payload(_text("919876543210", "hi"))),
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
    )
    assert forged.status_code == 401


# ---------- incoming ----------
async def test_incoming_lands_once_opens_the_window_notifies_and_stops_sequences(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
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

    m = _text("919876543210", "Is the course still open?")
    assert await _deliver(c, _payload(m)) == 1
    assert await _deliver(c, _payload(m)) == 0  # Meta retries: kept once
    async with tenant_session(tenant_id) as db:
        msg = await db.scalar(select(Message).where(Message.direction == "in"))
        conv = await db.get(Conversation, msg.conversation_id)
        assert str(msg.lead_id) == lead["id"] and conv.whatsapp_account_id is not None
        assert WA.window_ends(conv) is not None
        assert (await db.scalar(select(Enrolment))).ended_reason == "reply"
        assert await db.scalar(select(Notification.id).where(Notification.user_id == rep_id))
    detail = (await c.get(f"/api/v1/conversations/{conv.id}", headers=rep)).json()
    assert detail["official"] and detail["can_reply"] and detail["window_ends_at"]
    r = await c.post(
        f"/api/v1/conversations/{conv.id}/reply",
        json={"body": "Yes {{lead.first_name}}!"},
        headers=rep,
    )
    assert r.status_code == 200, r.text
    assert Recorder.sent[-1] == {
        "to": "919876543210",
        "type": "text",
        "text": {"body": "Yes Asha!"},
    }


async def test_unknown_number_becomes_a_lead_unless_turned_off(ws):
    tenant_id, c, admin = ws
    assert (
        await _deliver(c, _payload(_text("919811122233", "Hello, price?"), name="Ravi Kumar")) == 1
    )
    async with tenant_session(tenant_id) as db:
        lead = await db.scalar(select(Lead).where(Lead.primary_phone == "+919811122233"))
        assert lead and lead.first_name == "Ravi" and lead.created_via == "whatsapp"
    again = await _deliver(c, _payload(_text("919811122233", "Hello again")))
    assert again == 1
    async with tenant_session(tenant_id) as db:
        assert (
            len((await db.scalars(select(Lead).where(Lead.primary_phone == "+919811122233"))).all())
            == 1
        )

    s = (await c.get("/api/v1/whatsapp/settings", headers=admin)).json()
    await c.put("/api/v1/whatsapp/settings", json=s | {"create_leads": False}, headers=admin)
    assert await _deliver(c, _payload(_text("919800000111", "hi"))) == 0


async def test_delivery_receipts_never_go_backwards(ws):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    tpl = await _template(c, admin)
    r = await c.post(
        f"/api/v1/leads/{lead['id']}/whatsapp", json={"template_id": tpl["id"]}, headers=admin
    )
    assert r.status_code == 201, r.text
    async with tenant_session(tenant_id) as db:
        wamid = (await db.get(Message, uuid.UUID(r.json()["message_id"]))).provider_id
    now = int(datetime.now(UTC).timestamp())
    await _deliver(c, _payload(statuses=[{"id": wamid, "status": "read", "timestamp": str(now)}]))
    await _deliver(
        c, _payload(statuses=[{"id": wamid, "status": "delivered", "timestamp": str(now)}])
    )
    async with tenant_session(tenant_id) as db:
        msg = await db.get(Message, uuid.UUID(r.json()["message_id"]))
        assert msg.status == "read" and msg.read_at and msg.delivered_at


# ---------- the rules ----------
async def test_window_templates_and_consent_rules(ws):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    no = await c.post(f"/api/v1/leads/{lead['id']}/whatsapp", json={"text": "hello"}, headers=admin)
    assert no.status_code == 422 and "24-hour window" in no.text

    Recorder.status = "PENDING"
    pending = await _template(c, admin, name="not yet")
    assert pending["status"] == "pending"
    r = await c.post(
        f"/api/v1/leads/{lead['id']}/whatsapp", json={"template_id": pending["id"]}, headers=admin
    )
    assert r.status_code == 422 and "not approved" in r.text
    # Meta approves it (template webhook)
    await _deliver(
        c,
        {
            "entry": [
                {
                    "changes": [
                        {
                            "field": "message_template_status_update",
                            "value": {
                                "event": "APPROVED",
                                "message_template_name": "not_yet",
                                "message_template_language": "en",
                            },
                        }
                    ]
                }
            ]
        },
    )
    assert (
        await c.post(
            f"/api/v1/leads/{lead['id']}/whatsapp",
            json={"template_id": pending["id"]},
            headers=admin,
        )
    ).status_code == 201

    Recorder.status = "APPROVED"
    promo = await _template(
        c,
        admin,
        body="Hi {{lead.first_name}}, 20% off this week!",
        category="marketing",
        name="promo",
    )
    r = await c.post(
        f"/api/v1/leads/{lead['id']}/whatsapp", json={"template_id": promo["id"]}, headers=admin
    )
    assert r.status_code == 422 and "opted in" in r.text
    sent = Recorder.submitted[-1]
    assert (
        sent["components"][0]["text"] == "Hi {{1}}, 20% off this week!"
        and sent["category"] == "MARKETING"
    )
    bad = await c.post(
        "/api/v1/whatsapp/templates",
        json={"name": "x", "category": "utility", "body": "{{lead.first_name}} hi"},
        headers=admin,
    )
    assert bad.status_code == 422


async def test_stop_opts_out_and_nothing_automatic_follows(ws):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    s = (await c.get("/api/v1/whatsapp/settings", headers=admin)).json()
    await c.put(
        "/api/v1/whatsapp/settings",
        json=s | {"welcome": {"on": True, "text": "Thanks for writing!"}},
        headers=admin,
    )
    await _deliver(c, _payload(_text("919876543210", " stop ")))
    async with tenant_session(tenant_id) as db:
        assert (await db.get(Lead, uuid.UUID(lead["id"]))).whatsapp_consent == "opted_out"
    assert Recorder.sent == []  # no welcome after STOP
    tpl = await _template(c, admin)
    r = await c.post(
        f"/api/v1/leads/{lead['id']}/whatsapp", json={"template_id": tpl["id"]}, headers=admin
    )
    assert r.status_code == 422 and "opted out" in r.text


async def test_autoresponder_welcome_away_and_daily_limit(ws):
    tenant_id, c, admin = ws
    await _lead(c, admin)
    s = (await c.get("/api/v1/whatsapp/settings", headers=admin)).json()
    await c.put(
        "/api/v1/whatsapp/settings",
        json=s
        | {
            "welcome": {"on": True, "text": "Hi {{lead.first_name|there}}, thanks for writing!"},
            "away": {"on": True, "text": "We're closed now; we'll reply in the morning."},
        },
        headers=admin,
    )
    await _deliver(c, _payload(_text("919876543210", "hello")))
    assert [p["text"]["body"] for p in Recorder.sent] == ["Hi Asha, thanks for writing!"]
    await _deliver(c, _payload(_text("919876543210", "are you there?")))
    assert len(Recorder.sent) == 1  # open hours: no away message
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = dict(NEVER)
    await _deliver(c, _payload(_text("919876543210", "hello?")))
    assert Recorder.sent[-1]["text"]["body"].startswith("We're closed")
    await _deliver(c, _payload(_text("919876543210", "anyone?")))
    assert len(Recorder.sent) == 2  # away at most every 12 hours, two a day


async def test_extension_chats_and_the_company_number_stay_apart_and_companies_too(ws, client_for):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    await _deliver(c, _payload(_text("919876543210", "official hello")))
    async with tenant_session(tenant_id) as db:
        from app.modules.auth.deps import CurrentUser  # noqa: F401
        from app.modules.engage.extension import _conversation

        lead_row = await db.get(Lead, uuid.UUID(lead["id"]))
        official = await db.scalar(
            select(Conversation).where(Conversation.whatsapp_account_id.is_not(None))
        )

        class A:  # the minimum _conversation reads
            class user:
                id = None

        ext_conv = await _conversation(db, lead_row, A)
        assert ext_conv.id != official.id and ext_conv.whatsapp_account_id is None
    other_id, other_slug = await make_workspace()
    oc = client_for(other_slug)
    raw = json.dumps(_payload(_text("919876543210", "x"))).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = await oc.post("/api/v1/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 404  # that company has no number connected
    _, other_admin = await login_as(other_id, "admin")
    assert (await oc.get("/api/v1/whatsapp/templates", headers=other_admin)).json() == []


async def test_a_pdf_sent_on_whatsapp_is_kept_on_the_lead(ws, tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.modules.engage.models import MessageAttachment

    monkeypatch.setattr(get_settings(), "files_dir", str(tmp_path / "files"))

    async def media(self, media_id):
        return b"%PDF-1.4\n" + b"x" * 300, "application/pdf"

    monkeypatch.setattr(Recorder, "media", media)
    tenant_id, c, admin = ws
    await _lead(c, admin)
    doc = {
        "from": "919876543210",
        "id": "wamid.DOC1",
        "timestamp": str(int(datetime.now(UTC).timestamp())),
        "type": "document",
        "document": {"id": "M1", "filename": "pan-card.pdf", "caption": "my PAN"},
    }
    assert await _deliver(c, _payload(doc)) == 1
    async with tenant_session(tenant_id) as db:
        msg = await db.scalar(select(Message).where(Message.external_id == "wamid.DOC1"))
        assert msg.body == "[document] my PAN"
        assert await db.scalar(
            select(MessageAttachment.id).where(MessageAttachment.message_id == msg.id)
        )


# ---------- 10b-2: sequences, reminders, health ----------
async def _sequence(c, h, steps):
    s = (
        await c.post("/api/v1/sequences", json={"name": f"S{uuid.uuid4().hex[:4]}"}, headers=h)
    ).json()
    r = await c.put(f"/api/v1/sequences/{s['id']}/steps", json=steps, headers=h)
    assert r.status_code == 200, r.text
    await c.patch(f"/api/v1/sequences/{s['id']}", json={"is_active": True}, headers=h)
    return s


async def test_whatsapp_steps_send_templates_and_skip_when_a_rule_says_no(ws):
    from app.modules.engage import engine as E

    tenant_id, c, admin = ws
    ok_lead = await _lead(c, admin)
    out_lead = await _lead(c, admin, phone="91234 56789")
    async with tenant_session(tenant_id) as db:
        (await db.get(Lead, uuid.UUID(out_lead["id"]))).whatsapp_consent = "opted_out"
    tpl = await _template(c, admin)
    promo = await _template(
        c, admin, body="Hi {{lead.first_name}}, offer!", category="marketing", name="offer"
    )
    s = await _sequence(
        c,
        admin,
        [
            {"kind": "whatsapp", "template_id": tpl["id"]},
            {"kind": "whatsapp", "template_id": promo["id"]},
            {"kind": "task", "title": "Call them"},
        ],
    )
    await c.post(
        f"/api/v1/sequences/{s['id']}/enrol",
        json={"lead_ids": [ok_lead["id"], out_lead["id"]]},
        headers=admin,
    )
    await E.run_due(tenant_id)
    # ok_lead: utility sent; marketing skipped (no opt-in); out_lead: both skipped; both finish
    assert [p["to"] for p in Recorder.sent] == ["919876543210"]
    assert Recorder.sent[0]["template"]["components"][0]["parameters"] == [
        {"type": "text", "text": "Asha"}
    ]
    async with tenant_session(tenant_id) as db:
        assert {e.status for e in (await db.scalars(select(Enrolment))).all()} == {"completed"}
    stats = (await c.get(f"/api/v1/sequences/{s['id']}/stats", headers=admin)).json()
    assert stats["steps"][0]["sent"] == 1
    bad = await c.put(
        f"/api/v1/sequences/{s['id']}/steps", json=[{"kind": "whatsapp"}], headers=admin
    )
    assert bad.status_code == 422


async def test_payment_reminder_on_whatsapp_uses_invoice_details(ws):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    body = (
        "Hi {{lead.first_name}}, {{invoice.amount_due}} for {{invoice.number}} "
        "is due on {{invoice.due_date}}. Thank you."
    )
    tpl = await _template(c, admin, name="pay reminder", body=body)
    s = (await c.get("/api/v1/whatsapp/settings", headers=admin)).json()
    promo = await _template(
        c, admin, body="Hi {{lead.first_name}}, sale!", category="marketing", name="sale"
    )
    no = await c.put(
        "/api/v1/whatsapp/settings", json=s | {"reminder_template_id": promo["id"]}, headers=admin
    )
    assert no.status_code == 422  # reminders need a utility template
    await c.put(
        "/api/v1/whatsapp/settings", json=s | {"reminder_template_id": tpl["id"]}, headers=admin
    )
    async with tenant_session(tenant_id) as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        msg = await WA.payment_reminder(
            db,
            row,
            number="INV-7",
            amount_due="₹5,000",
            due_date=datetime(2026, 11, 19).date(),
            invoice_id=uuid.uuid4(),
        )
        assert msg is not None and msg.status == "sent"
    params = [p["text"] for p in Recorder.sent[-1]["template"]["components"][0]["parameters"]]
    assert params == ["Asha", "₹5,000", "INV-7", "19 Nov"]


async def test_health_check_warns_admins_when_quality_drops(ws, monkeypatch):
    tenant_id, c, admin = ws

    async def red(self):
        return {
            "display_phone_number": "+91 90000 00000",
            "quality_rating": "RED",
            "messaging_limit_tier": "TIER_250",
        }

    monkeypatch.setattr(Recorder, "phone_info", red)
    out = (await c.post("/api/v1/whatsapp/account/check", headers=admin)).json()
    assert out["quality_rating"] == "RED" and out["messaging_limit"] == "TIER_250"
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(Notification.id).where(Notification.kind == "whatsapp"))
        assert await WA.daily_limit(db) == 250

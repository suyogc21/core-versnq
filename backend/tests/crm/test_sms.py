"""Batch 5d: SMS. An admin connects a provider (keys never shown again); a rep sends an SMS to a
lead they can see, and it's on the timeline with an event; nobody who opted out (or whose number
is suppressed) gets one; STOP from a number opts it out; delivery reports update the status;
Twilio's requests need Twilio's signature; MSG91 (India) only sends DLT templates; sequences can
send SMS steps; another company sees none of it."""

import base64
import hashlib
import hmac
import uuid
from urllib.parse import urlencode

from sqlalchemy import select

from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.crm.models import Activity, Lead
from app.modules.engage import engine as E
from app.modules.settings.models import TenantSettings
from app.modules.sms.models import SmsAccount, SmsMessage
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

ALWAYS = {"from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "daily_cap": 200}
TWILIO_TOKEN = "twilio-sms-token-1"


async def _setup(ws, provider="test", **extra):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    body = {"provider": provider, "sender": "+14155550100", **extra}
    r = await c.put("/api/v1/sms/account", json=body, headers=admin)
    assert r.status_code == 200, r.text
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], owner_user_id=str(rep_id))).json()
    return tenant_id, c, admin, rep, lead, r.json()


async def _token(tenant_id) -> str:
    async with tenant_session(tenant_id) as db:
        return (await db.scalar(select(SmsAccount))).webhook_token


async def test_a_rep_sends_an_sms_on_the_timeline_with_an_event(ws):
    tenant_id, c, admin, rep, lead, acct = await _setup(ws)
    _, other_rep = await login_as(tenant_id, "sales_user")
    by_rep_settings = await c.put(
        "/api/v1/sms/account", headers=rep, json={"provider": "test", "sender": "+14155550100"}
    )
    r = await c.post(
        f"/api/v1/leads/{lead['id']}/sms", json={"body": "Hi {{lead.first_name}}!"}, headers=rep
    )
    hidden = await c.post(f"/api/v1/leads/{lead['id']}/sms", json={"body": "x"}, headers=other_rep)
    empty = await c.post(f"/api/v1/leads/{lead['id']}/sms", json={}, headers=rep)
    history = await c.get(f"/api/v1/leads/{lead['id']}/sms", headers=rep)

    assert acct["connected"] and acct["test_mode"] and acct["inbound_url"].endswith("/inbound")
    assert by_rep_settings.status_code == 403 and hidden.status_code == 404
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["body"] == "Hi Rahul!"
    assert empty.json()["code"] == "sms_empty" and len(history.json()) == 1
    async with tenant_session(tenant_id) as db:
        acts = (
            await db.scalars(
                select(Activity.type_key).where(Activity.lead_id == uuid.UUID(lead["id"]))
            )
        ).all()
        events = (await db.scalars(select(Event.type).where(Event.type == "sms.sent"))).all()
    assert "sms_sent" in acts and events == ["sms.sent"]


async def test_opted_out_and_stop_are_honoured(ws):
    tenant_id, c, admin, rep, lead, _ = await _setup(ws)
    token = await _token(tenant_id)
    inbound = f"/api/v1/sms/{token}/inbound"
    wrong = await c.post(
        "/api/v1/sms/not-the-token/inbound", data={"From": "+919876543210", "Body": "STOP"}
    )
    hello = await c.post(inbound, data={"From": "+919876543210", "Body": "Is the batch full?"})
    stop = await c.post(inbound, data={"From": "+91 98765 43210", "Body": " Stop "})
    after = await c.post(f"/api/v1/leads/{lead['id']}/sms", json={"body": "Offer"}, headers=rep)
    unknown_stop = await c.post(inbound, data={"From": "+919811100000", "Body": "STOP"})

    assert wrong.status_code == 404 and hello.status_code == 204 and stop.status_code == 204
    assert after.status_code == 422 and after.json()["code"] == "sms_opted_out"
    assert unknown_stop.status_code == 204
    _, sources = await setup_ids(c, admin)
    later = (await new_lead(c, admin, sources["Website"], phone="98111 00000")).json()
    refused = await c.post(f"/api/v1/leads/{later['id']}/sms", json={"body": "Hi"}, headers=admin)
    assert refused.json()["code"] == "sms_opted_out"  # the number was suppressed without a lead
    async with tenant_session(tenant_id) as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        received = (
            await db.scalars(select(SmsMessage.body).where(SmsMessage.direction == "in"))
        ).all()
    assert row.sms_consent == "opted_out" and sorted(received) == [" Stop ", "Is the batch full?"]


async def test_delivery_reports_update_the_status(ws):
    tenant_id, c, admin, rep, lead, _ = await _setup(ws)
    token = await _token(tenant_id)
    sent = (
        await c.post(f"/api/v1/leads/{lead['id']}/sms", json={"body": "Hi"}, headers=rep)
    ).json()
    async with tenant_session(tenant_id) as db:
        pid = (await db.get(SmsMessage, uuid.UUID(sent["id"]))).provider_id
    r = await c.post(f"/api/v1/sms/{token}/status", json={"requestId": pid, "status": "delivered"})
    history = (await c.get(f"/api/v1/leads/{lead['id']}/sms", headers=rep)).json()
    assert (
        r.status_code == 204 and history[0]["status"] == "delivered" and history[0]["delivered_at"]
    )


def _twilio_sig(url: str, form: dict) -> str:
    payload = url + "".join(k + form[k] for k in sorted(form))
    return base64.b64encode(
        hmac.new(TWILIO_TOKEN.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()


async def test_twilio_requests_need_twilios_signature(ws):
    tenant_id, c, admin, rep, lead, _ = await _setup(
        ws, provider="twilio", account_sid="AC" + "0" * 32, auth=TWILIO_TOKEN
    )
    token = await _token(tenant_id)
    path = f"/api/v1/sms/{token}/inbound"
    form = {"From": "+919876543210", "Body": "Yes please", "MessageSid": "SM1"}
    url = str(c.base_url).rstrip("/") + path
    unsigned = await c.post(path, data=form)
    signed = await c.post(
        path,
        content=urlencode(form),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": _twilio_sig(url, form),
        },
    )
    again = await c.post(
        path,
        content=urlencode(form),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": _twilio_sig(url, form),
        },
    )
    assert unsigned.status_code == 404
    assert signed.status_code == 200 and "<Response/>" in signed.text and again.status_code == 200
    async with tenant_session(tenant_id) as db:
        assert (
            len((await db.scalars(select(SmsMessage).where(SmsMessage.provider_id == "SM1"))).all())
            == 1
        )


async def test_msg91_only_sends_dlt_templates_and_keys_are_never_shown(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    bad_sender = await c.put(
        "/api/v1/sms/account",
        headers=admin,
        json={"provider": "msg91", "sender": "+9198", "auth": "msg91-key-123456"},
    )
    wrong_key = await c.put(
        "/api/v1/sms/account",
        headers=admin,
        json={"provider": "msg91", "sender": "VERSNQ", "auth": "wrong-key"},
    )
    ok = await c.put(
        "/api/v1/sms/account",
        headers=admin,
        json={"provider": "msg91", "sender": "versnq", "auth": "msg91-key-123456"},
    )
    no_ids = await c.post(
        "/api/v1/sms/templates",
        headers=admin,
        json={"name": "Hi", "body": "Hi {{lead.first_name}}"},
    )
    tpl = await c.post(
        "/api/v1/sms/templates",
        headers=admin,
        json={
            "name": "Hi",
            "body": "Hi {{lead.first_name}}, call us",
            "dlt_template_id": "1107160000000000001",
            "provider_template_id": "64fa00aa",
        },
    )
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"])).json()
    free = await c.post(f"/api/v1/leads/{lead['id']}/sms", json={"body": "Hello"}, headers=admin)
    templated = await c.post(
        f"/api/v1/leads/{lead['id']}/sms", json={"template_id": tpl.json()["id"]}, headers=admin
    )

    assert bad_sender.status_code == 422 and wrong_key.json()["code"] == "sms_failed"
    assert ok.json()["sender"] == "VERSNQ" and "msg91-key" not in ok.text
    assert no_ids.status_code == 422 and tpl.status_code == 201
    assert free.json()["code"] == "sms_template_required"
    assert templated.json()["status"] == "sent" and templated.json()["body"] == "Hi Rahul, call us"


async def test_sequences_send_sms_steps_and_skip_opted_out_leads(ws):
    tenant_id, c, admin, rep, lead, _ = await _setup(ws)
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = dict(ALWAYS)
    _, sources = await setup_ids(c, admin)
    out = (await new_lead(c, admin, sources["Website"], phone="91234 56789")).json()
    await c.post(
        f"/api/v1/leads/{out['id']}/consents",
        json={"channel": "sms", "status": "opted_out"},
        headers=admin,
    )
    tpl = (
        await c.post(
            "/api/v1/sms/templates",
            headers=admin,
            json={"name": "Reminder", "body": "Hi {{lead.first_name}}, class at 6"},
        )
    ).json()
    s = (await c.post("/api/v1/sequences", json={"name": "SMS"}, headers=admin)).json()
    steps = await c.put(
        f"/api/v1/sequences/{s['id']}/steps",
        headers=admin,
        json=[{"kind": "sms", "template_id": tpl["id"]}],
    )
    await c.patch(f"/api/v1/sequences/{s['id']}", json={"is_active": True}, headers=admin)
    await c.post(
        f"/api/v1/sequences/{s['id']}/enrol",
        json={"lead_ids": [lead["id"], out["id"]]},
        headers=admin,
    )
    await E.run_due(tenant_id)

    assert steps.status_code == 200, steps.text
    async with tenant_session(tenant_id) as db:
        sent = (
            await db.scalars(select(SmsMessage.lead_id).where(SmsMessage.direction == "out"))
        ).all()
        skipped = await db.scalar(
            select(Activity.summary).where(
                Activity.lead_id == uuid.UUID(out["id"]), Activity.type_key == "sms_sent"
            )
        )
    assert sent == [uuid.UUID(lead["id"])] and "skipped" in skipped


async def test_another_company_sees_no_sms_and_cant_use_the_token(ws, client_for):
    tenant_id, c, admin, rep, lead, _ = await _setup(ws)
    token = await _token(tenant_id)
    await c.post(f"/api/v1/leads/{lead['id']}/sms", json={"body": "Hi"}, headers=rep)
    other_id, other_slug = await make_workspace()
    other = client_for(other_slug)
    _, other_admin = await login_as(other_id, "admin")
    peek = await other.get(f"/api/v1/leads/{lead['id']}/sms", headers=other_admin)
    acct = await other.get("/api/v1/sms/account", headers=other_admin)
    hook = await other.post(
        f"/api/v1/sms/{token}/inbound", data={"From": "+919876543210", "Body": "STOP"}
    )
    assert peek.status_code == 404 and acct.json()["connected"] is False and hook.status_code == 404

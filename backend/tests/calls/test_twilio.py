"""Step C3 (docs/plans/calls-plan.md): calling with the company's own Twilio. Connecting checks
the token and never shows it again; click-to-call rings the rep's phone, then the lead; Twilio's
requests are refused without a valid signature; every call ends in the pipeline with its
recording fetched by the worker; incoming calls ring the lead's owner, and unanswered ones leave
a voicemail and a call-back task; unknown callers without a lead are not kept."""

import base64
import hashlib
import hmac
import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.calls import twilio as T
from app.modules.calls.models import Call
from app.modules.crm.models import Task
from app.workers.jobs import call_recordings_job
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as

SID = "AC" + "0" * 32
TOKEN = "twilio-auth-token-1"
NUMBER = "+14155550100"
REC = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Recordings/RE123"


def sign(url: str, form: dict) -> str:
    payload = url + "".join(k + form[k] for k in sorted(form))
    return base64.b64encode(
        hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()


async def twilio_post(c, path: str, form: dict, good: bool = True):
    url = str(c.base_url).rstrip("/") + path  # the address Twilio signs
    sig = sign(url, form) if good else "bad"
    return await c.post(path, data=form, headers={"X-Twilio-Signature": sig})


@pytest.fixture
def started(monkeypatch):
    calls: list[dict] = []

    async def create_call(self, *, to, from_, url):
        calls.append({"to": to, "from": from_, "url": url})
        return "CA" + uuid.uuid4().hex

    monkeypatch.setattr(T.TestTwilio, "create_call", create_call)
    return calls


async def _connected(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    await c.put("/api/v1/calling/my-phone", json={"phone": "98200 11122"}, headers=rep)
    r = await c.put("/api/v1/calling/twilio", json={"account_sid": SID, "auth_token": TOKEN,
                    "numbers": [NUMBER], "forward_to": "98200 99999"}, headers=admin)  # fmt: skip
    assert r.status_code == 200, r.text
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], owner_user_id=str(rep_id))).json()
    return tenant_id, c, admin, rep_id, rep, lead


def _path(url: str) -> str:
    u = urlparse(url)
    return f"{u.path}?{u.query}"


async def test_connecting_checks_the_token_and_never_shows_it(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    body = {"account_sid": SID, "auth_token": "wrong-token", "numbers": [NUMBER]}

    wrong = await c.put("/api/v1/calling/twilio", json=body, headers=admin)
    by_rep = await c.put("/api/v1/calling/twilio", json={**body, "auth_token": TOKEN}, headers=rep)
    ok = await c.put("/api/v1/calling/twilio", json={**body, "auth_token": TOKEN}, headers=admin)
    two = ["+1 415 555 0100", "+1 415 555 0101"]
    keep = await c.put("/api/v1/calling/twilio", json={**body, "auth_token": None, "numbers": two},
                       headers=admin)  # fmt: skip

    assert wrong.status_code == 422 and wrong.json()["code"] == "twilio_failed"
    assert by_rep.status_code == 403
    assert ok.json()["connected"] and TOKEN not in ok.text
    assert ok.json()["voice_url"].endswith("/api/v1/twilio/voice")
    assert keep.json()["numbers"] == [NUMBER, "+14155550101"]


async def test_click_to_call_rings_the_rep_then_connects_the_lead(ws, started):
    tenant_id, c, admin, rep_id, rep, lead = await _connected(ws)
    _, no_phone = await login_as(tenant_id, "admin")

    r = await c.post(f"/api/v1/leads/{lead['id']}/call", headers=rep)
    missing = await c.post(f"/api/v1/leads/{lead['id']}/call", headers=no_phone)
    [placed] = started
    connect = await twilio_post(c, _path(placed["url"]), {"CallSid": "CApar1"})
    forged = await twilio_post(c, _path(placed["url"]), {"CallSid": "CApar1"}, good=False)

    assert r.status_code == 200 and r.json() == {"status": "ringing_you"}
    assert missing.json()["code"] == "my_phone_missing"
    assert placed["to"] == "+919820011122" and placed["from"] == NUMBER
    assert connect.status_code == 200 and "<Number>+919876543210</Number>" in connect.text
    assert 'record="record-from-answer-dual"' in connect.text
    assert f'callerId="{NUMBER}"' in connect.text
    assert forged.status_code == 404

    ctx = parse_qs(urlparse(placed["url"]).query)["ctx"][0]
    done = await twilio_post(c, f"/api/v1/twilio/dial-done?ctx={ctx}", {
        "CallSid": "CApar1", "DialCallStatus": "completed", "DialCallDuration": "65"})  # fmt: skip
    rec = await twilio_post(c, f"/api/v1/twilio/recording?ctx={ctx}", {
        "CallSid": "CApar1", "RecordingStatus": "completed", "RecordingUrl": REC})  # fmt: skip
    assert "<Hangup/>" in done.text and rec.status_code == 204
    assert await call_recordings_job(None) >= 1
    async with tenant_session(tenant_id) as db:
        call = await db.scalar(select(Call).where(Call.external_id == "CApar1"))
    assert (call.source, call.direction, call.status, call.duration_seconds) == (
        "twilio", "out", "answered", 65)  # fmt: skip
    assert call.user_id == rep_id and call.recording_path and call.recording_pending_url is None


async def test_incoming_rings_the_owner_and_unanswered_leaves_a_voicemail(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _connected(ws)
    voice = await twilio_post(c, "/api/v1/twilio/voice", {
        "CallSid": "CAin1", "From": "+919876543210", "To": NUMBER})  # fmt: skip
    ctx = re.search(r"dial-done\?ctx=([^\"&]+)", voice.text).group(1)
    done = await twilio_post(c, f"/api/v1/twilio/dial-done?ctx={ctx}", {
        "CallSid": "CAin1", "DialCallStatus": "no-answer"})  # fmt: skip
    rec = await twilio_post(c, f"/api/v1/twilio/recording?ctx={ctx}", {
        "CallSid": "CAin1", "RecordingStatus": "completed", "RecordingUrl": REC})  # fmt: skip
    await call_recordings_job(None)
    bye = await twilio_post(c, f"/api/v1/twilio/hangup?ctx={ctx}", {"CallSid": "CAin1"})

    assert "<Number>+919820011122</Number>" in voice.text  # the lead's owner's phone
    assert "<Record" in done.text and "/api/v1/twilio/hangup" in done.text
    assert rec.status_code == 204 and "<Hangup/>" in bye.text
    async with tenant_session(tenant_id) as db:
        call = await db.scalar(select(Call).where(Call.external_id == "CAin1"))
        task = await db.scalar(select(Task).where(Task.lead_id == uuid.UUID(lead["id"])))
    assert call.status == "missed" and call.recording_path  # the voicemail
    assert task.title.startswith("Call back") and task.owner_user_id == rep_id


async def test_unknown_caller_goes_to_the_main_number_and_is_not_kept(ws):
    tenant_id, c, *_ = await _connected(ws)
    voice = await twilio_post(c, "/api/v1/twilio/voice", {
        "CallSid": "CAin2", "From": "+919811177777", "To": NUMBER})  # fmt: skip
    ctx = re.search(r"dial-done\?ctx=([^\"&]+)", voice.text).group(1)
    await twilio_post(c, f"/api/v1/twilio/dial-done?ctx={ctx}", {
        "CallSid": "CAin2", "DialCallStatus": "completed", "DialCallDuration": "30"})  # fmt: skip

    assert "<Number>+919820099999</Number>" in voice.text  # forward_to
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(Call).where(Call.external_id == "CAin2")) is None


async def test_recording_before_the_call_ends_is_kept(ws, started):
    tenant_id, c, admin, rep_id, rep, lead = await _connected(ws)
    await c.post(f"/api/v1/leads/{lead['id']}/call", headers=rep)
    ctx = parse_qs(urlparse(started[0]["url"]).query)["ctx"][0]
    await twilio_post(c, f"/api/v1/twilio/recording?ctx={ctx}", {
        "CallSid": "CApar9", "RecordingStatus": "completed", "RecordingUrl": REC})  # fmt: skip
    await twilio_post(c, f"/api/v1/twilio/dial-done?ctx={ctx}", {
        "CallSid": "CApar9", "DialCallStatus": "completed", "DialCallDuration": "12"})  # fmt: skip
    await call_recordings_job(None)
    async with tenant_session(tenant_id) as db:
        call = await db.scalar(select(Call).where(Call.external_id == "CApar9"))
    assert call.recording_path is not None

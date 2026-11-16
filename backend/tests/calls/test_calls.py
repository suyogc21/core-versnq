"""Step C1 (docs/plans/calls-plan.md): the call pipeline. A reported call finds the lead by
number and is on the timeline at once; a repeat is the same call; an unknown number is not kept
unless the company makes leads from unknown incoming calls; a missed incoming call is a call-back
task; the Outcome uses the one-step rules on the same timeline entry; recordings are audio only,
played only by people who can see the lead, removed after keep_days; ACE's analysis shows on the
call; another company sees nothing."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.calls.models import Call
from app.modules.calls.service import expire_recordings
from app.modules.crm.models import Activity, Lead, Task
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_custom_role, make_workspace, switch_on

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 2000


def _call(**extra):
    return {"external_id": uuid.uuid4().hex, "direction": "out", "status": "answered",
            "number": "98765 43210", "started_at": datetime.now(UTC).isoformat(),
            "duration_seconds": 252, **extra}  # fmt: skip


async def _setup(ws, role="sales_user"):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, role)
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], owner_user_id=str(rep_id))).json()
    return tenant_id, c, admin, rep_id, rep, lead


async def _events(tenant_id, type_):
    async with tenant_session(tenant_id) as db:
        rows = await db.scalars(select(Event).where(Event.type == type_))
        return [e.payload for e in rows.all()]


async def test_a_call_from_the_phone_is_on_the_lead_at_once_and_a_repeat_is_the_same(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    body = _call(number="+91 98765-43210")

    r = await c.post("/api/v1/calls", json=body, headers=rep)
    again = await c.post("/api/v1/calls", json=body, headers=rep)
    timeline = await c.get(f"/api/v1/calls?lead_id={lead['id']}", headers=admin)

    assert r.status_code == 200, r.text
    call = r.json()["call"]
    assert r.json()["tracked"] and call["lead_id"] == lead["id"] and call["user_id"] == str(rep_id)
    assert again.json()["call"]["id"] == call["id"] and len(timeline.json()) == 1
    async with tenant_session(tenant_id) as db:
        act = await db.get(Activity, uuid.UUID(call["activity_id"]))
        row = await db.get(Lead, uuid.UUID(lead["id"]))
    assert act.type_key == "call" and act.summary == "Outgoing call · 4m 12s"
    assert act.data["call_id"] == call["id"] and act.data["recording"] is False
    assert row.last_contacted_at is not None
    [ev] = await _events(tenant_id, "call.logged")
    assert ev["call_id"] == call["id"] and ev["status"] == "answered"


async def test_unknown_numbers_are_not_kept_unless_the_company_makes_leads(ws):
    tenant_id, c, admin, _, rep, _ = await _setup(ws)
    personal = await c.post("/api/v1/calls", json=_call(number="98111 00000"), headers=rep)
    await c.put("/api/v1/call-settings", json={"record": True, "keep_days": 30, "new_leads": True},
                headers=admin)  # fmt: skip
    outgoing = await c.post("/api/v1/calls", json=_call(number="98111 00001"), headers=rep)
    incoming = await c.post("/api/v1/calls", json=_call(number="98111 00002", direction="in"),
                            headers=rep)  # fmt: skip

    assert personal.json() == {"tracked": False, "call": None}
    assert outgoing.json()["tracked"] is False  # a rep's own outgoing calls never make leads
    assert incoming.json()["tracked"] is True
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(Call).where(Call.number == "+919811100000")) is None
        made = await db.get(Lead, uuid.UUID(incoming.json()["call"]["lead_id"]))
    assert made.primary_phone == "+919811100002" and made.created_via == "call"


async def test_a_missed_incoming_call_is_a_call_back_task_for_the_owner(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    r = await c.post("/api/v1/calls", json=_call(direction="in", status="missed",
                                                 duration_seconds=40), headers=rep)  # fmt: skip
    call = r.json()["call"]
    async with tenant_session(tenant_id) as db:
        task = await db.scalar(select(Task).where(Task.lead_id == uuid.UUID(lead["id"])))
        act = await db.get(Activity, uuid.UUID(call["activity_id"]))
    assert call["duration_seconds"] == 0 and act.summary == "Missed call"
    assert task.title == "Call back Rahul" and task.owner_user_id == rep_id
    assert task.created_from == "call" and task.priority == "high"


async def test_the_outcome_completes_the_same_timeline_entry(ws):
    tenant_id, c, admin, _, rep, lead = await _setup(ws)
    call = (await c.post("/api/v1/calls", json=_call(), headers=rep)).json()["call"]
    types = (await c.get("/api/v1/activity-types", headers=rep)).json()
    options = next(t for t in types if t["key"] == "call")["fields"][0]["options"]
    later = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    no_follow_up = await c.post(f"/api/v1/calls/{call['id']}/outcome",
                                json={"disposition": options[0]["value"]}, headers=rep)  # fmt: skip
    ok = await c.post(f"/api/v1/calls/{call['id']}/outcome", json={
        "disposition": options[0]["value"], "next_follow_up_at": later, "body": "Wants a demo"},
        headers=rep)  # fmt: skip

    assert no_follow_up.status_code == 422  # the follow-up rule still applies
    assert ok.status_code == 200, ok.text
    assert ok.json()["outcome"] == options[0]["label"]
    async with tenant_session(tenant_id) as db:
        on_lead = Activity.lead_id == uuid.UUID(lead["id"])
        acts = (
            await db.scalars(select(Activity).where(on_lead, Activity.type_key == "call"))
        ).all()
    [act] = acts  # still one entry for the call
    assert act.disposition == options[0]["label"] and act.body == "Wants a demo"
    assert act.data["call_id"] == call["id"] and act.data["duration_seconds"] == 252


async def test_recordings_audio_only_played_by_who_sees_the_lead_and_removed_later(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    _, other_rep = await login_as(tenant_id, "sales_user")
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    call = (await c.post("/api/v1/calls", json=_call(started_at=old), headers=rep)).json()["call"]
    url = f"/api/v1/calls/{call['id']}/recording"

    pdf = await c.put(url, content=b"%PDF-1.4 nope", headers=rep)
    by_other = await c.put(url, content=MP3, headers={**admin, "X-File-Name": "a.mp3"})
    ok = await c.put(url, content=MP3, headers={**rep, "X-File-Name": "call.mp3"})
    twice = await c.put(url, content=MP3, headers=rep)
    play = await c.get(url, headers=admin)
    hidden = await c.get(url, headers=other_rep)

    assert pdf.status_code == 422 and by_other.status_code == 403
    assert ok.status_code == 200 and ok.json()["has_recording"] is True
    assert twice.json()["code"] == "recording_exists"
    assert play.status_code == 200 and play.headers["content-type"] == "audio/mpeg"
    assert play.content == MP3 and hidden.status_code == 404
    assert await _events(tenant_id, "call.recorded") == []  # for ACE: only when ACE is on

    async with tenant_session(tenant_id) as db:
        assert await expire_recordings(db, tenant_id) == 1
    gone = await c.get(f"/api/v1/calls/{call['id']}", headers=admin)
    assert gone.json()["has_recording"] is False and gone.json()["recording_removed"] is True
    assert (await c.get(url, headers=admin)).status_code == 404


async def test_recording_off_and_ace_analysis(ws):
    tenant_id, c, admin, _, rep, lead = await _setup(ws)
    await switch_on(tenant_id, "ace")  # call.recorded / call.analyzed are ACE's events
    call = (await c.post("/api/v1/calls", json=_call(), headers=rep)).json()["call"]
    role = await make_custom_role(tenant_id, "ACE", "all", ("leads.edit",))
    r = await c.post("/api/v1/integrations/keys", json={"name": "ACE", "role_id": str(role)},
                     headers=admin)  # fmt: skip
    ace = {"Authorization": f"Bearer {r.json()['key']}"}
    analysis = {"summary": "Asked about weekend batches; wants a callback Friday.",
                "intent": "warm", "red_flags": ["price concern"]}  # fmt: skip

    by_person = await c.put(f"/api/v1/calls/{call['id']}/analysis", json=analysis, headers=admin)
    by_ace = await c.put(f"/api/v1/calls/{call['id']}/analysis", json=analysis, headers=ace)
    retry = await c.put(f"/api/v1/calls/{call['id']}/analysis", json=analysis, headers=ace)
    await c.put("/api/v1/call-settings", json={"record": False, "keep_days": 30,
                "new_leads": False}, headers=admin)  # fmt: skip
    off = await c.put(f"/api/v1/calls/{call['id']}/recording", content=MP3, headers=rep)

    assert by_person.status_code == 403 and by_ace.status_code == 200, by_ace.text
    assert by_ace.json()["summary"].startswith("Asked about weekend")
    assert by_ace.json()["analysis"] == {"intent": "warm", "red_flags": ["price concern"]}
    assert off.json()["code"] == "recording_off" and retry.status_code == 200
    [ev] = await _events(tenant_id, "call.analyzed")  # the retry sent nothing new
    assert ev["call_id"] == call["id"]
    async with tenant_session(tenant_id) as db:
        act = await db.get(Activity, uuid.UUID(call["activity_id"]))
    assert act.data["summary"].startswith("Asked about weekend")
    assert act.data["intent"] == "warm" and act.data["red_flags"] == ["price concern"]


async def test_another_company_sees_no_calls_and_settings_need_admin(ws, client_for):
    tenant_id, c, admin, _, rep, _ = await _setup(ws)
    call = (await c.post("/api/v1/calls", json=_call(), headers=rep)).json()["call"]
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)

    assert (await oc.get(f"/api/v1/calls/{call['id']}", headers=other_admin)).status_code == 404
    assert (await oc.get("/api/v1/calls", headers=other_admin)).json() == []
    assert (await c.put("/api/v1/call-settings", json={"record": False}, headers=rep)
            ).status_code == 403  # fmt: skip

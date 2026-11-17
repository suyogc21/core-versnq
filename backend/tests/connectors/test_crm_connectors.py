"""Connect any CRM (docs/plans/crm-connectors-plan.md). Calls and WhatsApp messages go to the
company's connected CRM once each, through one shape for every CRM: Custom CRM (the company's own
signed addresses) and LeadSquared (as its API docs describe). The lead is found by phone, or made
there when the company asked; its id is kept. Busy (429) is tried again later, wrong keys fail at
once; keys never come back; only an admin sets it up; another company sees nothing; the "Calls +
WhatsApp" plan (crm_screens off) hides deals, customers and reports, also from the backend."""

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.core.modules import set_module
from app.core.tenancy import tenant_session
from app.modules.connectors import base as B
from app.modules.connectors import custom as C
from app.modules.connectors import service as S
from app.modules.connectors.hubspot import national
from app.modules.connectors.models import CrmSync
from app.modules.crm.models import ExternalRef
from app.modules.engage.inbox import message_event
from app.modules.engage.models import Message
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

LSQ = "api-in21.leadsquared.com"


class FakeCrm:
    """Answers like LeadSquared (paths from its docs) and like a Custom CRM."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.leads: dict[str, str] = {}  # phone digits -> id
        self.busy = 0  # answer 429 this many times
        self.status = None  # force a status
        self.owners: dict[str, str] = {}  # HubSpot: owner email -> id

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.busy:
            self.busy -= 1
            return httpx.Response(429, text="API calls exceeded the limit of 25 in 5 second(s)")
        if self.status:
            return httpx.Response(self.status, text="no")
        path = req.url.path
        body = json.loads(req.content) if req.content else None
        if path.endswith("RetrieveLeadByPhoneNumber"):
            found = self.leads.get(req.url.params["phone"])
            return httpx.Response(200, json=[{"ProspectID": found}] if found else [])
        if path.endswith("Lead.Create"):
            phone = next(a["Value"] for a in body if a["Attribute"] == "Phone").lstrip("+")
            self.leads[phone] = f"lsq-{len(self.leads) + 1}"
            return httpx.Response(200, json={"Status": "Success",
                                             "Message": {"Id": self.leads[phone]}})  # fmt: skip
        if path.endswith("ByEmailAddress"):
            return httpx.Response(200, json=[{"UserId": "user-1"}])
        if path.endswith("CreateType"):
            code = "207" if body["ActivityEventName"].startswith("Call notes") else "206"
            return httpx.Response(200, json={"Status": "Success", "Message": {"Id": code}})
        if path.endswith(("LogCall", "ProspectActivity.svc/Create")):
            return httpx.Response(200, json={"Status": "Success", "Message": {"Id": "act-1"}})
        # HubSpot (paths from developers.hubspot.com)
        if path == "/crm/objects/2026-09/contacts/search":
            number = body["filterGroups"][0]["filters"][0]["value"]
            found = self.leads.get(number)
            results = [{"id": found}] if found else []
            return httpx.Response(200, json={"total": len(results), "results": results})
        if path == "/crm/v3/owners":
            owners = [{"id": i, "email": e} for e, i in self.owners.items()]
            return httpx.Response(200, json={"results": owners})
        if path == "/crm/v3/objects/contacts":
            self.leads[national(body["properties"]["phone"])] = "hs-new"
            return httpx.Response(201, json={"id": "hs-new"})
        if path in ("/crm/v3/objects/calls", "/crm/v3/objects/notes"):
            return httpx.Response(201, json={"id": path.rsplit("/", 1)[1] + "-1"})
        if path == "/lookup":
            return httpx.Response(200, json={"lead_id": self.leads.get(body["phone"])})
        if path == "/create":
            self.leads[body["phone"]] = "c-1"
            return httpx.Response(200, json={"lead_id": "c-1"})
        if path == "/activity":
            return httpx.Response(200, json={"activity_id": "a-1"})
        return httpx.Response(404)

    def to(self, ending: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith(ending)]


@pytest.fixture
def crm(monkeypatch):
    f = FakeCrm()
    monkeypatch.setattr(
        B, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(f.handler))
    )
    monkeypatch.setattr(C, "check_url", lambda url: url)  # no DNS in tests
    return f


async def _setup(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"], phone="98765 43210",
                           owner_user_id=str(rep_id))).json()  # fmt: skip
    return tenant_id, c, admin, rep_id, rep, lead


def _lsq(**extra):
    return {"provider": "leadsquared", "host": LSQ, "access_key": "u$abc123access",
            "secret_key": "s3cr3t-key-value", **extra}  # fmt: skip


async def _call(c, rep, number="98765 43210", **extra):
    body = {"external_id": uuid.uuid4().hex, "direction": "out", "status": "answered",
            "number": number, "started_at": datetime.now(UTC).isoformat(),
            "duration_seconds": 95, **extra}  # fmt: skip
    r = await c.post("/api/v1/calls", json=body, headers=rep)
    assert r.status_code == 200, r.text
    return r.json()["call"]


async def _syncs(tenant_id):
    async with tenant_session(tenant_id) as db:
        return list((await db.scalars(select(CrmSync).order_by(CrmSync.created_at))).all())


async def _due_now(tenant_id):
    async with tenant_session(tenant_id) as db:
        await db.execute(update(CrmSync).values(next_try_at=S.now() - timedelta(seconds=1)))


async def test_leadsquared_gets_each_call_once_on_the_right_lead(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    crm.leads["919876543210"] = "lsq-asha"
    before = await _call(c, rep)  # before connecting: never sent

    put = await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    test = await c.post("/api/v1/crm-connection/test", json={"phone": "98765 43210"},
                        headers=admin)  # fmt: skip
    call = await _call(c, rep, direction="in", status="missed")
    await _call(c, rep)
    first = await S.run_tenant(tenant_id)
    again = await S.run_tenant(tenant_id)  # nothing new: nothing sent twice
    syncs = await _syncs(tenant_id)
    got = await c.get("/api/v1/crm-connection", headers=admin)

    assert put.status_code == 200, put.text
    assert put.json()["activity_event"] == 206  # the WhatsApp activity type, made once
    assert put.json()["key_hint"] == "••••cess" and "s3cr3t" not in put.text
    assert "u$abc123access" not in got.text and "s3cr3t" not in got.text
    assert test.json() == {"ok": True, "lead_id": "lsq-asha", "error": None}
    assert first == {"made": 2, "sent": 2} and again == {"made": 0, "sent": 0}
    assert [s.status for s in syncs] == ["sent", "sent"]
    assert all(s.external_lead_id == "lsq-asha" for s in syncs)
    assert before["id"] not in {str(s.ref_id) for s in syncs}
    logged = [json.loads(r.content) for r in crm.to("Telephony.svc/LogCall")]
    assert len(logged) == 2
    missed = next(b for b in logged if b["Direction"] == "Inbound")
    assert missed["Status"] == "Missed" and missed["LeadId"] == "lsq-asha"
    assert missed["SourceNumber"] == "+919876543210" and missed["UserId"] == "user-1"
    assert missed["CallSessionId"] == call["id"] and missed["CallDuration"] == 0
    for r in crm.requests:  # keys in LeadSquared's headers, never in the address
        assert r.headers["x-LSQ-AccessKey"] == "u$abc123access"
        assert "secret" not in str(r.url).lower()
    async with tenant_session(tenant_id) as db:
        ref = await db.scalar(select(ExternalRef).where(ExternalRef.system == "leadsquared"))
    assert ref.external_id == "lsq-asha" and str(ref.lead_id) == lead["id"]
    assert len(crm.to("RetrieveLeadByPhoneNumber")) == 2  # the test, then once: then kept


async def test_a_lead_missing_in_the_crm_is_made_there_or_skipped(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    await c.put("/api/v1/crm-connection", json=_lsq(create_leads=False), headers=admin)
    await _call(c, rep)
    await S.run_tenant(tenant_id)
    skipped = (await _syncs(tenant_id))[0]

    await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    retry = await c.post(f"/api/v1/crm-connection/syncs/{skipped.id}/retry", headers=admin)
    await S.run_tenant(tenant_id)
    made = (await _syncs(tenant_id))[0]

    assert skipped.status == "skipped" and "aren't created" in skipped.last_error
    assert retry.status_code == 200 and made.status == "sent"
    created = json.loads(crm.to("Lead.Create")[0].content)
    assert {"Attribute": "Phone", "Value": "+919876543210"} in created
    assert {"Attribute": "OwnerId", "Value": "user-1"} in created  # the lead's owner
    assert made.external_lead_id == "lsq-1"


async def test_busy_is_tried_later_and_wrong_keys_fail_at_once(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    crm.leads["919876543210"] = "lsq-asha"
    await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    await _call(c, rep)
    crm.busy = 1
    await S.run_tenant(tenant_id)
    waiting = (await _syncs(tenant_id))[0]
    await S.run_tenant(tenant_id)  # not due yet: nothing happens
    await _due_now(tenant_id)
    await S.run_tenant(tenant_id)
    sent = (await _syncs(tenant_id))[0]

    await _call(c, rep)
    crm.status = 401
    await S.run_tenant(tenant_id)
    refused = (await _syncs(tenant_id))[1]
    shown = (await c.get("/api/v1/crm-connection", headers=admin)).json()

    assert waiting.status == "pending" and waiting.attempts == 1
    assert "too many requests" in waiting.last_error
    assert sent.status == "sent" and sent.attempts == 2
    assert refused.status == "failed" and refused.attempts == 1
    assert "refused the keys" in shown["last_error"]


async def test_custom_crm_works_with_any_crm_signed(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    body = {"provider": "custom", "lookup_url": "https://crm.example.com/lookup",
            "create_url": "https://crm.example.com/create",
            "activity_url": "https://crm.example.com/activity"}  # fmt: skip
    put = await c.put("/api/v1/crm-connection", json=body, headers=admin)
    again = await c.put("/api/v1/crm-connection", json=body, headers=admin)
    plain = await c.put("/api/v1/crm-connection", json={**body, "lookup_url": "http://x.com"},
                        headers=admin)  # fmt: skip
    secret = put.json()["signing_secret"]
    await _call(c, rep)
    await S.run_tenant(tenant_id)

    assert put.status_code == 200 and secret and again.json()["signing_secret"] is None
    assert plain.json()["code"] == "crm_urls"
    lookup, create, activity = crm.requests
    assert json.loads(lookup.content) == {"phone": "+919876543210"}
    assert json.loads(create.content)["phone"] == "+919876543210"
    sent = json.loads(activity.content)
    assert sent["lead_id"] == "c-1" and sent["type"] == "call" and sent["duration_seconds"] == 95
    ts = activity.headers["X-Versnq-Timestamp"]
    want = hmac.new(secret.encode(), f"{ts}.{activity.content.decode()}".encode(),
                    hashlib.sha256).hexdigest()  # fmt: skip
    assert activity.headers["X-Versnq-Signature"] == f"sha256={want}"
    assert (await _syncs(tenant_id))[0].external_activity_id == "a-1"


async def test_whatsapp_messages_go_to_the_crm_but_emails_dont(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    crm.leads["919876543210"] = "lsq-asha"
    await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    async with tenant_session(tenant_id) as db:
        for channel, text in (("whatsapp", "Is the batch full?"), ("email", "An email")):
            msg = Message(
                id=uuid.uuid4(), tenant_id=tenant_id, lead_id=uuid.UUID(lead["id"]),
                channel=channel, direction="in", to_address="us", from_address="+919876543210",
                body=text, token=secrets.token_urlsafe(16), status="received",
            )  # fmt: skip
            db.add(msg)
            await db.flush()
            await message_event(db, msg, channel=channel)
    await S.run_tenant(tenant_id)

    posted = [json.loads(r.content) for r in crm.to("ProspectActivity.svc/Create")]
    assert len(posted) == 1 and [s.kind for s in await _syncs(tenant_id)] == ["whatsapp"]
    assert posted[0]["RelatedProspectId"] == "lsq-asha" and posted[0]["ActivityEvent"] == 206
    assert posted[0]["ActivityNote"] == "WhatsApp from the lead: Is the batch full?"


async def test_only_admins_and_never_another_company(ws, crm, client_for):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    by_rep = await c.put("/api/v1/crm-connection", json=_lsq(), headers=rep)
    await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    await _call(c, rep)
    await S.run_tenant(tenant_id)
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    other = client_for(other_slug)

    theirs = await other.get("/api/v1/crm-connection", headers=other_admin)
    their_syncs = await other.get("/api/v1/crm-connection/syncs", headers=other_admin)
    gone = await c.delete("/api/v1/crm-connection", headers=admin)

    assert by_rep.status_code == 403
    assert theirs.json()["connected"] is False and their_syncs.json() == []
    assert gone.status_code == 204 and await _syncs(tenant_id) == []
    assert (await c.get("/api/v1/crm-connection", headers=admin)).json()["connected"] is False


async def test_calls_and_whatsapp_plan_hides_the_crm_screens(ws):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "crm_screens", False)

    hidden = ("/api/v1/deals", "/api/v1/customers", "/api/v1/pipelines", "/api/v1/newsletters",
              "/api/v1/reports/saved", "/api/v1/landing-pages")  # fmt: skip
    for path in hidden:
        assert (await c.get(path, headers=admin)).status_code == 404, path
    assert (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).status_code == 200
    assert (await c.get("/api/v1/calls", headers=admin)).status_code == 200
    modules = {m["key"]: m["enabled"] for m in (await c.get("/api/v1/modules", headers=rep)).json()}
    assert modules["crm_screens"] is False  # the app hides the menu entries from this


MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 2000


async def _recorded_call(c, rep):
    call = await _call(c, rep)
    up = await c.put(f"/api/v1/calls/{call['id']}/recording", content=MP3,
                     headers={**rep, "X-File-Name": "call.mp3"})  # fmt: skip
    assert up.status_code == 200, up.text
    return call


def _notes(crm):
    return [json.loads(r.content) for r in crm.to("ProspectActivity.svc/Create")]


async def test_the_recording_goes_to_the_crm_as_a_private_link(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    crm.leads["919876543210"] = "lsq-asha"
    await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    call = await _recorded_call(c, rep)
    await S.run_tenant(tenant_id)
    await S.run_tenant(tenant_id)  # nothing twice

    syncs = {s.kind: s for s in await _syncs(tenant_id)}
    notes = _notes(crm)
    made = [json.loads(r.content)["ActivityEventName"] for r in crm.to("CreateType")]

    assert syncs["call"].status == "sent" and syncs["recording"].status == "sent"
    assert made == ["WhatsApp (Versnq)", "Call notes (Versnq)"]  # each type made once
    assert len(notes) == 1 and notes[0]["ActivityEvent"] == 207
    assert notes[0]["RelatedProspectId"] == "lsq-asha"
    link = notes[0]["ActivityNote"].removeprefix("Recording: ")
    assert f"/api/v1/calls/{call['id']}/recording/shared?until=" in link
    async with tenant_session(tenant_id) as db:
        from app.modules.connectors.models import CrmConnection

        conn = await db.scalar(select(CrmConnection))
    assert conn.config["notes_event"] == 207  # kept: the type isn't made again

    path = link[link.index("/api/") :]
    played = await c.get(path)  # the CRM has no Core login: the signature is the key
    forged = await c.get(path[:-4] + "0000")
    other = await c.get(path.replace(call["id"], str(uuid.uuid4())))
    until = int(path.split("until=")[1].split("&")[0])
    expired = await c.get(path.replace(f"until={until}", f"until={until - 40 * 86400}"))

    assert played.status_code == 200 and played.content == MP3
    assert played.headers["cache-control"] == "private, no-store"
    assert forged.status_code == other.status_code == expired.status_code == 404


async def test_with_ace_the_summary_and_link_go_as_one_note(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    crm.leads["919876543210"] = "lsq-asha"
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "ace", True)
    await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    call = await _recorded_call(c, rep)
    await S.run_tenant(tenant_id)
    before = len(_notes(crm))
    async with tenant_session(tenant_id) as db:
        from app.modules.calls.models import Call
        from app.modules.calls.service import save_analysis

        row = await db.get(Call, uuid.UUID(call["id"]))
        said = "Asked about the weekend batch; wants fees by email."
        await save_analysis(db, row, said, {"intent": "high",
                                            "next_step": "Email the fee sheet today"})  # fmt: skip
    await S.run_tenant(tenant_id)

    syncs = {s.kind: s for s in await _syncs(tenant_id)}
    notes = _notes(crm)
    assert before == 0 and "recording" not in syncs  # the summary's note carries the link
    assert syncs["summary"].status == "sent" and len(notes) == 1
    text = notes[0]["ActivityNote"]
    assert text.startswith("Summary: Asked about the weekend batch; wants fees by email.\n")
    assert "Next step: Email the fee sheet today\nRecording: https://" in text


async def test_custom_crm_gets_the_call_note(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    crm.leads["+919876543210"] = "c-9"
    body = {"provider": "custom", "lookup_url": "https://crm.example.com/lookup",
            "create_url": "https://crm.example.com/create",
            "activity_url": "https://crm.example.com/activity"}  # fmt: skip
    await c.put("/api/v1/crm-connection", json=body, headers=admin)
    call = await _recorded_call(c, rep)
    await S.run_tenant(tenant_id)

    sent = [json.loads(r.content) for r in crm.to("/activity")]
    note = next(x for x in sent if x["type"] == "call_note")
    assert note["lead_id"] == "c-9" and note["call_id"] == call["id"]
    assert "/recording/shared?until=" in note["recording_url"] and note["summary"] is None


async def test_hubspot_gets_calls_and_call_notes_on_the_contact(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    me = (await c.get("/api/v1/auth/me", headers=rep)).json()
    crm.leads["9876543210"] = "hs-asha"  # HubSpot compares the number without +91
    crm.owners[me["email"]] = "own-7"
    hub = {"provider": "hubspot", "token": "pat-na1-secret-token-1234"}
    put = await c.put("/api/v1/crm-connection", headers=admin, json=hub)
    keep = await c.put("/api/v1/crm-connection", headers=admin,
                       json={"provider": "hubspot", "send_whatsapp": False})  # fmt: skip
    test = await c.post("/api/v1/crm-connection/test", json={"phone": "98765 43210"},
                        headers=admin)  # fmt: skip
    call = await _recorded_call(c, rep)
    await _call(c, rep, direction="in", status="missed")
    await S.run_tenant(tenant_id)
    shown = (await c.get("/api/v1/crm-connection", headers=admin)).text

    assert put.status_code == 200 and put.json()["key_hint"] == "••••1234"
    assert keep.status_code == 200 and "pat-na1-secret" not in shown
    assert test.json()["lead_id"] == "hs-asha"
    assert all(r.headers["authorization"] == "Bearer pat-na1-secret-token-1234"
               for r in crm.requests)  # fmt: skip
    calls = [json.loads(r.content) for r in crm.to("/crm/v3/objects/calls")]
    out = next(x for x in calls if x["properties"]["hs_call_direction"] == "OUTBOUND")
    missed = next(x for x in calls if x["properties"]["hs_call_direction"] == "INBOUND")
    assert out["properties"]["hs_call_duration"] == 95_000  # milliseconds
    assert out["properties"]["hs_call_status"] == "COMPLETED"
    assert out["properties"]["hs_call_to_number"] == "+919876543210"
    assert out["properties"]["hubspot_owner_id"] == "own-7"
    assert out["associations"] == [{"to": {"id": "hs-asha"}, "types": [
        {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 194}]}]  # fmt: skip
    assert missed["properties"]["hs_call_status"] == "NO_ANSWER"
    note = json.loads(crm.to("/crm/v3/objects/notes")[0].content)
    assert note["associations"][0]["types"][0]["associationTypeId"] == 202
    body = note["properties"]["hs_note_body"]
    assert body.startswith("Call notes (Versnq)\nRecording: https://")
    assert f"/calls/{call['id']}/recording/shared" in body
    assert {s.status for s in await _syncs(tenant_id)} == {"sent"}


async def test_hubspot_creates_the_contact_when_missing(ws, crm):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    await c.put("/api/v1/crm-connection", headers=admin,
                json={"provider": "hubspot", "token": "pat-na1-secret-token-1234"})  # fmt: skip
    await _call(c, rep)
    await S.run_tenant(tenant_id)

    made = json.loads(crm.to("/crm/v3/objects/contacts")[0].content)
    assert made["properties"]["phone"] == "+919876543210"
    assert made["properties"]["firstname"] == "Rahul"
    assert (await _syncs(tenant_id))[0].external_lead_id == "hs-new"

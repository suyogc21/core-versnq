"""Step 9b-1 (Decision log #40): conversations, replies, colleagues, notes, attachments."""

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead, Notification
from app.modules.engage import engine as E
from app.modules.engage import inbox as IB
from app.modules.engage.models import Enrolment, Message
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as, make_workspace

ALWAYS = {"from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "daily_cap": 200}
PDF = b"%PDF-1.4\n" + b"x" * 300


@pytest.fixture(autouse=True)
def files_dir(tmp_path):
    s = get_settings()
    old = s.files_dir
    s.files_dir = str(tmp_path / "files")
    yield
    s.files_dir = old


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = dict(ALWAYS)
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, client_for(slug), admin


async def _lead(c, h, email="asha@example.com"):
    _, sources = await setup_ids(c, h)
    phone = f"98{uuid.uuid4().int % 10**8:08d}"
    r = await new_lead(
        c, h, sources["Website"], first_name="Asha",
        identities=[{"type": "email", "value": email}, {"type": "phone", "value": phone}],
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def _email(
    frm, subject, body="Yes, interested!", *, reply_to_id=None, cc=(), attach=None, msg_id=None
):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = "hello@company.example"
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Subject"] = subject
    m["Message-ID"] = msg_id or f"<{uuid.uuid4().hex}@mail.example>"
    if reply_to_id:
        m["In-Reply-To"] = reply_to_id
        m["References"] = reply_to_id
    m.set_content(body)
    if attach:
        name, data, maintype, subtype = attach
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()


async def _ingest(tenant_id, raw):
    async with tenant_session(tenant_id) as db:
        msg = await IB.ingest(db, tenant_id, raw)
        return str(msg.conversation_id) if msg else None


async def _sequence_email(c, h, tenant_id, lead):
    t = (
        await c.post(
            "/api/v1/templates",
            json={
                "name": f"T{uuid.uuid4().hex[:4]}",
                "subject": "Hello {{lead.first_name}}",
                "body": "Hi",
            },
            headers=h,
        )
    ).json()
    s = (
        await c.post("/api/v1/sequences", json={"name": f"S{uuid.uuid4().hex[:4]}"}, headers=h)
    ).json()
    await c.put(
        f"/api/v1/sequences/{s['id']}/steps",
        json=[
            {"kind": "email", "template_id": t["id"]},
            {"kind": "wait", "hours": 24},
            {"kind": "email", "template_id": t["id"]},
        ],
        headers=h,
    )
    await c.patch(f"/api/v1/sequences/{s['id']}", json={"is_active": True}, headers=h)
    await c.post(f"/api/v1/sequences/{s['id']}/enrol", json={"lead_ids": [lead["id"]]}, headers=h)
    await E.run_due(tenant_id)
    async with tenant_session(tenant_id) as db:
        return await db.scalar(select(Message).where(Message.lead_id == uuid.UUID(lead["id"])))


# ---------- incoming ----------
async def test_a_reply_threads_stops_the_sequence_and_lands_in_the_owners_inbox(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep)
    sent = await _sequence_email(c, admin, tenant_id, lead)
    assert sent.message_id_header and sent.conversation_id
    conv_id = await _ingest(
        tenant_id,
        _email("Asha <ASHA@example.com>", "Re: Hello Asha", reply_to_id=sent.message_id_header),
    )
    assert conv_id == str(sent.conversation_id)
    async with tenant_session(tenant_id) as db:
        e = await db.scalar(select(Enrolment))
        assert e.status == "stopped" and e.ended_reason == "reply"
        assert (await db.get(Message, sent.id)).replied_at is not None
        assert await db.scalar(select(Event.id).where(Event.type == "sequence.replied"))
        assert await db.scalar(select(Notification.id).where(Notification.user_id == rep_id))
    mine = (await c.get("/api/v1/inbox", headers=rep)).json()
    assert (
        len(mine) == 1
        and mine[0]["waiting"]
        and mine[0]["unread"]
        and mine[0]["snippet"].startswith("Yes")
    )
    detail = (await c.get(f"/api/v1/conversations/{conv_id}", headers=rep)).json()
    assert [m["direction"] for m in detail["messages"]] == ["out", "in"]
    assert detail["messages"][0]["from_sequence"] is True
    assert (await c.get("/api/v1/inbox", headers=rep)).json()[0]["unread"] is False  # opened
    timeline = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)).json()
    items = timeline["items"] if isinstance(timeline, dict) else timeline
    assert any(a["type_key"] == "email_received" for a in items)


async def test_unknown_senders_and_repeats_are_not_stored(ws):
    tenant_id, c, admin = ws
    await _lead(c, admin)
    assert await _ingest(tenant_id, _email("stranger@nowhere.example", "Hello")) is None
    raw = _email("asha@example.com", "Question", msg_id="<same-1@mail.example>")
    first = await _ingest(tenant_id, raw)
    assert first is not None and await _ingest(tenant_id, raw) is None
    async with tenant_session(tenant_id) as db:
        assert len((await db.scalars(select(Message))).all()) == 1


async def test_threads_by_subject_when_headers_are_missing(ws):
    tenant_id, c, admin = ws
    await _lead(c, admin)
    a = await _ingest(tenant_id, _email("asha@example.com", "Fees for the course"))
    b = await _ingest(
        tenant_id, _email("asha@example.com", "RE: Fees for the course", "And the EMI?")
    )
    other = await _ingest(tenant_id, _email("asha@example.com", "Different question"))
    assert a == b and other != a


async def test_cc_and_attachments_are_kept_and_a_file_goes_to_the_checklist(ws):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    conv = await _ingest(
        tenant_id,
        _email(
            "asha@example.com",
            "My PAN",
            cc=["dad@example.com"],
            attach=("pan.pdf", PDF, "application", "pdf"),
        ),
    )
    exe = await _ingest(
        tenant_id,
        _email(
            "asha@example.com",
            "My PAN",
            attach=("run.exe", b"MZ\x90\x00" + b"0" * 100, "application", "octet-stream"),
        ),
    )
    d = (await c.get(f"/api/v1/conversations/{conv}", headers=admin)).json()
    first, second = d["messages"]
    assert first["cc"] == ["dad@example.com"] and first["attachments"][0]["name"] == "pan.pdf"
    assert exe == conv and second["attachments"] == [] and "run.exe" in second["error"]
    file_id = first["attachments"][0]["file_id"]
    got = await c.get(f"/api/v1/conversations/{conv}/attachments/{file_id}", headers=admin)
    assert got.status_code == 200 and got.content == PDF
    # into the customer's checklist
    cust = (await c.post(f"/api/v1/leads/{lead['id']}/customer", json={}, headers=admin)).json()
    added = (
        await c.post(
            f"/api/v1/customers/{cust['id']}/documents", json={"name": "PAN card"}, headers=admin
        )
    ).json()
    doc = next(x for x in added["documents"] if x["name"] == "PAN card")
    r = await c.post(
        f"/api/v1/conversations/{conv}/attachments/{file_id}/to-document",
        json={"document_id": doc["id"]},
        headers=admin,
    )
    assert r.status_code == 204, r.text
    after = (await c.get(f"/api/v1/customers/{cust['id']}/documents", headers=admin)).json()
    assert next(x for x in after["documents"] if x["id"] == doc["id"])["status"] == "received"


# ---------- outgoing ----------
async def test_reply_from_the_crm_threads_and_counts_as_contact(ws):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    conv = await _ingest(
        tenant_id, _email("asha@example.com", "Fees", msg_id="<in-1@mail.example>")
    )
    r = await c.post(
        f"/api/v1/conversations/{conv}/reply",
        json={"body": "It is 80,000.", "cc": ["boss@company.example"]},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    out = r.json()["messages"][-1]
    assert (
        out["direction"] == "out"
        and out["subject"] == "Re: Fees"
        and out["cc"] == ["boss@company.example"]
    )
    async with tenant_session(tenant_id) as db:
        m = await db.get(Message, uuid.UUID(out["id"]))
        assert m.in_reply_to == "<in-1@mail.example>" and m.status == "sent"
    assert (await c.get("/api/v1/inbox?view=waiting", headers=admin)).json() == []
    got = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()
    assert got["last_contacted_at"]
    bad_cc = await c.post(
        f"/api/v1/conversations/{conv}/reply", json={"body": "x", "cc": ["nope"]}, headers=admin
    )
    assert bad_cc.status_code == 422


async def test_opt_out_and_suppression_rules_for_one_to_one(ws):
    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    v = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()
    await c.post(
        f"/api/v1/leads/{lead['id']}/consents",
        json={"channel": "email", "status": "opted_out"},
        headers=admin,
    )
    new = await c.post(
        f"/api/v1/leads/{lead['id']}/emails", json={"subject": "Offer", "body": "Hi"}, headers=admin
    )
    assert new.status_code == 422 and "opted out" in new.json()["detail"]
    conv = await _ingest(tenant_id, _email("asha@example.com", "A question"))
    assert (
        await c.post(f"/api/v1/conversations/{conv}/reply", json={"body": "Sure"}, headers=admin)
    ).status_code == 200
    async with tenant_session(tenant_id) as db:
        from app.modules.crm import consent as C

        await C.suppress(db, tenant_id, "email", ["asha@example.com"], "bounce")
    assert (
        await c.post(f"/api/v1/conversations/{conv}/reply", json={"body": "Again"}, headers=admin)
    ).status_code == 422
    assert v  # lead existed


# ---------- people ----------
async def test_a_colleague_added_sees_the_conversation_but_not_the_whole_lead(ws):
    tenant_id, c, admin = ws
    a_id, a = await login_as(tenant_id, "sales_user")
    b_id, b = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, a)
    conv = await _ingest(tenant_id, _email("asha@example.com", "Pricing"))
    assert (await c.get(f"/api/v1/conversations/{conv}", headers=b)).status_code == 404
    r = await c.post(
        f"/api/v1/conversations/{conv}/members", json={"user_id": str(b_id)}, headers=a
    )
    assert r.status_code == 200
    seen = (await c.get(f"/api/v1/conversations/{conv}", headers=b)).json()
    assert seen["lead"]["name"] == "Asha" and seen["lead"]["can_open"] is False
    assert (await c.get(f"/api/v1/leads/{lead['id']}", headers=b)).status_code == 404
    assert (await c.get("/api/v1/inbox?view=shared", headers=b)).json()[0]["id"] == conv
    assert (
        await c.post(f"/api/v1/conversations/{conv}/reply", json={"body": "Hi from B"}, headers=b)
    ).status_code == 200
    # b cannot hand it on; a can remove b
    assert (
        await c.put(
            f"/api/v1/conversations/{conv}/assignee", json={"user_id": str(b_id)}, headers=b
        )
    ).status_code == 403
    await c.delete(f"/api/v1/conversations/{conv}/members/{b_id}", headers=a)
    assert (await c.get(f"/api/v1/conversations/{conv}", headers=b)).status_code == 404


async def test_notes_are_internal_and_mentions_tell_people(ws):
    tenant_id, c, admin = ws
    a_id, a = await login_as(tenant_id, "sales_user")
    b_id, _ = await login_as(tenant_id, "sales_user")
    await _lead(c, a)
    conv = await _ingest(tenant_id, _email("asha@example.com", "Pricing"))
    r = await c.post(
        f"/api/v1/conversations/{conv}/notes",
        json={"body": "@B can you confirm the price?", "mention_ids": [str(b_id)]},
        headers=a,
    )
    d = r.json()
    assert d["notes"][0]["body"].startswith("@B") and any(
        m["user_id"] == str(b_id) for m in d["members"]
    )
    async with tenant_session(tenant_id) as db:
        assert len((await db.scalars(select(Message))).all()) == 1  # nothing was emailed
        assert await db.scalar(
            select(Notification.id).where(
                Notification.user_id == b_id, Notification.kind == "inbox"
            )
        )


async def test_take_over_and_private(ws):
    tenant_id, c, admin = ws
    a_id, a = await login_as(tenant_id, "sales_user")
    m_id, m = await login_as(tenant_id, "sales_manager")
    await make_team(tenant_id, m_id, [a_id])
    await _lead(c, a)
    conv = await _ingest(tenant_id, _email("asha@example.com", "Pricing"))
    r = await c.put(
        f"/api/v1/conversations/{conv}/assignee", json={"user_id": str(m_id)}, headers=m
    )
    assert r.status_code == 200 and r.json()["assignee_id"] == str(m_id)
    assert (await c.get("/api/v1/inbox", headers=m)).json()[0]["id"] == conv
    assert (await c.get("/api/v1/inbox", headers=a)).json() == []
    await c.put(f"/api/v1/conversations/{conv}/assignee", json={"user_id": None}, headers=m)
    assert (
        await c.patch(f"/api/v1/conversations/{conv}", json={"is_private": True}, headers=a)
    ).status_code == 200
    assert (
        await c.get(f"/api/v1/conversations/{conv}", headers=m)
    ).status_code == 404  # private: not even the manager
    assert (await c.get(f"/api/v1/conversations/{conv}", headers=admin)).status_code == 200


async def test_merge_moves_conversations(ws):
    tenant_id, c, admin = ws
    keep = await _lead(c, admin, "keep@example.com")
    other = await _lead(c, admin, "other@example.com")
    conv = await _ingest(tenant_id, _email("other@example.com", "Hi"))
    r = await c.post(
        "/api/v1/leads/merge",
        json={
            "survivor_id": keep["id"],
            "survivor_version": keep["version"],
            "other_id": other["id"],
            "other_version": other["version"],
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    convs = (await c.get(f"/api/v1/leads/{keep['id']}/conversations", headers=admin)).json()
    assert [x["id"] for x in convs] == [conv]


async def test_saved_replies(ws):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    assert (
        await c.post(
            "/api/v1/canned-replies",
            json={"name": "Fees", "body": "x", "is_shared": True},
            headers=rep,
        )
    ).status_code == 403
    await c.post("/api/v1/canned-replies", json={"name": "Mine", "body": "x"}, headers=rep)
    await c.post(
        "/api/v1/canned-replies",
        json={"name": "Team", "body": "y", "is_shared": True},
        headers=admin,
    )
    await c.post("/api/v1/canned-replies", json={"name": "Admin's own", "body": "z"}, headers=admin)
    assert [x["name"] for x in (await c.get("/api/v1/canned-replies", headers=rep)).json()] == [
        "Mine",
        "Team",
    ]


async def test_test_inbound_and_isolation(ws, client_for):
    tenant_id, c, admin = ws
    await _lead(c, admin)
    r = await c.post(
        "/api/v1/inbox/test-inbound",
        content=_email("asha@example.com", "Hello"),
        headers=admin | {"Content-Type": "message/rfc822"},
    )
    assert r.json()["stored"] is True
    conv = r.json()["conversation_id"]
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)
    assert (await oc.get(f"/api/v1/conversations/{conv}", headers=other_admin)).status_code == 404
    assert (await oc.get("/api/v1/inbox?view=all", headers=other_admin)).json() == []
    _, rep = await login_as(tenant_id, "sales_user")
    assert (
        await c.post("/api/v1/inbox/test-inbound", content=b"x", headers=rep)
    ).status_code == 403


# ---------- message.received / message.sent (Decision log #43) ----------
async def _message_events(tenant_id):
    async with tenant_session(tenant_id) as db:
        rows = (
            await db.scalars(
                select(Event).where(Event.type.like("message.%")).order_by(Event.occurred_at)
            )
        ).all()
        return [(e.type, e.payload) for e in rows]


async def test_emails_in_and_out_raise_one_message_event_each(ws, client_for):
    from app.core.modules import set_module

    tenant_id, c, admin = ws
    lead = await _lead(c, admin)
    raw = _email("asha@example.com", "Fees", msg_id="<ev-1@mail.example>")
    conv = await _ingest(tenant_id, raw)
    await _ingest(tenant_id, raw)  # the same email seen twice: no second event
    events = await _message_events(tenant_id)
    assert [t for t, _ in events] == ["message.received"]
    p = events[0][1]
    assert p["conversation_id"] == conv and p["lead_id"] == lead["id"]
    assert p["channel"] == "email" and p["direction"] == "in" and p["official"] is None
    assert set(p) == {
        "_actor",
        "conversation_id", "lead_id", "message_id", "channel", "direction", "official",
        "contact_id", "campaign_id", "mailbox_id", "auto_submitted",
    }  # fmt: skip

    r = await c.post(f"/api/v1/conversations/{conv}/reply", json={"body": "80,000"}, headers=admin)
    assert r.status_code == 200, r.text
    events = await _message_events(tenant_id)
    assert [t for t, _ in events] == ["message.received", "message.sent"]
    assert events[1][1]["message_id"] == r.json()["messages"][-1]["id"]

    # sent from the user's own mail app (Sent folder / copy-in): one message.sent
    out = EmailMessage()
    out["From"], out["To"], out["Subject"] = "admin@company.example", "asha@example.com", "Hi"
    out["Message-ID"] = "<own-1@mail.example>"
    out.set_content("Sent from Gmail")
    async with tenant_session(tenant_id) as db:
        lead_row = await db.get(Lead, uuid.UUID(lead["id"]))
        await IB.ingest_sent(db, out.as_bytes(), lead_row, user_id=None, from_address="a@x")
    assert [t for t, _ in await _message_events(tenant_id)][-1] == "message.sent"
    n = len(await _message_events(tenant_id))

    # older emails pulled in when a mailbox is first connected: no events
    async with tenant_session(tenant_id) as db:
        await IB.ingest(db, tenant_id, _email("asha@example.com", "Old"), quiet=True)
        old = EmailMessage()
        old["From"], old["To"], old["Subject"] = "a@x", "asha@example.com", "Old out"
        old["Message-ID"] = "<own-old@mail.example>"
        old.set_content("old")
        lead_row = await db.get(Lead, uuid.UUID(lead["id"]))
        await IB.ingest_sent(
            db, old.as_bytes(), lead_row, user_id=None, from_address="a@x", quiet=True
        )
    assert len(await _message_events(tenant_id)) == n

    # inbox module off: nothing is raised
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "inbox", False)
    await _ingest(tenant_id, _email("asha@example.com", "While off"))
    assert len(await _message_events(tenant_id)) == n

    # another company never sees them
    other_id, _ = await make_workspace()
    assert await _message_events(other_id) == []

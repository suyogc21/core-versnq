"""Step O2 (Decision log #44): campaigns. "Already your lead? Never a cold email." Import with
its report, launch checks, the runner (steps, versions split evenly, the same inbox for the same
person, threads, limits, sending hours, waiting not skipping), the promise checked at every send,
replies (stop only that person; auto-replies don't), unsubscribe / bounce, the outreach inbox,
answering, Convert to lead, who sees what, another company sees nothing."""

import uuid
from datetime import timedelta
from email.message import EmailMessage
from email.utils import make_msgid

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead, Suppression
from app.modules.engage import engine as E
from app.modules.engage import inbox as IB
from app.modules.engage.models import Conversation, Mailbox, Message
from app.modules.outreach import engine as OE
from app.modules.outreach.models import CampaignContact, Contact
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace, switch_on

ALWAYS = {"days": [0, 1, 2, 3, 4, 5, 6], "from": "00:00", "to": "24:00"}


@pytest.fixture(autouse=True)
def dirs(tmp_path):
    s = get_settings()
    old = (s.files_dir, s.mailbox_test_dir, s.mail_outbox_dir)
    s.files_dir = str(tmp_path / "files")
    s.mailbox_test_dir = str(tmp_path / "mailboxes")
    s.mail_outbox_dir = str(tmp_path / "outbox")
    yield tmp_path
    s.files_dir, s.mailbox_test_dir, s.mail_outbox_dir = old


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    await switch_on(tenant_id, "outreach")
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, client_for(slug), admin


async def _inbox(c, h, address, **extra):
    body = {
        "email_address": address, "password": "app-pass-1", "imap_host": "imap.mail.example",
        "smtp_host": "smtp.mail.example", "min_gap_minutes": 0, **extra,
    }  # fmt: skip
    r = await c.post("/api/v1/sending-inboxes", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _csv(rows: list[tuple]) -> str:
    lines = ["Email,First name,Company,City"]
    lines += [",".join(r) for r in rows]
    return "\n".join(lines) + "\n"


def _people(n: int, tag: str = "") -> list[tuple]:
    return [(f"p{i}{tag}-{uuid.uuid4().hex[:6]}@prospect.example", f"Pat{i}", f"Co{i}", "Pune")
            for i in range(n)]  # fmt: skip


STEPS = [
    {"wait_days": 0, "variants": [
        {"subject": "Quick idea for {{company}}", "body": "Hi {{first_name|there}}, version A"},
        {"subject": "{{first_name|Hi}}, a thought", "body": "Hi {{first_name|there}}, version B"},
    ]},
    {"wait_days": 0, "variants": [{"subject": "", "body": "Following up, {{first_name|there}}"}]},
]  # fmt: skip


async def _campaign(c, h, rows, *, steps=STEPS, mailbox_ids=(), schedule=ALWAYS, **extra):
    r = await c.post(
        "/api/v1/campaigns",
        json={"name": f"C{uuid.uuid4().hex[:4]}", "schedule": schedule,
              "mailbox_ids": list(mailbox_ids), **extra},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    if steps:
        r = await c.put(f"/api/v1/campaigns/{cid}/steps", json={"steps": steps}, headers=h)
        assert r.status_code == 200, r.text
    if rows:
        r = await c.post(
            f"/api/v1/campaigns/{cid}/contacts/import", json={"csv": _csv(rows)}, headers=h
        )
        assert r.status_code == 200, r.text
    return cid


async def _launch(c, h, cid):
    r = await c.post(f"/api/v1/campaigns/{cid}/launch", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def _sent(tenant_id, campaign_id):
    async with tenant_session(tenant_id) as db:
        return (
            await db.scalars(
                select(Message)
                .where(Message.campaign_id == uuid.UUID(campaign_id), Message.direction == "out")
                .order_by(Message.created_at)
            )
        ).all()


async def _places(tenant_id, campaign_id):
    async with tenant_session(tenant_id) as db:
        rows = await db.execute(
            select(Contact.email, CampaignContact)
            .join(Contact, Contact.id == CampaignContact.contact_id)
            .where(CampaignContact.campaign_id == uuid.UUID(campaign_id))
        )
        return {e: cc for e, cc in rows.all()}


async def _reply_to(tenant_id, msg: Message, body="Sounds good, tell me more", **headers):
    m = EmailMessage()
    m["From"] = msg.to_address
    m["To"] = msg.from_address
    m["Subject"] = f"Re: {msg.subject}"
    m["Message-ID"] = make_msgid(domain="prospect.example")
    m["In-Reply-To"] = msg.message_id_header
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    async with tenant_session(tenant_id) as db:
        return await IB.ingest(db, tenant_id, m.as_bytes())


# ---------- switch and permissions ----------
async def test_outreach_is_off_until_switched_on(client_for):
    tenant_id, slug = await make_workspace()
    _, admin = await login_as(tenant_id, "admin")
    assert (await client_for(slug).get("/api/v1/campaigns", headers=admin)).status_code == 404


async def test_reps_cannot_build_campaigns_and_see_only_their_own(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    mine = await _campaign(c, admin, [], owner_user_id=str(rep_id))
    await _campaign(c, admin, [])

    assert (await c.post("/api/v1/campaigns", json={"name": "x"}, headers=rep)).status_code == 403
    seen = [x["id"] for x in (await c.get("/api/v1/campaigns", headers=rep)).json()]
    assert seen == [mine]
    assert len((await c.get("/api/v1/campaigns", headers=admin)).json()) == 2


# ---------- import ----------
async def test_import_report_skips_leads_blocked_bad_and_repeated_rows(ws):
    tenant_id, c, admin = ws
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"],
                   identities=[{"type": "email", "value": "known@customer.example"}])  # fmt: skip
    async with tenant_session(tenant_id) as db:
        from app.modules.crm import consent as C

        await C.suppress(db, tenant_id, "email", ["gone@prospect.example"], "opt_out")
    people = _people(3)
    rows = [*people, people[0], ("not-an-email", "X", "Y", "Z"), ("known@customer.example",
            "K", "C", "D"), ("gone@prospect.example", "G", "C", "D")]  # fmt: skip
    cid = await _campaign(c, admin, [])
    url = f"/api/v1/campaigns/{cid}/contacts/import"

    dry = (await c.post(url, json={"csv": _csv(rows), "dry_run": True}, headers=admin)).json()
    real = (await c.post(url, json={"csv": _csv(rows)}, headers=admin)).json()
    again = (await c.post(url, json={"csv": _csv(rows)}, headers=admin)).json()

    for r in (dry, real):
        assert (r["added"], r["duplicates_in_file"], r["invalid_email"]) == (3, 1, 1)
        assert (r["already_lead"], r["suppressed"]) == (1, 1)
    assert dry["mapping"]["Email"] == "email" and dry["mapping"]["City"] == "variable"
    assert real["variables"] == ["city"]
    assert {p["reason"] for p in real["problems"]} >= {"already a lead or customer"}
    assert again["added"] == 0 and again["already_in_campaign"] == 3
    listed = (await c.get(f"/api/v1/campaigns/{cid}/contacts", headers=admin)).json()
    assert len(listed) == 3 and listed[0]["contact"]["variables"] == {"city": "Pune"}
    assert {x["status"] for x in listed} == {"pending"}


async def test_launch_says_what_is_missing(ws):
    tenant_id, c, admin = ws
    cid = await _campaign(c, admin, [], steps=None)
    r = await c.post(f"/api/v1/campaigns/{cid}/launch", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "campaign_not_ready"
    assert {"Add at least one step", "Add contacts"} <= set(r.json()["problems"])

    await _inbox(c, admin, "a@send.example")
    steps = [{"variants": [{"subject": "Hi", "body": "About {{pain_point}}"}]}]
    cid = await _campaign(c, admin, _people(2), steps=steps)
    r = await c.post(f"/api/v1/campaigns/{cid}/launch", headers=admin)
    assert r.status_code == 422 and "pain_point" in r.json()["detail"]


# ---------- the runner ----------
async def test_steps_go_out_in_order_split_across_versions_same_inbox_same_thread(ws):
    tenant_id, c, admin = ws
    boxes = [await _inbox(c, admin, f"s{i}@send.example") for i in range(2)]
    cid = await _campaign(c, admin, _people(4))
    await _launch(c, admin, cid)

    assert await OE.run_due(tenant_id) == 4
    first = await _sent(tenant_id, cid)
    assert len(first) == 4 and all(m.status == "sent" for m in first)
    assert sorted(m.variant for m in first) == [0, 0, 1, 1]
    assert {str(m.mailbox_id) for m in first} == set(boxes)  # spread across the pool
    assert "Hi Pat" in first[0].body and first[0].lead_id is None and first[0].contact_id

    await OE.run_due(tenant_id)
    both = await _sent(tenant_id, cid)
    follow = both[4:]
    assert len(follow) == 4
    by_contact = {m.contact_id: m for m in first}
    for m in follow:
        before = by_contact[m.contact_id]
        assert m.mailbox_id == before.mailbox_id  # the same inbox for the same person
        assert m.in_reply_to == before.message_id_header and m.subject.startswith("Re: ")
        assert m.conversation_id == before.conversation_id
    places = await _places(tenant_id, cid)
    assert {p.status for p in places.values()} == {"finished"}
    await OE.run_due(tenant_id)
    detail = (await c.get(f"/api/v1/campaigns/{cid}", headers=admin)).json()
    assert detail["status"] == "finished" and detail["counts"]["sent"] == 8


async def test_inbox_limits_hold_and_the_rest_wait(ws):
    tenant_id, c, admin = ws
    for i in range(2):
        await _inbox(c, admin, f"l{i}@send.example", daily_limit=1)
    cid = await _campaign(c, admin, _people(3), steps=STEPS[:1])
    await _launch(c, admin, cid)

    await OE.run_due(tenant_id)

    assert len(await _sent(tenant_id, cid)) == 2
    waiting = [p for p in (await _places(tenant_id, cid)).values() if p.status == "active"]
    assert len(waiting) == 1 and waiting[0].next_run_at > E.now()


async def test_nothing_goes_out_outside_sending_hours(ws):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "h@send.example")
    today = E.now().weekday()
    closed = {"days": [(today + 3) % 7], "from": "09:00", "to": "10:00"}
    cid = await _campaign(c, admin, _people(2), schedule=closed)
    await _launch(c, admin, cid)

    await OE.run_due(tenant_id)

    assert await _sent(tenant_id, cid) == []
    assert all(p.next_run_at > E.now() + timedelta(hours=1)
               for p in (await _places(tenant_id, cid)).values())  # fmt: skip


async def test_tracking_is_off_by_default(ws, dirs):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "t@send.example")
    steps = [{"variants": [{"subject": "Hi", "body": "See https://example.com/page"}]}]
    cid = await _campaign(c, admin, _people(1), steps=steps)
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)

    raw = b"".join(p.read_bytes() for p in (dirs / "outbox").rglob("*") if p.is_file())
    assert b"/api/v1/t/o/" not in raw and b"/api/v1/t/c/" not in raw
    assert b"List-Unsubscribe" in raw and b"/api/v1/u/" in raw


# ---------- the promise ----------
async def test_someone_who_became_a_lead_is_never_cold_emailed(ws):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "p@send.example")
    people = _people(2)
    cid = await _campaign(c, admin, people)
    await _launch(c, admin, cid)
    _, sources = await setup_ids(c, admin)  # a web form brings one of them in meanwhile
    await new_lead(c, admin, sources["Website"],
                   identities=[{"type": "email", "value": people[0][0]}])  # fmt: skip

    await OE.run_due(tenant_id)

    sent = await _sent(tenant_id, cid)
    assert [m.to_address for m in sent] == [people[1][0]]
    place = (await _places(tenant_id, cid))[people[0][0]]
    assert (place.status, place.ended_reason) == ("stopped", "already_lead")


async def test_unsubscribe_blocks_the_address_and_stops_every_campaign(ws, client_for):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "u@send.example")
    person = _people(1)
    one = await _campaign(c, admin, person)
    two = await _campaign(c, admin, person, steps=STEPS[:1])
    await _launch(c, admin, one)
    await OE.run_due(tenant_id)
    token = (await _sent(tenant_id, one))[0].token

    assert (await c.post(f"/api/v1/u/{token}")).status_code == 200

    async with tenant_session(tenant_id) as db:
        assert await db.scalar(
            select(Suppression.id).where(Suppression.value_normalized == person[0][0])
        )
    for cid in (one, two):
        assert (await _places(tenant_id, cid))[person[0][0]].status == "unsubscribed"


async def test_a_hard_bounce_stops_the_contact(ws):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "b@send.example")
    cid = await _campaign(c, admin, _people(1))
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    async with tenant_session(tenant_id) as db:
        msg = (await db.scalars(select(Message).where(Message.direction == "out"))).one()
        await E.record_bounce(db, msg, hard=True, detail="550 no such user")

    place = next(iter((await _places(tenant_id, cid)).values()))
    assert place.status == "bounced"
    async with tenant_session(tenant_id) as db:
        assert (await db.get(Contact, place.contact_id)).status == "bounced"


# ---------- replies and the outreach inbox ----------
async def test_a_reply_stops_only_that_person_and_lands_in_the_outreach_inbox(ws):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "r@send.example")
    cid = await _campaign(c, admin, _people(2))
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    first, other = await _sent(tenant_id, cid)

    stored = await _reply_to(tenant_id, first)

    assert stored is not None and stored.contact_id == first.contact_id
    places = await _places(tenant_id, cid)
    assert places[first.to_address].status == "replied"
    assert places[other.to_address].status == "active"
    inbox = (await c.get("/api/v1/outreach/conversations", headers=admin)).json()
    assert [x["contact"]["email"] for x in inbox] == [first.to_address]
    assert inbox[0]["state"] == "new"
    normal = (await c.get("/api/v1/inbox", headers=admin)).json()
    assert all(x["id"] != inbox[0]["id"] for x in normal)  # cold threads stay out of it
    async with tenant_session(tenant_id) as db:
        assert (await db.get(Message, first.id)).replied_at is not None


async def test_an_out_of_office_reply_does_not_stop_the_campaign(ws):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "o@send.example")
    cid = await _campaign(c, admin, _people(1))
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    first = (await _sent(tenant_id, cid))[0]

    stored = await _reply_to(tenant_id, first, "I am away", Auto_Submitted="auto-replied")

    assert stored.auto_submitted is True
    assert next(iter((await _places(tenant_id, cid)).values())).status == "active"
    assert (await c.get("/api/v1/outreach/conversations", headers=admin)).json() == []
    shown = await c.get("/api/v1/outreach/conversations?include_auto=true", headers=admin)
    assert len(shown.json()) == 1


async def test_answering_goes_from_the_same_inbox_in_the_same_thread(ws):
    tenant_id, c, admin = ws
    box = await _inbox(c, admin, "a1@send.example")
    await _inbox(c, admin, "a2@send.example")
    cid = await _campaign(c, admin, _people(1))
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    first = (await _sent(tenant_id, cid))[0]
    reply = await _reply_to(tenant_id, first)
    conv_id = (await c.get("/api/v1/outreach/conversations", headers=admin)).json()[0]["id"]

    r = await c.post(f"/api/v1/outreach/conversations/{conv_id}/reply",
                     json={"body": "Great, does Tuesday work?"}, headers=admin)  # fmt: skip

    assert r.status_code == 200, r.text
    last = r.json()["messages"][-1]
    assert last["direction"] == "out" and last["mailbox_id"] == str(first.mailbox_id)
    async with tenant_session(tenant_id) as db:
        sent = await db.get(Message, uuid.UUID(last["id"]))
    assert sent.in_reply_to == reply.message_id_header and str(sent.mailbox_id) in (box, str(
        first.mailbox_id))  # fmt: skip


async def test_convert_to_lead_moves_the_thread_into_the_crm(ws):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "cv@send.example")
    people = _people(1)
    one = await _campaign(c, admin, people)
    two = await _campaign(c, admin, people, steps=STEPS[:1])
    await _launch(c, admin, one)
    await OE.run_due(tenant_id)
    first = (await _sent(tenant_id, one))[0]
    await _reply_to(tenant_id, first)

    r = await c.post(f"/api/v1/contacts/{first.contact_id}/convert", headers=admin)

    assert r.status_code == 200, r.text
    lead_id = uuid.UUID(r.json()["lead_id"])
    async with tenant_session(tenant_id) as db:
        lead = await db.get(Lead, lead_id)
        assert lead.first_name == "Pat0" and lead.org_name == "Co0"
        conv = await db.scalar(select(Conversation).where(Conversation.contact_id ==
                                                          first.contact_id))  # fmt: skip
        assert conv.lead_id == lead_id
        assert await db.scalar(select(func.count()).select_from(Message).where(
            Message.conversation_id == conv.id, Message.lead_id == lead_id)) == 2  # fmt: skip
        assert await db.scalar(select(Event.id).where(Event.type == "contact.converted"))
    threads = (await c.get(f"/api/v1/leads/{lead_id}/conversations", headers=admin)).json()
    assert [t["id"] for t in threads] == [str(conv.id)]
    assert (await _places(tenant_id, two))[people[0][0]].status == "stopped"
    inbox = (await c.get("/api/v1/outreach/conversations", headers=admin)).json()
    assert inbox == []  # it now lives on the lead
    again = await c.post(f"/api/v1/contacts/{first.contact_id}/convert", headers=admin)
    assert again.json()["lead_id"] == str(lead_id)


async def test_reps_see_only_replies_to_their_own_campaigns(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    await _inbox(c, admin, "v@send.example")
    mine = await _campaign(c, admin, _people(1, "m"), owner_user_id=str(rep_id))
    theirs = await _campaign(c, admin, _people(1, "t"))
    for cid in (mine, theirs):
        await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    for cid in (mine, theirs):
        await _reply_to(tenant_id, (await _sent(tenant_id, cid))[0])

    rep_inbox = (await c.get("/api/v1/outreach/conversations", headers=rep)).json()
    admin_inbox = (await c.get("/api/v1/outreach/conversations", headers=admin)).json()

    assert [x["campaign_id"] for x in rep_inbox] == [mine]
    assert len(admin_inbox) == 2
    hidden = next(x for x in admin_inbox if x["campaign_id"] == theirs)
    assert (await c.get(f"/api/v1/outreach/conversations/{hidden['id']}",
                        headers=rep)).status_code == 404  # fmt: skip


async def test_another_company_sees_nothing(ws, client_for):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "i@send.example")
    cid = await _campaign(c, admin, _people(1))
    other_id, other_slug = await make_workspace()
    await switch_on(other_id, "outreach")
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)

    assert (await oc.get(f"/api/v1/campaigns/{cid}", headers=other_admin)).status_code == 404
    assert (await oc.get("/api/v1/campaigns", headers=other_admin)).json() == []
    assert (await oc.get("/api/v1/contacts", headers=other_admin)).json() == []
    async with tenant_session(other_id) as db:
        assert await db.scalar(select(func.count()).select_from(Contact)) == 0
        assert await db.scalar(select(func.count()).select_from(Mailbox)) == 0


async def test_mailbox_sync_brings_a_contacts_reply_in(ws, dirs):
    from app.modules.engage import mailsync as MS

    tenant_id, c, admin = ws
    address = "sync@send.example"
    (dirs / "mailboxes" / address / "INBOX").mkdir(parents=True)
    (dirs / "mailboxes" / address / "password").write_text("app-pass-1")
    await _inbox(c, admin, address)
    cid = await _campaign(c, admin, _people(1))
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    await MS.run_due(tenant_id)  # the first look only notes where the mailbox is
    first = (await _sent(tenant_id, cid))[0]
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = first.to_address, address, f"Re: {first.subject}"
    m["Message-ID"], m["In-Reply-To"] = (
        make_msgid(domain="prospect.example"),
        first.message_id_header,
    )
    m.set_content("Yes please")
    (dirs / "mailboxes" / address / "INBOX" / "1.eml").write_bytes(m.as_bytes())
    stranger = EmailMessage()
    stranger["From"], stranger["To"], stranger["Subject"] = "x@else.example", address, "Hi"
    stranger.set_content("not ours")
    (dirs / "mailboxes" / address / "INBOX" / "2.eml").write_bytes(stranger.as_bytes())

    async with tenant_session(
        tenant_id
    ) as db:  # "Sync now" (it otherwise waits a couple of minutes)
        (
            await db.scalar(select(Mailbox).where(Mailbox.email_address == address))
        ).sync_requested = True

    assert await MS.run_due(tenant_id) == 1  # the contact's reply; the stranger is not kept
    assert next(iter((await _places(tenant_id, cid)).values())).status == "replied"


async def test_results_by_step_version_and_inbox(ws):
    tenant_id, c, admin = ws
    await _inbox(c, admin, "st@send.example")
    cid = await _campaign(c, admin, _people(4))
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    await _reply_to(tenant_id, (await _sent(tenant_id, cid))[0])

    s = (await c.get(f"/api/v1/campaigns/{cid}/stats", headers=admin)).json()

    assert s["totals"]["sent"] == 4 and s["totals"]["replied"] == 1
    assert [(r["label"], r["sent"]) for r in s["steps"]] == [("Step 1", 4)]
    assert [(r["label"], r["sent"]) for r in s["variants"]] == [
        ("Step 1 · A", 2),
        ("Step 1 · B", 2),
    ]
    assert [(r["label"], r["sent"]) for r in s["inboxes"]] == [("st@send.example", 4)]


async def test_a_file_over_20000_rows_is_refused(ws):
    tenant_id, c, admin = ws
    cid = await _campaign(c, admin, [])
    text = "Email\n" + "".join(f"r{i}@big.example\n" for i in range(20_001))
    r = await c.post(f"/api/v1/campaigns/{cid}/contacts/import", json={"csv": text}, headers=admin)
    assert r.status_code == 422 and "20,000" in r.json()["detail"]

"""Step O1 (Decision log #44): the mailbox pool — any number of sending inboxes per company,
bulk import, who may see and change them, rotation within each inbox's daily limit and gap,
the owner's inbox first, waiting (never skipping) when all are busy, bounce reports matched
to the email sent, auto-pause and resume, isolation. The mail server is MAILBOX_TEST_DIR."""

import uuid
from datetime import timedelta
from email.message import EmailMessage

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.crm import leads as L
from app.modules.crm.models import Notification, Suppression
from app.modules.engage import engine as E
from app.modules.engage import mailsync as MS
from app.modules.engage import pool as P
from app.modules.engage.models import Enrolment, Mailbox, Message
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

ALWAYS = {"from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "daily_cap": 500}


@pytest.fixture(autouse=True)
def dirs(tmp_path):
    s = get_settings()
    old = (s.files_dir, s.mailbox_test_dir, s.mail_outbox_dir)
    s.files_dir = str(tmp_path / "files")
    s.mailbox_test_dir = str(tmp_path / "mailboxes")
    s.mail_outbox_dir = str(tmp_path / "outbox")
    yield tmp_path / "mailboxes"
    s.files_dir, s.mailbox_test_dir, s.mail_outbox_dir = old


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = dict(ALWAYS)
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, client_for(slug), admin


def _inbox(address, **extra):
    return {
        "email_address": address,
        "password": "app-pass-1",
        "imap_host": "imap.mail.example",
        "smtp_host": "smtp.mail.example",
        **extra,
    }


async def _add(c, h, address, **extra):
    r = await c.post("/api/v1/sending-inboxes", json=_inbox(address, **extra), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _sequence(c, h, tenant_id, lead_ids):
    t = (
        await c.post(
            "/api/v1/templates",
            json={"name": f"T{uuid.uuid4().hex[:4]}", "subject": "Hello", "body": "Hi there"},
            headers=h,
        )
    ).json()
    s = (
        await c.post("/api/v1/sequences", json={"name": f"S{uuid.uuid4().hex[:4]}"}, headers=h)
    ).json()
    await c.put(
        f"/api/v1/sequences/{s['id']}/steps",
        json=[{"kind": "email", "template_id": t["id"]}],
        headers=h,
    )
    await c.patch(f"/api/v1/sequences/{s['id']}", json={"is_active": True}, headers=h)
    r = await c.post(f"/api/v1/sequences/{s['id']}/enrol", json={"lead_ids": lead_ids}, headers=h)
    assert r.status_code == 200, r.text
    return s


async def _leads(c, h, n, owner_user_id=None):
    _, sources = await setup_ids(c, h)
    out = []
    for i in range(n):
        extra = {"owner_user_id": str(owner_user_id)} if owner_user_id else {}
        r = await new_lead(
            c, h, sources["Website"], phone=f"98{uuid.uuid4().int % 10**8:08d}", first_name=f"P{i}",
            identities=[{"type": "email", "value": f"p{uuid.uuid4().hex[:8]}@client.example"}],
            **extra,
        )  # fmt: skip
        assert r.status_code == 201, r.text
        out.append(r.json()["id"])
    return out


async def _sent_by_inbox(tenant_id):
    async with tenant_session(tenant_id) as db:
        rows = await db.execute(
            select(Message.mailbox_id, func.count())
            .where(Message.direction == "out", Message.status == "sent")
            .group_by(Message.mailbox_id)
        )
        return dict(rows.all())


# ---------- connecting ----------
async def test_many_inboxes_connect_and_only_admins_change_them(ws, client_for, dirs):
    tenant_id, c, admin = ws
    (dirs / "x@outreach.example").mkdir(parents=True)
    (dirs / "x@outreach.example" / "password").write_text("app-pass-1")
    for i in range(12):
        await _add(c, admin, f"sdr{i}@outreach.example", from_name=f"SDR {i}")
    listed = (await c.get("/api/v1/sending-inboxes", headers=admin)).json()
    assert len(listed) == 12 and all(x["status"] == "active" for x in listed)
    assert listed[0]["daily_limit"] == 30 and listed[0]["min_gap_minutes"] == 6

    dup = await c.post(
        "/api/v1/sending-inboxes", json=_inbox("SDR0@outreach.example"), headers=admin
    )
    assert dup.status_code == 422 and dup.json()["code"] == "mailbox_exists"
    bad = await c.post(
        "/api/v1/sending-inboxes",
        json=_inbox("x@outreach.example", password="wrong"),
        headers=admin,
    )
    assert bad.status_code == 422  # signed in before saving; nothing kept
    assert len((await c.get("/api/v1/sending-inboxes", headers=admin)).json()) == 12

    _, manager = await login_as(tenant_id, "sales_manager")
    _, rep = await login_as(tenant_id, "sales_user")
    assert len((await c.get("/api/v1/sending-inboxes", headers=manager)).json()) == 12
    assert (await c.get("/api/v1/sending-inboxes", headers=rep)).status_code == 403
    one = listed[0]["id"]
    assert (
        await c.patch(f"/api/v1/sending-inboxes/{one}", json={"daily_limit": 50}, headers=manager)
    ).status_code == 403

    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)
    assert (await oc.get("/api/v1/sending-inboxes", headers=other_admin)).json() == []
    assert (
        await oc.patch(
            f"/api/v1/sending-inboxes/{one}", json={"daily_limit": 5}, headers=other_admin
        )
    ).status_code == 404


async def test_csv_import_reports_each_row(ws, dirs):
    _, c, admin = ws
    (dirs / "a3@outreach.example").mkdir(parents=True)
    (dirs / "a3@outreach.example" / "password").write_text("app-pass-1")
    await _add(c, admin, "taken@outreach.example")
    csv = (
        "email,password,provider,imap_host,smtp_host,from_name,daily_limit,owner_email\n"
        "a1@outreach.example,app-pass-1,,imap.mail.example,smtp.mail.example,Asha,40,\n"
        "a2@outreach.example,app-pass-1,gmail,,,Ravi,,\n"
        "taken@outreach.example,app-pass-1,,imap.mail.example,smtp.mail.example,,,\n"
        "a3@outreach.example,wrong,,imap.mail.example,smtp.mail.example,,,\n"
        "a4@outreach.example,app-pass-1,,imap.mail.example,smtp.mail.example,,,nobody@x.example\n"
        "not-an-email,app-pass-1,,imap.mail.example,smtp.mail.example,,,\n"
    )
    r = await c.post("/api/v1/sending-inboxes/import", json={"csv": csv}, headers=admin)
    assert r.status_code == 200, r.text
    rows = {x["email_address"]: x for x in r.json()}
    assert rows["a1@outreach.example"]["ok"] and rows["a2@outreach.example"]["ok"]
    assert not rows["taken@outreach.example"]["ok"]
    assert not rows["a3@outreach.example"]["ok"]
    assert "nobody@x.example" in rows["a4@outreach.example"]["error"]
    assert not rows["not-an-email"]["ok"]
    listed = {
        x["email_address"]: x
        for x in (await c.get("/api/v1/sending-inboxes", headers=admin)).json()
    }
    assert set(listed) == {"taken@outreach.example", "a1@outreach.example", "a2@outreach.example"}
    assert listed["a1@outreach.example"]["daily_limit"] == 40
    bad = await c.post("/api/v1/sending-inboxes/import", json={"csv": "name\nx"}, headers=admin)
    assert bad.status_code == 422


# ---------- sending ----------
async def test_sends_rotate_within_limits_and_wait_when_all_are_busy(ws):
    tenant_id, c, admin = ws
    boxes = [
        await _add(c, admin, f"r{i}@outreach.example", daily_limit=2, min_gap_minutes=0)
        for i in range(3)
    ]
    leads = await _leads(c, admin, 8)
    await _sequence(c, admin, tenant_id, leads)
    for _ in range(3):
        await E.run_due(tenant_id)
    sent = await _sent_by_inbox(tenant_id)
    assert sent == {uuid.UUID(b["id"]): 2 for b in boxes}  # 6 sent, spread evenly, none over
    async with tenant_session(tenant_id) as db:
        waiting = (await db.scalars(select(Enrolment).where(Enrolment.status == "active"))).all()
        assert len(waiting) == 2 and all(e.next_run_at > L.now() for e in waiting)  # not skipped
        froms = set(
            (await db.scalars(select(Message.from_address).where(Message.direction == "out"))).all()
        )
    assert froms == {b["email_address"] for b in boxes}
    health = {
        x["email_address"]: x
        for x in (await c.get("/api/v1/sending-inboxes", headers=admin)).json()
    }
    assert all(x["sent_today"] == 2 for x in health.values())


async def test_the_owners_inbox_goes_first_and_the_gap_is_kept(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    mine = await _add(
        c, admin, "rep@outreach.example", user_id=str(rep_id), min_gap_minutes=60,
        from_name="Riya", signature="Riya · Brightlane",
    )  # fmt: skip
    other = await _add(c, admin, "shared@outreach.example", min_gap_minutes=60)
    leads = await _leads(c, admin, 3, owner_user_id=rep_id)
    await _sequence(c, admin, tenant_id, leads)
    await E.run_due(tenant_id)
    sent = await _sent_by_inbox(tenant_id)
    # one each: the owner's inbox first, then its 60-minute gap sends the next to the other inbox
    assert sent == {uuid.UUID(mine["id"]): 1, uuid.UUID(other["id"]): 1}
    async with tenant_session(tenant_id) as db:
        first = await db.scalar(select(Message).where(Message.mailbox_id == uuid.UUID(mine["id"])))
        assert first.from_address == "rep@outreach.example" and "Riya · Brightlane" in first.body


async def test_paused_and_broken_inboxes_never_send(ws):
    tenant_id, c, admin = ws
    a = await _add(c, admin, "a@outreach.example", min_gap_minutes=0)
    b = await _add(c, admin, "b@outreach.example", min_gap_minutes=0)
    r = await c.post(f"/api/v1/sending-inboxes/{a['id']}/pause", headers=admin)
    assert r.json()["status"] == "paused"
    async with tenant_session(tenant_id) as db:
        (await db.get(Mailbox, uuid.UUID(b["id"]))).status = "error"
    leads = await _leads(c, admin, 2)
    await _sequence(c, admin, tenant_id, leads)
    await E.run_due(tenant_id)
    assert await _sent_by_inbox(tenant_id) == {}
    assert (await c.post(f"/api/v1/sending-inboxes/{a['id']}/resume", headers=admin)).json()[
        "status"
    ] == "active"
    await E.run_due(tenant_id)  # waits are short; force the next pass
    async with tenant_session(tenant_id) as db:
        for e in (await db.scalars(select(Enrolment))).all():
            e.next_run_at = L.now() - timedelta(seconds=1)
    await E.run_due(tenant_id)
    assert await _sent_by_inbox(tenant_id) == {uuid.UUID(a["id"]): 2}


# ---------- bounces ----------
def _bounce(original_id: str, *, hard=True) -> bytes:
    m = EmailMessage()
    m["From"] = "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"
    m["To"] = "a@outreach.example"
    m["Subject"] = "Delivery Status Notification (Failure)"
    m["Message-ID"] = f"<{uuid.uuid4().hex}@mx.google.com>"
    status = "5.1.1" if hard else "4.2.2"
    m.set_content(f"Address not found. Status: {status}")
    m.add_attachment(
        f"From: a@outreach.example\nMessage-ID: {original_id}\nSubject: Hello\n".encode(),
        maintype="text",
        subtype="rfc822-headers",
    )
    return m.as_bytes()


async def test_a_bounce_report_is_matched_and_suppresses_the_address(ws, dirs):
    tenant_id, c, admin = ws
    a = await _add(c, admin, "a@outreach.example", min_gap_minutes=0)
    leads = await _leads(c, admin, 1)
    await _sequence(c, admin, tenant_id, leads)
    await E.run_due(tenant_id)
    async with tenant_session(tenant_id) as db:
        sent = await db.scalar(select(Message).where(Message.direction == "out"))
        sent_id, to = sent.message_id_header, sent.to_address
        mb = await db.get(Mailbox, uuid.UUID(a["id"]))
        mb.connected_at = L.now() - timedelta(days=1)
        mb.sync_state = {"INBOX": {"v": 1, "last": 0}}  # past the quiet first pass
    folder = dirs / "a@outreach.example" / "INBOX"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "1.eml").write_bytes(_bounce(sent_id))
    async with tenant_session(tenant_id) as db:
        await MS.sync(db, await db.get(Mailbox, uuid.UUID(a["id"])))
    async with tenant_session(tenant_id) as db:
        sent = await db.scalar(select(Message).where(Message.message_id_header == sent_id))
        assert sent.bounced_at is not None and sent.status == "bounced"
        assert await db.scalar(
            select(Suppression.id).where(Suppression.value_normalized == to.lower())
        )
    health = (await c.get("/api/v1/sending-inboxes", headers=admin)).json()[0]
    assert health["bounces_7d"] == 1


async def test_an_inbox_that_bounces_too_often_is_paused_and_admins_told(ws):
    tenant_id, c, admin = ws
    a = await _add(c, admin, "a@outreach.example")
    async with tenant_session(tenant_id) as db:
        mb = await db.get(Mailbox, uuid.UUID(a["id"]))
        for i in range(30):  # 30 recent sends, 2 bounced (6.7% > 5%)
            db.add(
                Message(
                    id=uuid.uuid4(), tenant_id=tenant_id, channel="email", direction="out",
                    to_address=f"x{i}@client.example", subject="Hi", body="Hi",
                    token=uuid.uuid4().hex, status="sent", sent_at=L.now() - timedelta(minutes=i),
                    mailbox_id=mb.id, bounced_at=L.now() if i < 2 else None,
                )
            )  # fmt: skip
        await db.flush()
        assert await P.check_health(db, mb) is True
        assert mb.status == "paused" and "2 of its last 30" in mb.paused_reason
        assert await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.title.like("%paused%"))
        )
    r = await c.post(f"/api/v1/sending-inboxes/{a['id']}/resume", headers=admin)
    assert r.json()["status"] == "active" and r.json()["paused_reason"] is None


async def test_removing_a_company_inbox_disconnects_it_but_keeps_its_emails(ws):
    tenant_id, c, admin = ws
    a = await _add(c, admin, "a@outreach.example", min_gap_minutes=0)
    leads = await _leads(c, admin, 1)
    await _sequence(c, admin, tenant_id, leads)
    await E.run_due(tenant_id)
    assert (await c.delete(f"/api/v1/sending-inboxes/{a['id']}", headers=admin)).status_code == 204
    assert (await c.get("/api/v1/sending-inboxes", headers=admin)).json() == []
    async with tenant_session(tenant_id) as db:
        mb = await db.get(Mailbox, uuid.UUID(a["id"]))
        assert mb.status == "off" and mb.password_enc is None and not mb.in_pool
        assert (
            await db.scalar(
                select(func.count()).select_from(Message).where(Message.mailbox_id == mb.id)
            )
            == 1
        )

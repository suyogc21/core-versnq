"""Step 9b-3 (Decision log #40): connect my inbox — sync only emails with known leads, both ways,
quiet 30-day backfill, exclusions, duplicates, wrong password, send through the user's mailbox,
disconnect and removal, isolation. The mail server is MAILBOX_TEST_DIR (folders of .eml files)."""

import uuid
from datetime import timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.crm import leads as L
from app.modules.crm.models import Notification
from app.modules.engage import mailsync as MS
from app.modules.engage.models import Mailbox, Message
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

ALWAYS = {"from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "daily_cap": 200}


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


def _box(address):
    return {
        "email_address": address,
        "password": "app-pass-1",
        "imap_host": "imap.mail.example",
        "imap_port": 993,
        "smtp_host": "smtp.mail.example",
        "smtp_port": 587,
        "smtp_security": "starttls",
    }


def _put(root: Path, address: str, folder: str, uid: int, raw: bytes) -> None:
    d = root / address / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{uid}.eml").write_bytes(raw)


def _mail(frm, to, subject, *, when=None, msg_id=None, reply_to=None, cc=()):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Date"] = format_datetime(when or L.now())
    m["Message-ID"] = msg_id or f"<{uuid.uuid4().hex}@mail.example>"
    if reply_to:
        m["In-Reply-To"] = m["References"] = reply_to
    m.set_content(f"About {subject}")
    return m.as_bytes()


async def _lead(c, h, email):
    _, sources = await setup_ids(c, h)
    r = await new_lead(
        c, h, sources["Website"], first_name="Asha",
        identities=[{"type": "email", "value": email}],
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def _connect(c, h, address):
    r = await c.put("/api/v1/me/mailbox", json=_box(address), headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def _messages(tenant_id, **where):
    async with tenant_session(tenant_id) as db:
        q = select(Message)
        for k, v in where.items():
            q = q.where(getattr(Message, k) == v)
        return (await db.scalars(q.order_by(Message.sent_at))).all()


# ---------- connecting ----------
async def test_connect_checks_the_password_and_never_shows_it(ws, dirs):
    tenant_id, c, _ = ws
    _, rep = await login_as(tenant_id, "sales_user")
    (dirs / "rep@gmail.example").mkdir(parents=True)
    (dirs / "rep@gmail.example" / "password").write_text("the-right-one")
    bad = await c.put("/api/v1/me/mailbox", json=_box("rep@gmail.example"), headers=rep)
    assert bad.status_code == 422 and "refused" in bad.text
    assert (await c.get("/api/v1/me/mailbox", headers=rep)).json() is None

    (dirs / "rep@gmail.example" / "password").write_text("app-pass-1")
    out = await _connect(c, rep, "rep@gmail.example")
    assert out["status"] == "active" and "password" not in out
    async with tenant_session(tenant_id) as db:
        mb = await db.scalar(select(Mailbox))
        assert mb.password_enc and "app-pass-1" not in mb.password_enc  # encrypted
    no_port = await c.put(
        "/api/v1/me/mailbox", json=_box("rep@gmail.example") | {"imap_port": 2222}, headers=rep
    )
    assert no_port.status_code == 422 and "ports" in no_port.text


# ---------- syncing ----------
async def test_sync_keeps_only_emails_with_known_leads_both_ways(ws, dirs):
    tenant_id, c, _ = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, "asha@client.example")
    await _connect(c, rep, "rep@gmail.example")
    box = "rep@gmail.example"
    _put(dirs, box, "INBOX", 1, _mail("Asha <asha@client.example>", box, "Pricing?"))
    _put(dirs, box, "INBOX", 2, _mail("mum@family.example", box, "Dinner"))  # not a lead
    _put(
        dirs, box, "Sent", 1, _mail(box, "Asha@Client.example", "Re: Pricing?", cc=["x@y.example"])
    )
    _put(dirs, box, "Sent", 2, _mail(box, "friend@else.example", "Weekend"))

    assert await MS.run_due(tenant_id) == 2
    rows = await _messages(tenant_id)
    assert {(m.direction, m.subject) for m in rows} == {("in", "Pricing?"), ("out", "Re: Pricing?")}
    assert all(str(m.lead_id) == lead["id"] for m in rows)
    out = next(m for m in rows if m.direction == "out")
    assert out.sent_by_user_id == rep_id and out.cc == ["x@y.example"]
    assert len({m.conversation_id for m in rows}) == 1  # one conversation, base subject

    timeline = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)).json()
    items = timeline["items"] if isinstance(timeline, dict) else timeline
    kinds = {i["type_key"] for i in items}
    assert {"email_received", "email_sent"} <= kinds

    # running again, or the same email turning up twice, never duplicates
    dup = (dirs / box / "INBOX" / "1.eml").read_bytes()
    _put(dirs, box, "INBOX", 3, dup)
    async with tenant_session(tenant_id) as db:
        (await db.scalar(select(Mailbox))).sync_requested = True
    await MS.run_due(tenant_id)
    assert len(await _messages(tenant_id)) == 2


async def test_backfill_is_quiet_new_mail_notifies(ws, dirs):
    tenant_id, c, _ = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    await _lead(c, rep, "asha@client.example")
    box = "rep@gmail.example"
    old = L.now() - timedelta(days=10)
    _put(dirs, box, "INBOX", 1, _mail("asha@client.example", box, "Old one", when=old))
    await _connect(c, rep, box)
    await MS.run_due(tenant_id)
    async with tenant_session(tenant_id) as db:
        n = await db.scalar(
            select(func.count()).select_from(Notification).where(Notification.user_id == rep_id)
        )
        assert n == 0
        msg = await db.scalar(select(Message))
        assert msg.sent_at.date() == old.date()  # kept with its own date

    _put(dirs, box, "INBOX", 2, _mail("asha@client.example", box, "New one"))
    async with tenant_session(tenant_id) as db:
        (await db.scalar(select(Mailbox))).sync_requested = True
    await MS.run_due(tenant_id)
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(Notification.id).where(Notification.user_id == rep_id))


async def test_exclusions_are_admin_only_and_honoured(ws, dirs):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    await _lead(c, rep, "partner@lawfirm.example")
    r = await c.put(
        "/api/v1/mailboxes/exclusions", json={"items": ["@lawfirm.example"]}, headers=rep
    )
    assert r.status_code == 403
    bad = await c.put(
        "/api/v1/mailboxes/exclusions", json={"items": ["not a domain"]}, headers=admin
    )
    assert bad.status_code == 422
    r = await c.put(
        "/api/v1/mailboxes/exclusions", json={"items": ["@LawFirm.example", " "]}, headers=admin
    )
    assert r.json()["items"] == ["@lawfirm.example"]
    box = "rep@gmail.example"
    await _connect(c, rep, box)
    _put(dirs, box, "INBOX", 1, _mail("partner@lawfirm.example", box, "Confidential"))
    _put(dirs, box, "Sent", 1, _mail(box, "partner@lawfirm.example", "Re: Confidential"))
    await MS.run_due(tenant_id)
    assert await _messages(tenant_id) == []


async def test_a_private_thread_stays_private_when_the_reply_syncs(ws, dirs):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, manager = await login_as(tenant_id, "sales_manager")
    lead = await _lead(c, rep, "asha@client.example")
    box = "rep@gmail.example"
    await _connect(c, rep, box)
    sent = await c.post(
        f"/api/v1/leads/{lead['id']}/emails",
        json={"subject": "Your offer", "body": "Here it is"},
        headers=rep,
    )
    conv_id = sent.json()["id"]
    assert (
        await c.patch(f"/api/v1/conversations/{conv_id}", json={"is_private": True}, headers=rep)
    ).status_code == 200
    header = (await _messages(tenant_id))[0].message_id_header
    _put(
        dirs,
        box,
        "INBOX",
        1,
        _mail(
            "asha@client.example",
            box,
            "Re: Your offer",
            reply_to=header,
            when=L.now() + timedelta(minutes=1),
        ),
    )
    await MS.run_due(tenant_id)
    detail = (await c.get(f"/api/v1/conversations/{conv_id}", headers=rep)).json()
    assert [m["direction"] for m in detail["messages"]] == ["out", "in"]
    assert (await c.get(f"/api/v1/conversations/{conv_id}", headers=manager)).status_code == 404


# ---------- sending ----------
async def test_email_from_core_goes_through_the_users_mailbox_and_into_sent(ws, dirs):
    tenant_id, c, _ = ws
    _, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, "asha@client.example")
    box = "rep@gmail.example"
    await _connect(c, rep, box)
    r = await c.post(
        f"/api/v1/leads/{lead['id']}/emails",
        json={"subject": "Hello", "body": "Hi Asha"},
        headers=rep,
    )
    assert r.status_code == 201, r.text
    [msg] = await _messages(tenant_id)
    assert msg.from_address == box and msg.mailbox_id is not None and msg.status == "sent"
    outbox = list((Path(get_settings().mail_outbox_dir)).glob("*.eml"))
    assert len(outbox) == 1 and b"rep@gmail.example" in outbox[0].read_bytes()
    assert [p.name for p in (dirs / box / "Sent").glob("*.eml")] == ["1.eml"]  # copy in Sent
    await MS.run_due(tenant_id)
    assert len(await _messages(tenant_id)) == 1  # the copy in Sent is not stored twice


async def test_a_wrong_password_shows_on_the_mailbox_and_stops_sending(ws, dirs):
    tenant_id, c, _ = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, "asha@client.example")
    box = "rep@gmail.example"
    await _connect(c, rep, box)
    (dirs / box / "password").write_text("changed-by-google")  # app password revoked
    await MS.run_due(tenant_id)
    out = (await c.get("/api/v1/me/mailbox", headers=rep)).json()
    assert out["status"] == "error" and "refused" in out["last_error"]
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(Notification.id).where(Notification.user_id == rep_id))
    r = await c.post(
        f"/api/v1/leads/{lead['id']}/emails", json={"subject": "Hello", "body": "Hi"}, headers=rep
    )
    assert r.status_code == 422 and "reconnecting" in r.text
    await MS.run_due(tenant_id)  # not retried until the user fixes it
    (dirs / box / "password").write_text("new-pass")
    fixed = await c.put(
        "/api/v1/me/mailbox", json=_box(box) | {"password": "new-pass"}, headers=rep
    )
    assert fixed.json()["status"] == "active"


async def test_disconnect_keeps_emails_and_admin_can_remove_synced_ones(ws, dirs):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, "asha@client.example")
    box = "rep@gmail.example"
    await _connect(c, rep, box)
    _put(dirs, box, "INBOX", 1, _mail("asha@client.example", box, "From her"))
    _put(dirs, box, "Sent", 1, _mail(box, "asha@client.example", "From his phone"))
    await MS.run_due(tenant_id)
    await c.post(
        f"/api/v1/leads/{lead['id']}/emails",
        json={"subject": "From Core", "body": "Hi"},
        headers=rep,
    )
    assert len(await _messages(tenant_id)) == 3

    listed = (await c.get("/api/v1/mailboxes", headers=admin)).json()
    assert [m["email_address"] for m in listed] == [box] and listed[0]["synced"] == 3
    assert (await c.get("/api/v1/mailboxes", headers=rep)).status_code == 403
    mb_id = listed[0]["id"]
    early = await c.delete(f"/api/v1/mailboxes/{mb_id}/emails", headers=admin)
    assert early.status_code == 422  # disconnect first

    assert (await c.delete("/api/v1/me/mailbox", headers=rep)).status_code == 204
    assert (await c.get("/api/v1/me/mailbox", headers=rep)).json() is None
    async with tenant_session(tenant_id) as db:
        mb = await db.get(Mailbox, uuid.UUID(mb_id))
        assert mb.status == "off" and mb.password_enc is None
    _put(dirs, box, "INBOX", 2, _mail("asha@client.example", box, "After"))
    await MS.run_due(tenant_id)
    assert len(await _messages(tenant_id)) == 3  # no sync after disconnect; emails stay

    r = await c.delete(f"/api/v1/mailboxes/{mb_id}/emails", headers=admin)
    assert r.json()["removed"] == 2
    assert [m.subject for m in await _messages(tenant_id)] == ["From Core"]


async def test_isolation_between_companies(ws, dirs, client_for):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    await _lead(c, rep, "asha@client.example")
    other_id, other_slug = await make_workspace()
    oc = client_for(other_slug)
    _, other_admin = await login_as(other_id, "admin")
    box = "theirs@gmail.example"
    await _connect(oc, other_admin, box)  # the other company has no lead with Asha's address
    _put(dirs, box, "INBOX", 1, _mail("asha@client.example", box, "Wrong company"))
    await MS.run_due(other_id)
    assert await _messages(tenant_id) == [] and await _messages(other_id) == []
    assert (await c.get("/api/v1/mailboxes", headers=admin)).json() == []

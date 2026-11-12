"""Step 9a (Decision log #39): sequences, templates, sending rules, tracking, unsubscribe."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead, Suppression, Task
from app.modules.engage import engine as E
from app.modules.engage.models import Enrolment, Message
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

ALWAYS = {"from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "daily_cap": 200}


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    _, admin = await login_as(tenant_id, "admin")
    async with tenant_session(tenant_id) as db:  # tests may run at any hour
        (await db.get(TenantSettings, tenant_id)).engage = dict(ALWAYS)
    return tenant_id, c, admin


async def _lead(c, h, email="asha@example.com", **extra):
    _, sources = await setup_ids(c, h)
    r = await new_lead(
        c, h, sources["Website"],
        identities=[
            {"type": "email", "value": email},
            {"type": "phone", "value": f"98{uuid.uuid4().int % 10**8:08d}"},
        ],
        first_name="Asha", **extra,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def _template(c, h, name="Welcome", subject="Hi {{lead.first_name|there}}", body=None):
    r = await c.post(
        "/api/v1/templates",
        json={"name": name, "subject": subject,
              "body": body or "Hello {{lead.first_name|there}},\n\nSee https://example.com/brochure\n\n{{owner.name|Team}}"},
        headers=h,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def _sequence(c, h, steps, name="Welcome", **extra):
    s = (await c.post("/api/v1/sequences", json={"name": name, **extra}, headers=h)).json()
    r = await c.put(f"/api/v1/sequences/{s['id']}/steps", json=steps, headers=h)
    assert r.status_code == 200, r.text
    on = await c.patch(f"/api/v1/sequences/{s['id']}", json={"is_active": True}, headers=h)
    assert on.status_code == 200, on.text
    return on.json()


async def _enrol(c, h, seq, *leads):
    r = await c.post(
        f"/api/v1/sequences/{seq['id']}/enrol",
        json={"lead_ids": [x["id"] for x in leads]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _run(tenant_id, *, now=True):
    if now:
        async with tenant_session(tenant_id) as db:
            await db.execute(
                update(Enrolment)
                .where(Enrolment.status == "active")
                .values(next_run_at=datetime.now(UTC))
            )
    return await E.run_due(tenant_id)


async def _messages(tenant_id) -> list[Message]:
    async with tenant_session(tenant_id) as db:
        return list((await db.scalars(select(Message).order_by(Message.created_at))).all())


async def _enrolment(tenant_id, lead_id) -> Enrolment:
    async with tenant_session(tenant_id) as db:
        return await db.scalar(select(Enrolment).where(Enrolment.lead_id == uuid.UUID(lead_id)))


# ---------- templates ----------
async def test_template_variables_are_checked_and_filled(ws):
    tenant_id, c, admin = ws
    bad = await c.post(
        "/api/v1/templates",
        json={"name": "x", "subject": "Hi {{lead.nope}}", "body": "x"},
        headers=admin,
    )
    assert bad.status_code == 422 and "lead.nope" in bad.json()["detail"]
    t = await _template(c, admin)
    lead = await _lead(c, admin)
    p = (
        await c.post(
            f"/api/v1/templates/{t['id']}/preview", json={"lead_id": lead["id"]}, headers=admin
        )
    ).json()
    assert p["subject"] == "Hi Asha" and p["body"].startswith("Hello Asha,")
    _, rep = await login_as(tenant_id, "sales_user")
    assert (await c.get("/api/v1/templates", headers=rep)).status_code == 403


# ---------- running a sequence ----------
async def test_a_sequence_sends_waits_makes_a_task_and_finishes(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    t2 = await _template(c, admin, name="Reminder", subject="Still interested?")
    seq = await _sequence(c, admin, [
        {"kind": "email", "template_id": t["id"]},
        {"kind": "wait", "hours": 48},
        {"kind": "task", "title": "Call Asha", "task_type": "call"},
        {"kind": "email", "template_id": t2["id"]},
    ])  # fmt: skip
    lead = await _lead(c, admin)
    assert (await _enrol(c, admin, seq, lead))["enrolled"] == 1
    await _run(tenant_id)
    msgs = await _messages(tenant_id)
    assert len(msgs) == 1 and msgs[0].status == "sent" and msgs[0].subject == "Hi Asha"
    assert msgs[0].links == ["https://example.com/brochure"]
    e = await _enrolment(tenant_id, lead["id"])
    assert e.position == 3 and e.next_run_at > datetime.now(UTC) + timedelta(hours=47)
    await _run(tenant_id, now=False)  # nothing due yet
    assert len(await _messages(tenant_id)) == 1
    await _run(tenant_id)
    assert [m.subject for m in await _messages(tenant_id)] == ["Hi Asha", "Still interested?"]
    async with tenant_session(tenant_id) as db:
        task = await db.scalar(select(Task).where(Task.created_from == "sequence"))
        assert task.title == "Call Asha"
    e = await _enrolment(tenant_id, lead["id"])
    assert e.status == "completed"
    timeline = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=admin)).json()
    kinds = [a["type_key"] for a in (timeline["items"] if isinstance(timeline, dict) else timeline)]
    assert (
        kinds.count("email_sent") == 2
        and "sequence_enrolled" in kinds
        and "sequence_ended" in kinds
    )
    stats = (await c.get(f"/api/v1/sequences/{seq['id']}/stats", headers=admin)).json()
    assert (
        stats["completed"] == 1
        and stats["steps"][0]["sent"] == 1
        and stats["steps"][3]["sent"] == 1
    )


async def test_check_opened_takes_the_other_path(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    t2 = await _template(c, admin, name="Opened", subject="Glad you looked")
    t3 = await _template(c, admin, name="Not opened", subject="Did you see this?")
    seq = await _sequence(c, admin, [
        {"kind": "email", "template_id": t["id"]},
        {"kind": "wait", "hours": 24},
        {"kind": "check", "check_if": "opened", "go_to": 5},
        {"kind": "email", "template_id": t3["id"]},
        {"kind": "email", "template_id": t2["id"]},
    ])  # fmt: skip
    lead = await _lead(c, admin)
    await _enrol(c, admin, seq, lead)
    await _run(tenant_id)
    sent = (await _messages(tenant_id))[0]
    await c.get(f"/api/v1/t/o/{sent.token}.gif")
    await _run(tenant_id)
    assert [m.subject for m in await _messages(tenant_id)] == ["Hi Asha", "Glad you looked"]


# ---------- sending rules ----------
async def test_quiet_hours_and_daily_cap(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    seq = await _sequence(c, admin, [{"kind": "email", "template_id": t["id"]}])
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = ALWAYS | {"days": []}
    lead = await _lead(c, admin)
    await _enrol(c, admin, seq, lead)
    await _run(tenant_id)
    assert await _messages(tenant_id) == []  # no sending day at all: waits
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = ALWAYS | {"daily_cap": 1}
    other = await _lead(c, admin, "b@example.com")
    await _enrol(c, admin, seq, other)
    await _run(tenant_id)
    assert len(await _messages(tenant_id)) == 1  # the cap held the second one
    held = [
        e
        for e in [await _enrolment(tenant_id, lead["id"]), await _enrolment(tenant_id, other["id"])]
        if e.status == "active"
    ]
    assert len(held) == 1 and held[0].next_run_at > datetime.now(UTC)


async def test_hours_window():
    engage = {"from": "09:00", "to": "20:00", "days": [0, 1, 2, 3, 4, 5]}
    sunday_noon = datetime(2026, 11, 15, 6, 30, tzinfo=UTC)  # 12:00 in India, a Sunday
    monday_9 = datetime(2026, 11, 16, 3, 30, tzinfo=UTC)
    assert E.next_open(sunday_noon, engage, "Asia/Kolkata") == monday_9
    monday_noon = datetime(2026, 11, 16, 6, 30, tzinfo=UTC)
    assert E.next_open(monday_noon, engage, "Asia/Kolkata") == monday_noon


async def test_settings_are_checked(ws):
    tenant_id, c, admin = ws
    r = await c.put(
        "/api/v1/engage/settings",
        json={"from": "20:00", "to": "09:00", "days": [0], "daily_cap": 5},
        headers=admin,
    )
    assert r.status_code == 422
    r = await c.put(
        "/api/v1/engage/settings",
        json={"from": "08:30", "to": "19:00", "days": [0, 1], "daily_cap": 50},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["from"] == "08:30"


# ---------- stopping ----------
async def test_stop_rules(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    seq = await _sequence(c, admin, [
        {"kind": "email", "template_id": t["id"]},
        {"kind": "wait", "hours": 24},
        {"kind": "email", "template_id": t["id"]},
    ])  # fmt: skip
    won = await _lead(c, admin, "won@example.com")
    replied = await _lead(c, admin, "r@example.com")
    closed = await _lead(c, admin, "c@example.com")
    await _enrol(c, admin, seq, won, replied, closed)
    await _run(tenant_id)
    deal = (
        await c.post(
            "/api/v1/deals", json={"lead_id": won["id"], "amount_minor": 100}, headers=admin
        )
    ).json()
    pipes = (await c.get("/api/v1/pipelines", headers=admin)).json()
    stages = next(p for p in pipes if p["id"] == deal["pipeline_id"])["stages"]
    won_stage = next(s for s in stages if s["kind"] == "won")
    r = await c.post(
        f"/api/v1/deals/{deal['id']}/move",
        json={"version": deal["version"], "stage_id": won_stage["id"]},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    async with tenant_session(tenant_id) as db:
        db.add(
            Message(
                tenant_id=tenant_id,
                lead_id=uuid.UUID(replied["id"]),
                channel="email",
                direction="in",
                to_address="us@example.com",
                body="yes please",
                token=uuid.uuid4().hex,
                status="received",
            )
        )
        lead = await db.get(Lead, uuid.UUID(closed["id"]))
        lead.is_open = False
    await _run(tenant_id)
    reasons = {
        x["id"]: (await _enrolment(tenant_id, x["id"])).ended_reason for x in (won, replied, closed)
    }
    assert reasons == {won["id"]: "deal_won", replied["id"]: "reply", closed["id"]: "closed"}
    assert len(await _messages(tenant_id)) == 4  # 3 first emails + the reply; no second emails


async def test_unsubscribe_needs_the_button_then_stops_everything(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    seq = await _sequence(c, admin, [
        {"kind": "email", "template_id": t["id"]}, {"kind": "wait", "hours": 1},
        {"kind": "email", "template_id": t["id"]},
    ])  # fmt: skip
    lead = await _lead(c, admin)
    await _enrol(c, admin, seq, lead)
    await _run(tenant_id)
    token = (await _messages(tenant_id))[0].token
    page = await c.get(f"/api/v1/u/{token}")
    assert page.status_code == 200 and "Unsubscribe" in page.text
    assert (
        await _enrolment(tenant_id, lead["id"])
    ).status == "active"  # opening the link alone does nothing
    done = await c.post(f"/api/v1/u/{token}")
    assert "unsubscribed" in done.text
    e = await _enrolment(tenant_id, lead["id"])
    assert e.status == "stopped" and e.ended_reason == "unsubscribed"
    got = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()
    assert got["email_consent"] == "opted_out"
    async with tenant_session(tenant_id) as db:
        assert (
            await db.scalar(
                select(Suppression.reason).where(Suppression.value_normalized == "asha@example.com")
            )
            == "opt_out"
        )
    other = await _sequence(c, admin, [{"kind": "email", "template_id": t["id"]}], name="Other")
    again = await _enrol(c, admin, other, lead)
    assert again["enrolled"] == 0 and again["skipped"][0]["reason"] == "they opted out of email"


async def test_bounces_and_suppression(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    steps = [
        {"kind": "email", "template_id": t["id"]},
        {"kind": "wait", "hours": 1},
        {"kind": "email", "template_id": t["id"]},
    ]
    seq = await _sequence(c, admin, steps)
    hard = await _lead(c, admin, "hard@example.com")
    soft = await _lead(c, admin, "soft@example.com")
    listed = await _lead(c, admin, "listed@example.com")
    await _enrol(c, admin, seq, hard, soft, listed)
    await _run(tenant_id)
    async with tenant_session(tenant_id) as db:
        msgs = {m.to_address: m for m in (await db.scalars(select(Message))).all()}
        await E.record_bounce(db, msgs["hard@example.com"], hard=True)
        await E.record_bounce(db, msgs["soft@example.com"], hard=False)
        db.add(
            Suppression(
                tenant_id=tenant_id,
                channel="email",
                value_normalized="listed@example.com",
                reason="complaint",
            )
        )
    await _run(tenant_id)
    ended = {x["id"]: (await _enrolment(tenant_id, x["id"])) for x in (hard, soft, listed)}
    assert ended[hard["id"]].ended_reason == "bounced"
    assert ended[listed["id"]].ended_reason == "suppressed"
    assert ended[soft["id"]].status == "completed"  # a soft bounce does not stop it
    assert len(await _messages(tenant_id)) == 4  # 3 first + soft's second


async def test_click_tracking_only_redirects_to_links_in_the_email(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    seq = await _sequence(c, admin, [{"kind": "email", "template_id": t["id"]}])
    await _enrol(c, admin, seq, await _lead(c, admin))
    await _run(tenant_id)
    m = (await _messages(tenant_id))[0]
    r = await c.get(f"/api/v1/t/c/{m.token}/0", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://example.com/brochure"
    assert (await c.get(f"/api/v1/t/c/{m.token}/5", follow_redirects=False)).status_code == 404
    assert (await c.get("/api/v1/t/c/nope/0", follow_redirects=False)).status_code == 404
    m = (await _messages(tenant_id))[0]
    assert m.clicked_at and m.opened_at


# ---------- who may do what ----------
async def test_enrolment_rules_and_permissions(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    a = await _sequence(
        c,
        admin,
        [{"kind": "email", "template_id": t["id"]}, {"kind": "wait", "hours": 9}],
        name="A",
    )
    b = await _sequence(c, admin, [{"kind": "wait", "hours": 9}], name="B")
    lead = await _lead(c, admin)
    await _enrol(c, admin, a, lead)
    second = await _enrol(c, admin, b, lead)
    assert second["skipped"][0]["reason"] == "already in another sequence"
    rep_id, rep = await login_as(tenant_id, "sales_user")
    assert (
        await c.post("/api/v1/sequences", json={"name": "Mine"}, headers=rep)
    ).status_code == 403
    theirs = await _enrol(c, rep, b, lead)  # not the rep's lead
    assert theirs["skipped"][0]["reason"] == "not found"
    own = await _lead(c, rep, "own@example.com")
    assert (await _enrol(c, rep, b, own))["enrolled"] == 1
    off = await c.patch(f"/api/v1/sequences/{b['id']}", json={"is_active": False}, headers=admin)
    assert off.json()["active"] == 0 and off.json()["stopped"] == 1
    empty = (await c.post("/api/v1/sequences", json={"name": "Empty"}, headers=admin)).json()
    assert (
        await c.patch(f"/api/v1/sequences/{empty['id']}", json={"is_active": True}, headers=admin)
    ).status_code == 422
    bad = await c.put(
        f"/api/v1/sequences/{empty['id']}/steps",
        json=[{"kind": "check", "check_if": "opened", "go_to": 1}],
        headers=admin,
    )
    assert bad.status_code == 422


async def test_an_automation_can_put_a_lead_into_a_sequence(ws):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    seq = await _sequence(c, admin, [{"kind": "email", "template_id": t["id"]}])
    r = await c.post(
        "/api/v1/automations",
        json={"name": "Welcome new leads", "trigger": {"type": "lead.created"}, "conditions": [],
              "actions": [{"type": "enrol", "sequence_id": seq["id"]}], "is_active": True},
        headers=admin,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    lead = await _lead(c, admin)
    from app.modules.crm.automation import process_tenant

    await process_tenant(tenant_id)
    assert (await _enrolment(tenant_id, lead["id"])).status == "active"


async def test_another_company_sees_none_of_it(ws, client_for):
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    seq = await _sequence(c, admin, [{"kind": "email", "template_id": t["id"]}])
    await _enrol(c, admin, seq, await _lead(c, admin))
    await _run(tenant_id)
    token = (await _messages(tenant_id))[0].token
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)
    assert (await oc.get("/api/v1/sequences", headers=other_admin)).json() == []
    assert (await oc.get("/api/v1/templates", headers=other_admin)).json() == []
    assert (await oc.get(f"/api/v1/sequences/{seq['id']}", headers=other_admin)).status_code == 404
    assert "no longer valid" in (await oc.get(f"/api/v1/u/{token}")).text

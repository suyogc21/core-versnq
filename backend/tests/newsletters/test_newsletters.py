"""Batch 5b of the finishing plan: newsletters.

Only people who can get email are on the list (an address, not opted out, not suppressed);
the list is fixed at send time and each person is checked again before their copy goes; the
company inboxes' daily cap holds; Postmark's broadcast stream works in test mode and is refused
when it isn't set up; opens, clicks and the one-click unsubscribe are the same as every email;
every copy is on the lead's timeline; only newsletters.manage; another company sees nothing."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.crm.models import Activity, Lead, Suppression
from app.modules.engage.models import Message
from app.modules.newsletters import postmark as PM
from app.modules.newsletters.service import run_tenant
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

ALWAYS = {"from": "00:00", "to": "24:00", "days": [0, 1, 2, 3, 4, 5, 6], "daily_cap": 200}
BODY = "Hi {{lead.first_name|there}},\n\nNew batches: https://example.com/batches\n\nTeam"


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    _, admin = await login_as(tenant_id, "admin")
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = dict(ALWAYS)
    return tenant_id, c, admin


async def _lead(c, h, email: str | None, name: str, tags=("News",)):
    _, sources = await setup_ids(c, h)
    ids = [{"type": "phone", "value": f"98{uuid.uuid4().int % 10**8:08d}"}]
    if email:
        ids.append({"type": "email", "value": email})
    r = await new_lead(c, h, sources["Website"], identities=ids, first_name=name)
    assert r.status_code == 201, r.text
    lead = r.json()
    if tags:
        await c.put(f"/api/v1/leads/{lead['id']}/tags", json={"new": list(tags)}, headers=h)
    return lead


async def _tag_id(c, h, name="News"):
    return next(
        t["id"] for t in (await c.get("/api/v1/tags", headers=h)).json() if t["name"] == name
    )


async def _newsletter(c, h, **extra):
    body = {"name": "November", "subject": "Hi {{lead.first_name|there}}", "body": BODY,
            "preheader": "Batches starting soon",
            "audience": {"filter": {"tag": [await _tag_id(c, h)]}}, **extra}  # fmt: skip
    r = await c.post("/api/v1/newsletters", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def test_only_people_who_can_get_email_are_sent_and_logged(ws):
    tenant_id, c, admin = ws
    asha = await _lead(c, admin, "asha@example.com", "Asha")
    ravi = await _lead(c, admin, "ravi@example.com", "Ravi")
    out = await _lead(c, admin, "out@example.com", "Optedout")
    listed = await _lead(c, admin, "listed@example.com", "Listed")
    await _lead(c, admin, None, "Nomail")
    await _lead(c, admin, "other@example.com", "Untagged", tags=())
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(Lead).where(Lead.id == uuid.UUID(out["id"])).values(email_consent="opted_out")
        )
        db.add(Suppression(tenant_id=tenant_id, channel="email",
                           value_normalized="listed@example.com", reason="complaint"))  # fmt: skip
    nl = await _newsletter(c, admin)
    count = await c.post("/api/v1/newsletters/audience-count", json=nl["audience"], headers=admin)
    sent = await c.post(f"/api/v1/newsletters/{nl['id']}/send", json={}, headers=admin)
    await run_tenant(tenant_id)
    after = (await c.get(f"/api/v1/newsletters/{nl['id']}", headers=admin)).json()

    assert count.json() == {"matching": 5, "reachable": 2}
    assert sent.status_code == 200 and sent.json()["report"]["recipients"] == 2
    assert after["status"] == "sent" and after["report"]["sent"] == 2
    async with tenant_session(tenant_id) as db:
        msgs = (await db.scalars(select(Message).where(Message.channel == "email"))).all()
        acts = (await db.scalars(select(Activity).where(Activity.type_key == "email_sent"))).all()
    assert {m.to_address for m in msgs} == {"asha@example.com", "ravi@example.com"}
    assert {m.subject for m in msgs} == {"Hi Asha", "Hi Ravi"}
    assert all(m.token and m.status == "sent" and m.direction == "out" for m in msgs)
    assert {str(a.lead_id) for a in acts} == {asha["id"], ravi["id"]}
    assert {a.summary for a in acts} == {"Newsletter sent: Hi Asha", "Newsletter sent: Hi Ravi"}
    assert listed["id"] not in {str(a.lead_id) for a in acts}


async def test_opens_clicks_and_unsubscribe_are_tracked_and_honoured(ws):
    tenant_id, c, admin = ws
    asha = await _lead(c, admin, "asha@example.com", "Asha")
    nl = await _newsletter(c, admin)
    await c.post(f"/api/v1/newsletters/{nl['id']}/send", json={}, headers=admin)
    await run_tenant(tenant_id)
    async with tenant_session(tenant_id) as db:
        msg = await db.scalar(select(Message).where(Message.to_address == "asha@example.com"))
    assert msg.links == ["https://example.com/batches"]

    await c.get(f"/api/v1/t/o/{msg.token}.gif")
    click = await c.get(f"/api/v1/t/c/{msg.token}/0")
    unsub = await c.post(f"/api/v1/u/{msg.token}")
    report = (await c.get(f"/api/v1/newsletters/{nl['id']}", headers=admin)).json()["report"]
    people = (await c.get(f"/api/v1/newsletters/{nl['id']}/recipients", headers=admin)).json()
    again = await _newsletter(c, admin, name="December")
    count = await c.post(
        "/api/v1/newsletters/audience-count", json=again["audience"], headers=admin
    )

    assert click.status_code == 302 and unsub.status_code == 200
    assert (report["opened"], report["clicked"], report["unsubscribed"]) == (1, 1, 1)
    assert people[0]["lead_id"] == asha["id"] and people[0]["unsubscribed"] and people[0]["clicked"]
    assert count.json()["reachable"] == 0  # unsubscribed: never on a list again


async def test_the_inboxes_daily_cap_holds_and_the_rest_waits(ws):
    tenant_id, c, admin = ws
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).engage = {**ALWAYS, "daily_cap": 1}
    for i in range(3):
        await _lead(c, admin, f"p{i}@example.com", f"P{i}")
    nl = await _newsletter(c, admin)
    await c.post(f"/api/v1/newsletters/{nl['id']}/send", json={}, headers=admin)
    await run_tenant(tenant_id)
    await run_tenant(tenant_id)
    after = (await c.get(f"/api/v1/newsletters/{nl['id']}", headers=admin)).json()
    assert after["status"] == "sending"
    assert (after["report"]["sent"], after["report"]["queued"]) == (1, 2)


async def test_someone_who_opts_out_after_the_list_is_fixed_is_skipped(ws):
    tenant_id, c, admin = ws
    await _lead(c, admin, "asha@example.com", "Asha")
    late = await _lead(c, admin, "late@example.com", "Late")
    nl = await _newsletter(c, admin)
    await c.post(f"/api/v1/newsletters/{nl['id']}/send", json={}, headers=admin)
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(Lead).where(Lead.id == uuid.UUID(late["id"])).values(email_consent="opted_out")
        )
    await run_tenant(tenant_id)
    report = (await c.get(f"/api/v1/newsletters/{nl['id']}", headers=admin)).json()["report"]
    assert (report["sent"], report["skipped"]) == (1, 1)


async def test_postmark_broadcast_in_test_mode_and_refused_when_not_set_up(ws, monkeypatch):
    tenant_id, c, admin = ws
    await _lead(c, admin, "asha@example.com", "Asha")
    no_from = await _newsletter(c, admin, path="postmark")
    missing = await c.post(f"/api/v1/newsletters/{no_from['id']}/send", json={}, headers=admin)
    nl = await _newsletter(c, admin, name="PM", path="postmark", from_email="news@acme.example",
                           from_name="Acme")  # fmt: skip
    PM.SENT.clear()
    monkeypatch.setattr(get_settings(), "postmark_mode", "live")
    monkeypatch.setattr(get_settings(), "postmark_server_token", None)
    not_set_up = await c.post(f"/api/v1/newsletters/{nl['id']}/send", json={}, headers=admin)
    monkeypatch.setattr(get_settings(), "postmark_mode", "test")
    ok = await c.post(f"/api/v1/newsletters/{nl['id']}/send", json={}, headers=admin)
    await run_tenant(tenant_id)
    report = (await c.get(f"/api/v1/newsletters/{nl['id']}", headers=admin)).json()["report"]

    assert missing.json()["code"] == "from_missing"
    assert not_set_up.json()["code"] == "postmark_missing" and ok.status_code == 200
    assert report["sent"] == 1 and len(PM.SENT) == 1
    sent = PM.SENT[0]
    assert sent["MessageStream"] == "broadcast" and sent["To"] == "asha@example.com"
    assert sent["From"] == '"Acme" <news@acme.example>' and sent["Subject"] == "Hi Asha"
    names = {h["Name"]: h["Value"] for h in sent["Headers"]}
    assert "/api/v1/u/" in names["List-Unsubscribe"] and "Batches starting soon" in sent["HtmlBody"]


async def test_schedule_cancel_test_send_and_checks(ws):
    tenant_id, c, admin = ws
    await _lead(c, admin, "asha@example.com", "Asha")
    bad = await c.post("/api/v1/newsletters", headers=admin, json={
        "name": "x", "subject": "x", "body": "Hi {{lead.nope}}"})  # fmt: skip
    nl = await _newsletter(c, admin)
    test = await c.post(f"/api/v1/newsletters/{nl['id']}/test", headers=admin)
    later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    scheduled = await c.post(f"/api/v1/newsletters/{nl['id']}/send", json={"send_at": later},
                             headers=admin)  # fmt: skip
    await run_tenant(tenant_id)
    edit = await c.patch(f"/api/v1/newsletters/{nl['id']}", json={"name": "y"}, headers=admin)
    cancelled = await c.post(f"/api/v1/newsletters/{nl['id']}/cancel", headers=admin)

    assert bad.status_code == 422 and test.status_code == 204
    assert scheduled.json()["status"] == "scheduled"
    assert edit.status_code == 409
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["report"]["skipped"] == 1 and cancelled.json()["report"]["sent"] == 0


async def test_who_may_and_other_companies(ws, client_for):
    tenant_id, c, admin = ws
    await _lead(c, admin, "asha@example.com", "Asha")
    nl = await _newsletter(c, admin)
    _, rep = await login_as(tenant_id, "sales_user")
    _, manager = await login_as(tenant_id, "sales_manager")
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    other = client_for(other_slug)

    assert (await c.get("/api/v1/newsletters", headers=rep)).status_code == 403
    assert (await c.get("/api/v1/newsletters", headers=manager)).status_code == 200
    assert (
        await other.get(f"/api/v1/newsletters/{nl['id']}", headers=other_admin)
    ).status_code == 404
    assert (await other.get("/api/v1/newsletters", headers=other_admin)).json() == []

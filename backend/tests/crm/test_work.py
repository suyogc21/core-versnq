"""Timeline, the follow-up rule, one-step logging, tasks, My Day and task.due."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.crm.models import Task
from app.modules.crm.work import notify_due_tasks
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as


def iso(delta_hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=delta_hours)).isoformat()


async def _lead(c, h, **extra):
    _, sources = await setup_ids(c, h)
    return (await new_lead(c, h, sources["Website"], **extra)).json()


async def _follow_ups(tenant_id, lead_id):
    async with tenant_session(tenant_id) as s:
        rows = await s.scalars(
            select(Task)
            .where(Task.lead_id == lead_id, Task.is_follow_up.is_(True))
            .order_by(Task.created_at)
        )
        return [(t.status, t.due_at) for t in rows.all()]


async def test_logging_a_call_needs_an_outcome_and_the_next_follow_up(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, next_follow_up_at=iso(-1))  # already overdue
    url = f"/api/v1/leads/{lead['id']}/activities"

    no_outcome = await c.post(
        url, json={"type_key": "call", "next_follow_up_at": iso(24)}, headers=rep
    )
    no_follow_up = await c.post(
        url, json={"type_key": "call", "data": {"disposition": "interested"}}, headers=rep
    )
    past_follow_up = await c.post(
        url,
        json={
            "type_key": "call",
            "next_follow_up_at": iso(-2),
            "data": {"disposition": "interested"},
        },
        headers=rep,
    )
    ok = await c.post(
        url,
        json={
            "type_key": "call",
            "body": "Wants weekend timings",
            "data": {"disposition": "interested"},
            "next_follow_up_at": iso(24),
        },
        headers=rep,
    )

    assert (no_outcome.status_code, no_follow_up.status_code, past_follow_up.status_code) == (
        422,
        422,
        422,
    )
    assert "follow-up" in no_follow_up.json()["detail"]
    assert ok.status_code == 201
    body = ok.json()
    assert body["activity"]["summary"] == "Call: Interested"
    assert body["lead"]["last_disposition"] == "Interested"
    assert body["lead"]["last_contacted_at"] and body["lead"]["version"] == 2
    # One-step logging: the overdue follow-up is done, a new one is open.
    assert [s for s, _ in await _follow_ups(tenant_id, lead["id"])] == ["done", "open"]
    async with tenant_session(tenant_id) as s:
        assert "activity.logged" in (await s.scalars(select(Event.type))).all()


async def test_follow_up_rule_can_be_set_to_warn_only(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    settings = await c.patch("/api/v1/crm-rules", json={"follow_up_required": False}, headers=admin)
    lead = await _lead(c, rep)

    logged = await c.post(
        f"/api/v1/leads/{lead['id']}/activities",
        json={"type_key": "call", "data": {"disposition": "not_reachable"}},
        headers=rep,
    )
    assert settings.json()["follow_up_required"] is False and logged.status_code == 201


async def test_notes_custom_types_and_closed_leads(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await c.post(
        "/api/v1/activity-types",
        json={
            "key": "site_visit",
            "label": "Site visit done",
            "fields": [{"key": "rating", "label": "Rating", "type": "number", "required": True}],
        },
        headers=admin,
    )
    stages, _ = await setup_ids(c, admin)
    lead = await _lead(c, admin)
    url = f"/api/v1/leads/{lead['id']}/activities"

    empty_note = await c.post(
        url, json={"type_key": "note", "next_follow_up_at": iso(5)}, headers=admin
    )
    note = await c.post(
        url,
        json={
            "type_key": "note",
            "body": "Prefers Hindi\nCall after 6",
            "next_follow_up_at": iso(5),
        },
        headers=admin,
    )
    visit_missing = await c.post(
        url, json={"type_key": "site_visit", "next_follow_up_at": iso(5)}, headers=admin
    )
    visit = await c.post(
        url,
        json={"type_key": "site_visit", "data": {"rating": "4"}, "next_follow_up_at": iso(5)},
        headers=admin,
    )
    system_type = await c.post(
        url, json={"type_key": "stage_changed", "next_follow_up_at": iso(5)}, headers=admin
    )
    future = await c.post(
        url,
        json={"type_key": "note", "body": "x", "occurred_at": iso(3), "next_follow_up_at": iso(5)},
        headers=admin,
    )

    assert (empty_note.status_code, visit_missing.status_code, system_type.status_code) == (
        422,
        422,
        422,
    )
    assert note.json()["activity"]["summary"] == "Prefers Hindi"
    assert note.json()["lead"]["last_contacted_at"] is None  # a note is not contact
    assert visit.json()["activity"]["data"] == {"rating": 4} and future.status_code == 422

    current = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()
    closed = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": current["version"], "stage_id": stages["Won"]["id"]},
        headers=admin,
    )
    after_close = await c.post(url, json={"type_key": "note", "body": "Paid"}, headers=admin)
    follow_up_on_closed = await c.post(
        url, json={"type_key": "note", "body": "x", "next_follow_up_at": iso(5)}, headers=admin
    )
    assert closed.status_code == 200 and after_close.status_code == 201
    assert follow_up_on_closed.status_code == 422


async def test_timeline_is_newest_first_and_follows_lead_visibility(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, other_rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep)
    await c.post(
        f"/api/v1/leads/{lead['id']}/activities",
        json={"type_key": "note", "body": "Second", "next_follow_up_at": iso(5)},
        headers=rep,
    )

    timeline = await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)
    hidden = await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=other_rep)
    assert [a["type_key"] for a in timeline.json()] == ["note", "lead_created"]
    assert timeline.json()[0]["actor_name"] == "Member"
    assert hidden.status_code == 404


async def test_task_rules(ws):
    tenant_id, c = ws
    a_id, rep = await login_as(tenant_id, "sales_user")
    b_id, _ = await login_as(tenant_id, "sales_user")
    m_id, mgr = await login_as(tenant_id, "sales_manager")
    await make_team(tenant_id, m_id, [a_id, b_id])
    lead = await _lead(c, rep, next_follow_up_at=iso(30))

    own = await c.post(
        "/api/v1/tasks",
        json={"title": "Send brochure", "due_at": iso(2), "lead_id": lead["id"]},
        headers=rep,
    )
    for_other = await c.post(
        "/api/v1/tasks",
        json={"title": "X", "due_at": iso(2), "owner_user_id": str(b_id)},
        headers=rep,
    )
    mgr_assigns = await c.post(
        "/api/v1/tasks",
        json={"title": "Call back", "due_at": iso(2), "owner_user_id": str(b_id)},
        headers=mgr,
    )
    assert (own.status_code, for_other.status_code, mgr_assigns.status_code) == (201, 403, 201)
    assert own.json()["lead_name"] == "Rahul"

    follow_up = next(
        t
        for t in (await c.get(f"/api/v1/tasks?lead_id={lead['id']}", headers=rep)).json()
        if t["is_follow_up"]
    )
    moved = await c.patch(f"/api/v1/tasks/{follow_up['id']}", json={"due_at": iso(48)}, headers=rep)
    lead_after_move = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    done = await c.patch(f"/api/v1/tasks/{own.json()['id']}", json={"status": "done"}, headers=rep)
    timeline = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)).json()

    assert moved.status_code == 200
    assert lead_after_move["next_follow_up_at"][:13] == moved.json()["due_at"][:13]
    assert done.json()["status"] == "done" and timeline[0]["type_key"] == "task_completed"
    team_open = (await c.get("/api/v1/tasks?scope=team", headers=mgr)).json()
    team_done = (await c.get("/api/v1/tasks?scope=team&status=done", headers=mgr)).json()
    rep_team = (await c.get("/api/v1/tasks?scope=team", headers=rep)).json()
    assert "Call back" in {t["title"] for t in team_open}
    assert {t["title"] for t in team_done} == {"Send brochure"}
    # A rep's scope is their own: "team" still shows only their tasks, not B's "Call back".
    assert rep_team and {t["owner_user_id"] for t in rep_team} == {str(a_id)}


async def test_my_day_buckets_and_queue_order(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, mgr = await login_as(tenant_id, "sales_manager")
    late = await _lead(c, rep, first_name="Late", next_follow_up_at=iso(-30))
    later = await _lead(c, rep, first_name="Later", phone="98765 43219", next_follow_up_at=iso(-2))
    await _lead(c, rep, first_name="Next week", phone="98765 43218", next_follow_up_at=iso(24 * 5))
    fresh = await _lead(c, rep, first_name="Fresh", phone="98765 43217")
    await _lead(c, mgr, first_name="Nobody's", phone="98765 43216", assign_to_me=False)

    day = (await c.get("/api/v1/me/day", headers=rep)).json()
    mgr_day = (await c.get("/api/v1/me/day", headers=mgr)).json()

    assert [t["lead_name"] for t in day["overdue"]] == ["Late", "Later"]  # oldest first
    assert [t["lead_name"] for t in day["upcoming"]] == ["Next week"]
    assert fresh["id"] in {lead["id"] for lead in day["new_leads"]}
    assert {late["id"], later["id"]} <= {t["lead_id"] for t in day["overdue"]}
    assert day["unassigned_count"] is None and mgr_day["unassigned_count"] == 1
    # The dialer's list after the follow-ups: own leads never contacted with nothing booked.
    assert [lead["id"] for lead in day["to_call"]] == [fresh["id"]]


async def test_task_due_is_emitted_once(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    await c.post("/api/v1/tasks", json={"title": "Overdue", "due_at": iso(-1)}, headers=rep)
    await c.post("/api/v1/tasks", json={"title": "Later", "due_at": iso(5)}, headers=rep)

    await notify_due_tasks()
    await notify_due_tasks()
    async with tenant_session(tenant_id) as s:
        due = (await s.scalars(select(Event).where(Event.type == "task.due"))).all()
    assert len(due) == 1

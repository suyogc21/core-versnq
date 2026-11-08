"""Step 1: assignment rules, response-time (SLA) rules, the leakage guard, notifications."""

import asyncio
from collections import Counter
from datetime import timedelta

from sqlalchemy import select, update

from app.core.tenancy import tenant_session
from app.modules.crm import leads as L
from app.modules.crm import routing as R
from app.modules.crm.models import Lead, LeadSla, LeadSource, Task
from app.modules.users.models import User
from tests.crm.helpers import make_team
from tests.crm.intake_helpers import (
    activities,
    backdate,
    capture,
    lead,
    notifications,
    rule,
    settings,
)
from tests.factories import login_as


async def _reps(tenant_id, n=3):
    return [(await login_as(tenant_id, "sales_user"))[0] for _ in range(n)]


async def _owner(tenant_id, lead_id):
    return (await lead(tenant_id, lead_id)).owner_user_id


# ---------- assignment ----------
async def test_round_robin_gives_equal_turns(ws):
    tenant_id, _ = ws
    reps = await _reps(tenant_id)
    await rule(tenant_id, user_ids=reps)
    owners = [
        await _owner(
            tenant_id, (await capture(tenant_id, phone=f"98765 1000{i}", owner="rules"))[1]
        )
        for i in range(6)
    ]
    assert owners == reps + reps


async def test_round_robin_is_fair_when_leads_arrive_together(ws):
    tenant_id, _ = ws
    reps = await _reps(tenant_id)
    await rule(tenant_id, user_ids=reps)
    results = await asyncio.gather(
        *[capture(tenant_id, phone=f"98765 2000{i}", owner="rules") for i in range(9)]
    )
    counts = Counter([await _owner(tenant_id, lead_id) for _, lead_id in results])
    assert sorted(counts.values()) == [3, 3, 3]


async def test_disabled_people_are_skipped_and_new_leads_tell_the_owner(ws):
    tenant_id, _ = ws
    a, b, c = await _reps(tenant_id)
    await rule(tenant_id, user_ids=[a, b, c])
    async with tenant_session(tenant_id) as db:
        await db.execute(update(User).where(User.id == b).values(status="disabled"))
    owners = [
        await _owner(
            tenant_id, (await capture(tenant_id, phone=f"98765 3000{i}", owner="rules"))[1]
        )
        for i in range(4)
    ]
    assert owners == [a, c, a, c]
    assert [k for k, _ in await notifications(tenant_id, a)] == ["lead_assigned", "lead_assigned"]


async def test_first_matching_rule_wins_and_conditions_use_any_field(ws):
    tenant_id, _ = ws
    hindi, english, fallback = await _reps(tenant_id)
    async with tenant_session(tenant_id) as db:
        sources = {s.name: s.id for s in (await db.scalars(select(LeadSource))).all()}
    await rule(
        tenant_id,
        strategy="user",
        user_ids=[hindi],
        conditions=[{"field": "preferred_language", "op": "in", "values": ["HI"]}],
        position=0,
    )
    await rule(
        tenant_id,
        strategy="user",
        user_ids=[english],
        conditions=[{"field": "source", "op": "in", "values": [str(sources["Website"])]}],
        position=1,
    )
    await rule(tenant_id, strategy="user", user_ids=[fallback], position=2)

    _, l1 = await capture(
        tenant_id,
        phone="98765 40001",
        owner="rules",
        source_id=sources["Website"],
        fields={"preferred_language": "hi"},
    )
    _, l2 = await capture(
        tenant_id, phone="98765 40002", owner="rules", source_id=sources["Website"]
    )
    _, l3 = await capture(
        tenant_id, phone="98765 40003", owner="rules", source_id=sources["Referral"]
    )
    assert [await _owner(tenant_id, x) for x in (l1, l2, l3)] == [hindi, english, fallback]


async def test_unassigned_strategy_and_no_match_leave_the_lead_for_a_manager(ws):
    tenant_id, _ = ws
    (rep,) = await _reps(tenant_id, 1)
    await rule(
        tenant_id,
        strategy="unassigned",
        conditions=[{"field": "city", "op": "in", "values": ["Dubai"]}],
        position=0,
    )
    await rule(
        tenant_id,
        strategy="user",
        user_ids=[rep],
        conditions=[{"field": "city", "op": "in", "values": ["Pune"]}],
        position=1,
    )
    _, dubai = await capture(
        tenant_id, phone="98765 50001", owner="rules", fields={"city": "dubai"}
    )
    _, nowhere = await capture(
        tenant_id, phone="98765 50002", owner="rules", fields={"city": "Goa"}
    )
    assert await _owner(tenant_id, dubai) is None and await _owner(tenant_id, nowhere) is None


async def test_team_pool_falls_through_when_nobody_is_available(ws):
    tenant_id, _ = ws
    mgr, _ = await login_as(tenant_id, "sales_manager")
    (rep,) = await _reps(tenant_id, 1)
    team = await make_team(tenant_id, mgr, [rep])
    await rule(tenant_id, team_id=team, position=0)
    async with tenant_session(tenant_id) as db:
        await db.execute(update(User).where(User.id.in_([mgr, rep])).values(status="disabled"))
    (other,) = await _reps(tenant_id, 1)
    await rule(tenant_id, strategy="user", user_ids=[other], position=1)
    _, x = await capture(tenant_id, phone="98765 50003", owner="rules")
    assert await _owner(tenant_id, x) == other


async def test_rules_api_validates_and_needs_permission(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, mgr = await login_as(tenant_id, "sales_manager")
    (rep,) = await _reps(tenant_id, 1)
    body = {"name": "Website leads", "strategy": "round_robin", "user_ids": [str(rep)]}
    assert (await c.post("/api/v1/assignment-rules", json=body, headers=mgr)).status_code == 403
    assert (await c.get("/api/v1/assignment-rules", headers=mgr)).status_code == 403
    ok = await c.post("/api/v1/assignment-rules", json=body, headers=admin)
    assert ok.status_code == 201
    bad = [
        {"name": "x", "strategy": "round_robin"},
        {"name": "x", "strategy": "user", "user_ids": [str(rep), str(rep)]},
        {"name": "x", "strategy": "unassigned", "conditions": [{"field": "nope", "op": "empty"}]},
        {"name": "x", "strategy": "unassigned", "conditions": [{"field": "city", "op": "in"}]},
        {"name": "x", "strategy": "unassigned", "conditions": [
            {"field": "source", "op": "in", "values": ["not-a-source"]}]},
    ]  # fmt: skip
    for b in bad:
        assert (await c.post("/api/v1/assignment-rules", json=b, headers=admin)).status_code == 422
    second = await c.post(
        "/api/v1/assignment-rules", json={"name": "Rest", "strategy": "unassigned"}, headers=admin
    )
    ids = [second.json()["id"], ok.json()["id"]]
    assert (
        await c.put("/api/v1/assignment-rules/order", json={"ids": ids}, headers=admin)
    ).status_code == 204
    listed = (await c.get("/api/v1/assignment-rules", headers=admin)).json()
    assert [r["id"] for r in listed] == ids


async def test_managers_can_add_a_lead_by_the_rules(ws):
    tenant_id, c = ws
    _, mgr = await login_as(tenant_id, "sales_manager")
    _, rep_h = await login_as(tenant_id, "sales_user")
    (rep,) = await _reps(tenant_id, 1)
    await rule(tenant_id, strategy="user", user_ids=[rep])
    src = (await c.get("/api/v1/lead-sources", headers=mgr)).json()[0]["id"]
    body = {
        "identities": [{"type": "phone", "value": "98765 60001"}],
        "source_id": src,
        "assign_by_rules": True,
    }
    r = await c.post("/api/v1/leads", json=body, headers=mgr)
    assert r.status_code == 201 and r.json()["owner_user_id"] == str(rep)
    body["identities"] = [{"type": "phone", "value": "98765 60002"}]
    assert (await c.post("/api/v1/leads", json=body, headers=rep_h)).status_code == 403


# ---------- SLAs ----------
async def _sla(c, h, **body):
    r = await c.post("/api/v1/sla-rules", json={"name": "First call", **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _expire_clocks(tenant_id, lead_id):
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(LeadSla)
            .where(LeadSla.lead_id == lead_id)
            .values(started_at=L.now() - timedelta(hours=2), due_at=L.now() - timedelta(minutes=1))
        )


async def _run_checks(tenant_id):
    async with tenant_session(tenant_id) as db:
        missed = await R.check_slas(db)
        leaking = await R.check_leakage(db, tenant_id)
    return missed, leaking


async def test_sla_creates_a_task_and_alerts_the_manager_once_when_missed(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    mgr, _ = await login_as(tenant_id, "sales_manager")
    (rep,) = await _reps(tenant_id, 1)
    await make_team(tenant_id, mgr, [rep])
    await _sla(c, admin, trigger="lead_created", within_minutes=30, task_title="Call new lead")
    _, lead_id = await capture(tenant_id, phone="98765 70001", owner=rep)
    async with tenant_session(tenant_id) as db:
        task = await db.scalar(select(Task).where(Task.lead_id == lead_id))
    assert (task.title, task.created_from, task.owner_user_id) == ("Call new lead", "sla_rule", rep)

    await _expire_clocks(tenant_id, lead_id)
    assert (await _run_checks(tenant_id))[0] == 1
    assert (await _run_checks(tenant_id))[0] == 0  # once only
    assert "sla_missed" in await activities(tenant_id, lead_id)
    assert [k for k, _ in await notifications(tenant_id, mgr)] == ["lead_at_risk"]


async def test_sla_is_met_by_a_call_and_skipped_for_closed_leads(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await _sla(c, admin, trigger="lead_created", within_minutes=30, create_task=False)
    _, called = await capture(tenant_id, phone="98765 70002")
    _, closed = await capture(tenant_id, phone="98765 70003")
    r = await c.post(
        f"/api/v1/leads/{called}/activities",
        json={
            "type_key": "call",
            "data": {"disposition": "interested"},
            "next_follow_up_at": (L.now() + timedelta(days=1)).isoformat(),
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    async with tenant_session(tenant_id) as db:
        met = await db.scalar(select(LeadSla.met_at).where(LeadSla.lead_id == called))
        await db.execute(update(Lead).where(Lead.id == closed).values(is_open=False))
    assert met is not None
    await _expire_clocks(tenant_id, closed)
    assert (await _run_checks(tenant_id))[0] == 0


async def test_sla_on_entering_a_stage_and_reassign_on_breach(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    first, second = await _reps(tenant_id, 2)
    await rule(tenant_id, user_ids=[first, second])
    stages = {s["name"]: s for s in (await c.get("/api/v1/lead-stages", headers=admin)).json()}
    await _sla(
        c,
        admin,
        trigger="stage_entered",
        stage_id=stages["Qualified"]["id"],
        within_minutes=60,
        on_breach="reassign",
    )
    _, lead_id = await capture(tenant_id, phone="98765 70004", owner="rules")
    assert await _owner(tenant_id, lead_id) == first
    found = await lead(tenant_id, lead_id)
    r = await c.patch(
        f"/api/v1/leads/{lead_id}",
        json={"version": found.version, "stage_id": stages["Qualified"]["id"]},
        headers=admin,
    )
    assert r.status_code == 200
    await _expire_clocks(tenant_id, lead_id)
    await _run_checks(tenant_id)
    assert await _owner(tenant_id, lead_id) == second
    assert ("lead_assigned", f"New lead: {found.display_name}") in await notifications(
        tenant_id, second
    )


async def test_sla_rule_needs_an_open_stage(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    stages = {s["name"]: s for s in (await c.get("/api/v1/lead-stages", headers=admin)).json()}
    for body in (
        {"trigger": "stage_entered", "within_minutes": 5},
        {"trigger": "stage_entered", "stage_id": stages["Lost"]["id"], "within_minutes": 5},
        {"trigger": "lead_created", "stage_id": stages["New"]["id"], "within_minutes": 5},
        {"trigger": "lead_created", "within_minutes": 0},
    ):
        r = await c.post("/api/v1/sla-rules", json={"name": "x", **body}, headers=admin)
        assert r.status_code == 422, body


# ---------- leakage guard ----------
async def test_leakage_guard_flags_untouched_and_overdue_leads_once(ws):
    tenant_id, _ = ws
    mgr, _ = await login_as(tenant_id, "sales_manager")
    (rep,) = await _reps(tenant_id, 1)
    await make_team(tenant_id, mgr, [rep])
    _, untouched = await capture(tenant_id, phone="98765 80001", owner=rep)
    _, overdue = await capture(tenant_id, phone="98765 80002", owner=rep)
    _, fine = await capture(tenant_id, phone="98765 80003", owner=rep)
    await backdate(tenant_id, untouched, 5)
    await backdate(
        tenant_id,
        overdue,
        48,
        last_contacted_at=L.now() - timedelta(hours=40),
        next_follow_up_at=L.now() - timedelta(hours=4),
    )
    await backdate(tenant_id, fine, 1)

    assert (await _run_checks(tenant_id))[1] == 0  # off by default
    await settings(tenant_id, leakage_hours=3)
    assert (await _run_checks(tenant_id))[1] == 2
    assert (await _run_checks(tenant_id))[1] == 0
    titles = [t for _, t in await notifications(tenant_id, mgr)]
    assert any("not contacted for 3 hours" in t for t in titles)
    assert any("follow-up overdue" in t for t in titles)


async def test_leakage_guard_can_reassign(ws):
    tenant_id, _ = ws
    a, b = await _reps(tenant_id, 2)
    await rule(tenant_id, user_ids=[a, b])
    await settings(tenant_id, leakage_hours=2, leakage_action="reassign")
    _, lead_id = await capture(tenant_id, phone="98765 80004", owner="rules")
    assert await _owner(tenant_id, lead_id) == a
    await backdate(tenant_id, lead_id, 3)
    await _run_checks(tenant_id)
    assert await _owner(tenant_id, lead_id) == b


# ---------- notifications ----------
async def test_notifications_are_private_and_can_be_marked_read(ws):
    tenant_id, c = ws
    rep, rep_h = await login_as(tenant_id, "sales_user")
    _, other_h = await login_as(tenant_id, "sales_user")
    await capture(tenant_id, phone="98765 90001", owner=rep)
    await capture(tenant_id, phone="98765 90002", owner=rep)
    mine = (await c.get("/api/v1/notifications", headers=rep_h)).json()
    assert mine["unread"] == 2 and len(mine["items"]) == 2
    assert (await c.get("/api/v1/notifications", headers=other_h)).json()["unread"] == 0
    first = mine["items"][0]["id"]
    await c.post("/api/v1/notifications/read", json={"ids": [first]}, headers=other_h)
    assert (await c.get("/api/v1/notifications", headers=rep_h)).json()["unread"] == 2
    await c.post("/api/v1/notifications/read", json={"ids": [first]}, headers=rep_h)
    assert (await c.get("/api/v1/notifications", headers=rep_h)).json()["unread"] == 1
    await c.post("/api/v1/notifications/read", json={}, headers=rep_h)
    left = (await c.get("/api/v1/notifications?unread_only=true", headers=rep_h)).json()
    assert left == {"items": [], "unread": 0}


async def test_due_tasks_notify_their_owner(ws):
    tenant_id, _ = ws
    from app.modules.crm.work import notify_due_tasks

    rep, _ = await login_as(tenant_id, "sales_user")
    _, lead_id = await capture(
        tenant_id, phone="98765 90003", owner=rep, next_follow_up_at=L.now() + timedelta(hours=1)
    )
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(Task)
            .where(Task.lead_id == lead_id)
            .values(due_at=L.now() - timedelta(minutes=1))
        )
    await notify_due_tasks()
    assert [k for k, _ in await notifications(tenant_id, rep)] == ["lead_assigned", "task_due"]

"""Step 4: calculated fields, tags, saved views, scoring, automation."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.core.errors import Invalid
from app.core.tenancy import tenant_session
from app.modules.crm import automation as A
from app.modules.crm import formula as FX
from app.modules.crm.models import Activity, Automation, AutomationRun, Lead, Task
from app.modules.crm.scoring import rescore_tenant
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as, make_workspace


async def _lead(c, h, phone="98765 43210", source="Website", **extra):
    _, sources = await setup_ids(c, h)
    r = await new_lead(c, h, sources[source], phone=phone, **extra)
    assert r.status_code == 201, r.text
    return r.json()


async def _field(c, h, entity="lead", **body):
    return await c.post(f"/api/v1/custom-fields?entity={entity}", json=body, headers=h)


# ---------- formulas ----------
def _ev(text, values=None, fields=None):
    fields = fields or {k: "number" for k in (values or {})}
    node = FX.check(text, fields)
    vals = {
        k: (v if isinstance(v, date) or v is None else Decimal(str(v)))
        for k, v in (values or {}).items()
    }
    return FX.evaluate(node, vals, date(2026, 11, 11))


def test_formula_arithmetic_precedence_and_empties():
    assert _ev("2 + 3 * 4") == 14
    assert _ev("(2 + 3) * 4") == 20
    assert _ev("-a + 10", {"a": 3}) == 7
    assert _ev("fee - ifempty(scholarship, 0)", {"fee": 50000, "scholarship": None}) == 50000
    assert _ev("fee - scholarship", {"fee": 50000, "scholarship": None}) is None
    assert _ev("a / b", {"a": 1, "b": 0}) is None  # dividing by zero: empty, not a crash
    assert _ev("round(a * 18 / 100, 2)", {"a": "999.99"}) == Decimal("180.00")
    assert _ev("round(2.5)") == 3  # half up
    assert _ev("max(a, b, 7)", {"a": 1, "b": 9}) == 9
    assert FX.to_stored(Decimal("2.50")) == 2.5 and FX.to_stored(Decimal("3.000")) == 3


def test_formula_dates():
    fields = {"enquiry": "date"}
    assert _ev("days_between(enquiry, today())", {"enquiry": date(2026, 11, 1)}, fields) == 10
    with pytest.raises(Invalid):
        FX.check("enquiry + 1", fields)  # dates only through days_between()
    with pytest.raises(Invalid):
        FX.check("days_between(1, today())", fields)


@pytest.mark.parametrize(
    "bad",
    [
        "__import__('os')",
        "a.b",
        "open(1)",
        "1 +",
        "(1",
        "a[0]",
        "lambda: 1",
        "1; 2",
        "round(1, 2, 3)",
        "x" * 600,
        "(" * 40 + "1" + ")" * 40,
    ],
)
def test_formula_refuses_anything_else(bad):
    with pytest.raises(Invalid):
        FX.check(bad, {"a": "number"})


def test_formula_cycles_refused():
    nodes = {"a": FX.parse("b + 1"), "b": FX.parse("c * 2"), "c": FX.parse("a")}
    with pytest.raises(Invalid, match="circle"):
        FX.order(nodes)
    assert FX.order({"a": FX.parse("b + 1"), "b": FX.parse("2")}) == ["b", "a"]


async def test_calculated_fields_on_leads_and_deals(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    assert (await _field(c, h, key="fee", label="Fee", type="number")).status_code == 201
    assert (
        await _field(c, h, key="scholarship", label="Scholarship", type="number")
    ).status_code == 201
    bad = await _field(c, h, key="net", label="Net", type="calculated", formula="fee - nope")
    assert bad.status_code == 422 and "nope" in bad.json()["detail"]
    r = await _field(
        c, h, key="net", label="Net", type="calculated", formula="fee - ifempty(scholarship, 0)"
    )
    assert r.status_code == 201, r.text
    net_id = r.json()["id"]
    # A circle is refused when the second field would close it.
    await _field(c, h, key="half", label="Half", type="calculated", formula="net / 2")
    r = await c.patch(f"/api/v1/custom-fields/{net_id}", json={"formula": "half * 2"}, headers=h)
    assert r.status_code == 422 and "circle" in r.json()["detail"]

    lead = await _lead(c, h, custom_fields={"fee": 80000, "scholarship": 15000})
    assert lead["custom_fields"]["net"] == 65000 and lead["custom_fields"]["half"] == 32500
    # Typing into a calculated field is refused; changing an input recalculates.
    r = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": lead["version"], "custom_fields": {"net": 1}},
        headers=h,
    )
    assert r.status_code == 422
    r = await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": lead["version"], "custom_fields": {"scholarship": None}},
        headers=h,
    )
    assert r.json()["custom_fields"]["net"] == 80000
    # A field a formula reads cannot be deleted.
    fields = {f["key"]: f["id"] for f in (await c.get("/api/v1/custom-fields", headers=h)).json()}
    assert (await c.delete(f"/api/v1/custom-fields/{fields['fee']}", headers=h)).status_code == 409

    # Deals: GST from the deal amount, exact, and updated when the amount changes.
    r = await _field(
        c,
        h,
        "deal",
        key="gst",
        label="GST",
        type="calculated",
        formula="round(amount * 18 / 100, 2)",
    )
    assert r.status_code == 201, r.text
    deal = (
        await c.post(
            "/api/v1/deals", json={"lead_id": lead["id"], "amount_minor": 99999}, headers=h
        )
    ).json()
    assert deal["custom_fields"]["gst"] == 180.0  # 999.99 × 18% = 179.9982 → 180.00
    deal = (
        await c.patch(
            f"/api/v1/deals/{deal['id']}",
            json={"version": deal["version"], "amount_minor": 1000000},
            headers=h,
        )
    ).json()
    assert deal["custom_fields"]["gst"] == 1800


# ---------- tags ----------
async def test_tags_on_leads_and_deals(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    a = await _lead(c, rep, "98765 00001")
    b = await _lead(c, rep, "98765 00002")
    r = await c.put(f"/api/v1/leads/{a['id']}/tags", json={"new": ["VIP", " vip "]}, headers=rep)
    assert r.status_code == 200 and [t["name"] for t in r.json()] == ["VIP"]
    vip = r.json()[0]["id"]
    # Bulk tag (creating "Scholarship"), filter, untag.
    r = await c.post(
        "/api/v1/leads/bulk",
        json={"action": "tag", "ids": [a["id"], b["id"]], "new_tags": ["Scholarship"]},
        headers=rep,
    )
    assert r.json()["done"] == 2
    page = (await c.get(f"/api/v1/leads?tag={vip}", headers=rep)).json()
    assert [x["id"] for x in page["items"]] == [a["id"]]
    assert {t["name"] for t in page["items"][0]["tags"]} == {"VIP", "Scholarship"}
    tags = {t["name"]: t for t in (await c.get("/api/v1/tags", headers=rep)).json()}
    assert tags["Scholarship"]["uses"] == 2
    # Only configurers tidy tags.
    url = f"/api/v1/tags/{vip}"
    assert (await c.patch(url, json={"name": "Gold"}, headers=rep)).status_code == 403
    r = await c.post(f"/api/v1/tags/{tags['Scholarship']['id']}/merge?into={vip}", headers=admin)
    assert r.status_code == 200 and r.json()["uses"] == 2
    acts = (await c.get(f"/api/v1/leads/{a['id']}/activities", headers=rep)).json()
    assert "tagged" in [x["type_key"] for x in acts]
    # Deals too.
    deal = (await c.post("/api/v1/deals", json={"lead_id": a["id"]}, headers=rep)).json()
    r = await c.put(f"/api/v1/deals/{deal['id']}/tags", json={"tag_ids": [vip]}, headers=rep)
    assert [t["name"] for t in r.json()] == ["VIP"]
    assert (await c.get(f"/api/v1/deals?tag={vip}", headers=rep)).json()["total"] == 1
    assert (await c.delete(url, headers=admin)).status_code == 204
    assert (await c.get(f"/api/v1/leads/{a['id']}", headers=rep)).json()["tags"] == []


# ---------- saved views ----------
async def test_views_private_team_everyone(ws):
    tenant_id, c = ws
    mgr_id, mgr = await login_as(tenant_id, "sales_manager")
    a_id, rep_a = await login_as(tenant_id, "sales_user")
    _, rep_b = await login_as(tenant_id, "sales_user")
    _, admin = await login_as(tenant_id, "admin")
    team = await make_team(tenant_id, mgr_id, [a_id])
    body = {"entity": "leads", "name": "Hot Pune", "filters": {"band": ["hot"], "status": "open"}}
    mine = (await c.post("/api/v1/views", json=body, headers=rep_a)).json()
    assert mine["filters"] == {"band": ["hot"], "status": "open"} and mine["mine"]
    assert (await c.get("/api/v1/views?entity=leads", headers=rep_b)).json() == []
    patch = {"name": "x"}
    assert (
        await c.patch(f"/api/v1/views/{mine['id']}", json=patch, headers=rep_b)
    ).status_code == 403
    # Team views: team managers only; everyone: configurers only.
    shared = body | {"name": "Team hot", "sharing": "team", "team_id": str(team)}
    assert (await c.post("/api/v1/views", json=shared, headers=rep_a)).status_code == 403
    assert (await c.post("/api/v1/views", json=shared, headers=mgr)).status_code == 201
    names = [v["name"] for v in (await c.get("/api/v1/views?entity=leads", headers=rep_a)).json()]
    assert names == ["Hot Pune", "Team hot"]
    assert [
        v["name"] for v in (await c.get("/api/v1/views?entity=leads", headers=rep_b)).json()
    ] == []
    every = body | {"name": "All hot", "sharing": "everyone"}
    assert (await c.post("/api/v1/views", json=every, headers=mgr)).status_code == 403
    assert (await c.post("/api/v1/views", json=every, headers=admin)).status_code == 201
    assert "All hot" in [
        v["name"] for v in (await c.get("/api/v1/views?entity=leads", headers=rep_b)).json()
    ]
    bad = body | {"filters": {"band": ["boiling"]}}
    assert (await c.post("/api/v1/views", json=bad, headers=rep_a)).status_code == 422


# ---------- scoring ----------
async def test_fit_and_engagement_scoring_with_bands(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin)
    rule = {
        "kind": "fit",
        "condition": {"field": "source_id", "op": "is", "value": sources["Website"]},
        "points": 10,
    }
    assert (await c.post("/api/v1/score-rules", json=rule, headers=admin)).status_code == 201
    assert (await c.post("/api/v1/score-rules", json=rule, headers=rep)).status_code == 403
    selfref = {"kind": "fit", "condition": {"field": "score", "op": "gt", "value": 1}, "points": 1}
    assert (await c.post("/api/v1/score-rules", json=selfref, headers=admin)).status_code == 422
    eng = {
        "kind": "engagement",
        "activity_type_key": "call",
        "disposition": "interested",
        "points": 15,
    }
    assert (await c.post("/api/v1/score-rules", json=eng, headers=admin)).status_code == 201
    await c.put(
        "/api/v1/score-settings",
        json={"engagement_days": 30, "hot_score": 40, "warm_score": 20},
        headers=admin,
    )

    lead = await _lead(c, rep)
    assert (lead["score"], lead["fit_score"], lead["score_band"]) == (10, 10, "cold")
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    for _ in range(2):
        r = await c.post(
            f"/api/v1/leads/{lead['id']}/activities",
            headers=rep,
            json={
                "type_key": "call",
                "data": {"disposition": "interested"},
                "next_follow_up_at": future,
            },
        )
        assert r.status_code == 201, r.text
    after = r.json()["lead"]
    assert (after["score"], after["engagement_score"], after["score_band"]) == (40, 30, "hot")
    br = (await c.get(f"/api/v1/leads/{lead['id']}/score", headers=rep)).json()
    assert (br["fit"], br["engagement"]) == (10, 30)
    assert any("× 2" in line["label"] for line in br["lines"])
    hot = (await c.get("/api/v1/leads?band=hot", headers=rep)).json()
    assert [x["id"] for x in hot["items"]] == [lead["id"]]
    # Old activity drops out of the window at the nightly re-score.
    async with tenant_session(tenant_id) as db:
        await db.execute(
            update(Activity)
            .where(Activity.lead_id == lead["id"])
            .values(occurred_at=datetime.now(UTC) - timedelta(days=40))
        )
    await rescore_tenant(tenant_id)
    again = (await c.get(f"/api/v1/leads/{lead['id']}", headers=rep)).json()
    assert (again["score"], again["score_band"]) == (10, "cold")


# ---------- automation ----------
async def _auto(c, h, **body):
    r = await c.post("/api/v1/automations", json={"name": "Auto", **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def test_new_website_lead_gets_task_tag_and_note(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin)
    vip = (await c.post("/api/v1/tags", json={"name": "Web"}, headers=admin)).json()
    body = {
        "trigger": {"type": "lead.created"},
        "conditions": [{"field": "source_id", "op": "is", "value": sources["Website"]}],
        "actions": [
            {"type": "create_task", "title": "Call within the hour", "due_hours": 1},
            {"type": "add_tag", "tag_id": vip["id"]},
            {"type": "notify", "to": "owner", "message": "New web lead"},
        ],
    }
    assert (
        await c.post("/api/v1/automations", json={"name": "x", **body}, headers=rep)
    ).status_code == 403
    auto = await _auto(c, admin, **body)
    web = await _lead(c, rep, "98765 10001")
    other = await _lead(
        c,
        rep,
        "98765 10002",
        source="Walk-in" if "Walk-in" in sources else next(s for s in sources if s != "Website"),
    )
    assert await A.process_tenant(tenant_id) == 1
    async with tenant_session(tenant_id) as db:
        tasks = (await db.scalars(select(Task).where(Task.created_from == "automation"))).all()
        assert [(str(t.lead_id), t.owner_user_id) for t in tasks] == [(web["id"], rep_id)]
    assert [
        t["name"] for t in (await c.get(f"/api/v1/leads/{web['id']}", headers=rep)).json()["tags"]
    ] == ["Web"]
    assert (await c.get(f"/api/v1/leads/{other['id']}", headers=rep)).json()["tags"] == []
    acts = (await c.get(f"/api/v1/leads/{web['id']}/activities", headers=rep)).json()
    tagged = next(a for a in acts if a["type_key"] == "tagged")
    assert tagged["actor_type"] == "automation" and tagged["data"]["automation"] == "Auto"
    runs = (await c.get(f"/api/v1/automations/{auto['id']}/runs", headers=admin)).json()
    assert [r["status"] for r in runs] == ["done"] and len(runs[0]["detail"]) == 3
    # Each event runs once.
    assert await A.process_tenant(tenant_id) == 0
    test = (
        await c.post(f"/api/v1/automations/{auto['id']}/test?lead_id={other['id']}", headers=admin)
    ).json()
    assert test["matches"] is False


async def test_a_failing_action_rolls_back_the_run_and_switches_off(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    stages, _ = await setup_ids(c, admin)
    gated = next(s for s in stages.values() if s["is_open"] and not s["is_unqualified"])
    await _field(c, admin, key="intake", label="Intake", type="text")
    other = [s for s in stages.values() if s["is_open"] and s["id"] != gated["id"]][-1]
    await c.patch(
        f"/api/v1/lead-stages/{other['id']}", json={"required_fields": ["intake"]}, headers=admin
    )
    tag = (await c.post("/api/v1/tags", json={"name": "Moved"}, headers=admin)).json()
    auto = await _auto(
        c,
        admin,
        trigger={"type": "lead.created"},
        actions=[
            {"type": "add_tag", "tag_id": tag["id"]},
            {"type": "change_stage", "stage_id": other["id"]},
        ],
    )
    async with tenant_session(tenant_id) as db:
        await db.execute(update(Automation).values(failures_in_row=A.MAX_FAILURES - 1))
    lead = await _lead(c, admin)
    await A.process_tenant(tenant_id)
    runs = (await c.get(f"/api/v1/automations/{auto['id']}/runs", headers=admin)).json()
    assert runs[0]["status"] == "failed" and "Intake" in runs[0]["error"]
    assert (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()["tags"] == []
    state = (await c.get(f"/api/v1/automations/{auto['id']}", headers=admin)).json()
    assert state["is_active"] is False
    notes = (await c.get("/api/v1/notifications", headers=admin)).json()
    assert any("switched off" in n["title"] for n in notes["items"])


async def test_loop_guard_and_chains(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await _field(c, admin, key="note_a", label="A", type="text")
    await _field(c, admin, key="note_b", label="B", type="text")
    # A sets B when A changes; B sets A when B changes: a loop that must stop.
    await _auto(
        c,
        admin,
        name="A→B",
        trigger={"type": "lead.field_changed", "field": "note_a"},
        actions=[{"type": "update_field", "field": "note_b", "value": "from A"}],
    )
    await _auto(
        c,
        admin,
        name="B→A",
        trigger={"type": "lead.field_changed", "field": "note_b"},
        actions=[{"type": "update_field", "field": "note_a", "value": "from B"}],
    )
    lead = await _lead(c, admin)
    await c.patch(
        f"/api/v1/leads/{lead['id']}",
        json={"version": lead["version"], "custom_fields": {"note_a": "typed"}},
        headers=admin,
    )
    total = 0
    for _ in range(6):
        total += await A.process_tenant(tenant_id)
    assert total == 2  # A→B, then B→A; A is in the chain so it stops
    final = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()["custom_fields"]
    assert final == {"note_a": "from B", "note_b": "from A"}


async def test_deal_won_and_no_response_triggers(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    await _field(c, admin, "deal", key="handover", label="Handover", type="text")
    await _auto(
        c,
        admin,
        trigger={"type": "deal.won"},
        actions=[{"type": "update_field", "field": "handover", "value": "Send welcome kit"}],
    )
    nr = await _auto(
        c,
        admin,
        name="Nobody called",
        trigger={"type": "lead.no_response", "hours": 2},
        actions=[{"type": "notify", "to": "managers", "message": "Nobody called yet"}],
    )
    lead = await _lead(c, admin)
    deal = (await c.post("/api/v1/deals", json={"lead_id": lead["id"]}, headers=admin)).json()
    stages = (await c.get("/api/v1/pipelines", headers=admin)).json()[0]["stages"]
    won = next(s for s in stages if s["kind"] == "won")
    await c.post(
        f"/api/v1/deals/{deal['id']}/move",
        json={"version": deal["version"], "stage_id": won["id"]},
        headers=admin,
    )
    await A.process_tenant(tenant_id)
    got = (await c.get(f"/api/v1/deals/{deal['id']}", headers=admin)).json()
    assert got["custom_fields"]["handover"] == "Send welcome kit"
    # No response: only once the hours have passed, and only once per lead.
    assert await A.no_response_tenant(tenant_id) == 0
    async with tenant_session(tenant_id) as db:
        await db.execute(update(Lead).values(created_at=datetime.now(UTC) - timedelta(hours=3)))
        await db.execute(
            update(Automation).values(created_at=datetime.now(UTC) - timedelta(days=1))
        )
    assert await A.no_response_tenant(tenant_id) == 1
    assert await A.no_response_tenant(tenant_id) == 0
    runs = (await c.get(f"/api/v1/automations/{nr['id']}/runs", headers=admin)).json()
    assert len(runs) == 1


async def test_definitions_are_checked(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    bad = [
        {"trigger": {"type": "nope"}, "actions": [{"type": "notify", "message": "x"}]},
        {"trigger": {"type": "lead.created"}, "actions": []},
        {"trigger": {"type": "lead.created"}, "actions": [{"type": "explode"}]},
        {
            "trigger": {"type": "lead.created"},
            "conditions": [{"field": "nope", "op": "is", "value": 1}],
            "actions": [{"type": "notify", "message": "x"}],
        },
        {
            "trigger": {"type": "lead.no_response", "hours": 0},
            "actions": [{"type": "notify", "message": "x"}],
        },
        {
            "trigger": {"type": "deal.won"},
            "actions": [{"type": "change_owner", "user_id": "rules"}],
        },
    ]
    for body in bad:
        r = await c.post("/api/v1/automations", json={"name": "x", **body}, headers=admin)
        assert r.status_code == 422, body
    for url in (
        "http://example.com/hook",
        "https://localhost/x",
        "https://10.0.0.5/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest",
    ):
        with pytest.raises(Invalid):
            A.check_url(url)
    assert A.sign("s", 1, "{}") == A.sign("s", 1, "{}") != A.sign("t", 1, "{}")


async def test_automations_stay_in_their_company(client_for):
    t1, s1 = await make_workspace()
    t2, s2 = await make_workspace()
    c1, c2 = client_for(s1), client_for(s2)
    _, h1 = await login_as(t1, "admin")
    _, h2 = await login_as(t2, "admin")
    tag = (await c1.post("/api/v1/tags", json={"name": "Only here"}, headers=h1)).json()
    auto = await _auto(
        c1, h1, trigger={"type": "lead.created"}, actions=[{"type": "add_tag", "tag_id": tag["id"]}]
    )
    await _lead(c2, h2)
    assert await A.process_tenant(t2) == 0
    assert await A.process_tenant(t1) == 0
    assert (await c2.get(f"/api/v1/automations/{auto['id']}", headers=h2)).status_code == 404
    assert (await c2.get("/api/v1/tags", headers=h2)).json() == []
    other = await _auto(
        c2, h2, trigger={"type": "lead.created"}, actions=[{"type": "notify", "message": "hi"}]
    )
    r = await c2.patch(
        f"/api/v1/automations/{other['id']}",
        headers=h2,
        json={"actions": [{"type": "add_tag", "tag_id": tag["id"]}]},
    )
    assert r.status_code == 422
    async with tenant_session(t2) as db:
        assert (await db.scalars(select(AutomationRun))).all() == []


def test_this_machine_is_a_webhook_target_only_on_a_developers_machine(monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    local = (
        "http://localhost:8787/hooks",
        "http://127.0.0.1:9000/x",
        "http://host.docker.internal/x",
    )
    monkeypatch.setattr(s, "environment", "dev")
    for url in local:
        assert A.check_url(url) == url
    with pytest.raises(Invalid):
        A.check_url("http://10.0.0.5/x")  # other private addresses: still refused in dev
    for env in ("test", "prod"):
        monkeypatch.setattr(s, "environment", env)
        for url in local:
            with pytest.raises(Invalid):
                A.check_url(url)

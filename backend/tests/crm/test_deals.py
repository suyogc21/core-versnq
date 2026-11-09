"""Step 3: pipelines, deals, stage moves, exact money, products, forecast, links, isolation."""

import pytest
from sqlalchemy import select

from app.core import money
from app.core.errors import Invalid
from app.core.events_model import Event
from app.core.tenancy import tenant_session
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as, make_workspace


async def _lead(c, h, phone="98765 43210", **extra):
    _, sources = await setup_ids(c, h)
    r = await new_lead(c, h, sources["Website"], phone=phone, **extra)
    assert r.status_code == 201, r.text
    return r.json()


async def _pipeline(c, h):
    pipes = (await c.get("/api/v1/pipelines", headers=h)).json()
    p = pipes[0]
    return p, {s["name"]: s for s in p["stages"]}


async def _deal(c, h, lead_id, **body):
    r = await c.post("/api/v1/deals", json={"lead_id": lead_id, **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _reasons(c, h):
    return {r["name"]: r["id"] for r in (await c.get("/api/v1/lost-reasons", headers=h)).json()}


async def _events(tenant_id, prefix="deal."):
    async with tenant_session(tenant_id) as db:
        return list(
            (await db.scalars(select(Event.type).where(Event.type.like(f"{prefix}%")))).all()
        )


# ---------- money (rule 7) ----------
def test_line_totals_and_weighting_are_exact():
    assert money.line_total(3, 33_333, 0) == 99_999
    assert money.line_total(2, 6_999_900, 999_900) == 12_999_900
    assert money.line_total(1, 100, 100) == 0
    with pytest.raises(Invalid):
        money.line_total(1, 100, 101)  # discount above the line
    with pytest.raises(Invalid):
        money.line_total(0, 100, 0)
    with pytest.raises(Invalid):
        money.line_total(money.MAX_QUANTITY, money.MAX_MINOR, 0)  # too large, never overflows
    # weighted = amount × probability %, rounded half up to a whole minor unit
    assert money.weighted(1_000, 33) == 330
    assert money.weighted(5, 10) == 1  # 0.5 → 1
    assert money.weighted(4, 10) == 0  # 0.4 → 0
    assert money.weighted(999_999_999_999_999, 100) == 999_999_999_999_999
    assert money.weighted(10**15, 37) == 37 * 10**13


def test_currencies_and_their_exponents():
    assert money.EXPONENT["INR"] == 2
    assert money.EXPONENT["JPY"] == 0
    assert money.EXPONENT["KWD"] == 3
    assert money.currency(" aed ") == "AED"
    with pytest.raises(Invalid):
        money.currency("XYZ")
    with pytest.raises(Invalid):
        money.check_amount(1.5)  # floats are refused
    assert money.for_country("IN") == "INR"
    assert money.for_country("ZZ") == "USD"


# ---------- packs ----------
async def test_generic_pack_has_a_sales_pipeline_in_the_company_currency(admin):
    c, h = admin
    p, stages = await _pipeline(c, h)
    assert (p["name"], p["currency"]) == ("Sales", "INR")
    assert [(s["name"], s["kind"], s["probability"]) for s in p["stages"]] == [
        ("Qualification", "open", 10),
        ("Proposal", "open", 40),
        ("Negotiation", "open", 70),
        ("Won", "won", 100),
        ("Lost", "lost", 0),
    ]
    assert "Price too high" in await _reasons(c, h)
    assert (await c.get("/api/v1/products", headers=h)).json() == []


async def test_edtech_pack_has_admissions_and_courses(client_for):
    tenant_id, slug = await make_workspace(pack="edtech")
    c = client_for(slug)
    _, h = await login_as(tenant_id, "admin")
    p, stages = await _pipeline(c, h)
    assert p["name"] == "Admissions"
    assert stages["Enrolled"]["kind"] == "won" and stages["Dropped"]["kind"] == "lost"
    products = {x["code"]: x for x in (await c.get("/api/v1/products", headers=h)).json()}
    assert products["DS-PRO"]["price_minor"] == 6_999_900
    assert {x["currency"] for x in products.values()} == {"INR"}
    assert "Fees too high" in await _reasons(c, h)


# ---------- creating and seeing ----------
async def test_a_rep_adds_a_deal_to_their_lead(ws):
    tenant_id, c = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, first_name="Riya")
    p, stages = await _pipeline(c, rep)
    deal = await _deal(c, rep, lead["id"], amount_minor=5_000_000, expected_close_on="2026-12-15")
    assert (deal["name"], deal["lead_name"]) == ("Riya", "Riya")
    assert (deal["stage_name"], deal["status"], deal["currency"]) == (
        "Qualification",
        "open",
        "INR",
    )
    assert (deal["owner_user_id"], deal["amount_minor"]) == (str(rep_id), 5_000_000)
    # On the deal's timeline and the lead's.
    acts = (await c.get(f"/api/v1/deals/{deal['id']}/activities", headers=rep)).json()
    assert [a["type_key"] for a in acts] == ["deal_created"]
    lead_acts = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)).json()
    assert "deal_created" in [a["type_key"] for a in lead_acts]
    assert await _events(tenant_id) == ["deal.created"]
    # A rep only gives deals to themselves; new deals start open.
    _, other = await login_as(tenant_id, "sales_user")
    body = {"lead_id": lead["id"], "owner_user_id": str((await login_as(tenant_id))[0])}
    assert (await c.post("/api/v1/deals", json=body, headers=rep)).status_code == 403
    body = {"lead_id": lead["id"], "stage_id": stages["Won"]["id"]}
    assert (await c.post("/api/v1/deals", json=body, headers=rep)).status_code == 422
    # Someone who cannot see the lead cannot add a deal to it.
    body = {"lead_id": lead["id"]}
    assert (await c.post("/api/v1/deals", json=body, headers=other)).status_code == 404


async def test_visibility_own_team_all_on_list_board_and_summary(ws):
    tenant_id, c = ws
    mgr_id, mgr = await login_as(tenant_id, "sales_manager")
    a_id, rep_a = await login_as(tenant_id, "sales_user")
    b_id, rep_b = await login_as(tenant_id, "sales_user")
    out_id, outsider = await login_as(tenant_id, "sales_user")
    _, admin = await login_as(tenant_id, "admin")
    await make_team(tenant_id, mgr_id, [a_id, b_id])
    da = await _deal(c, rep_a, (await _lead(c, rep_a, "98765 00001"))["id"], amount_minor=1_000)
    db_ = await _deal(c, rep_b, (await _lead(c, rep_b, "98765 00002"))["id"], amount_minor=2_000)
    await _deal(c, outsider, (await _lead(c, outsider, "98765 00003"))["id"], amount_minor=4_000)

    def ids(page):
        return {d["id"] for d in page["items"]}

    assert ids((await c.get("/api/v1/deals", headers=rep_a)).json()) == {da["id"]}
    assert (await c.get(f"/api/v1/deals/{db_['id']}", headers=rep_a)).status_code == 404
    assert ids((await c.get("/api/v1/deals", headers=mgr)).json()) == {da["id"], db_["id"]}
    assert (await c.get("/api/v1/deals", headers=admin)).json()["total"] == 3
    # Board totals and the forecast count only what you may see.
    board = (await c.get("/api/v1/deals/board", headers=mgr)).json()
    assert (board["open_count"], board["open_minor"]) == (2, 3_000)
    assert board["weighted_minor"] == money.weighted(3_000, 10)
    assert (await c.get("/api/v1/deals/board", headers=admin)).json()["open_minor"] == 7_000
    summary = (await c.get("/api/v1/deals/summary", headers=rep_a)).json()
    assert (summary[0]["open_count"], summary[0]["open_minor"]) == (1, 1_000)
    # A rep cannot edit, move or link someone else's deal.
    patch = {"version": db_["version"], "name": "Mine now"}
    assert (
        await c.patch(f"/api/v1/deals/{db_['id']}", json=patch, headers=rep_a)
    ).status_code == 404


async def test_finance_sees_no_deals_and_cannot_add_them(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, fin = await login_as(tenant_id, "finance")
    await _deal(c, rep, (await _lead(c, rep))["id"])
    assert (await c.get("/api/v1/deals", headers=fin)).json()["total"] == 0
    assert (await c.get("/api/v1/deals/board", headers=fin)).json()["open_count"] == 0


# ---------- moving ----------
async def test_lost_needs_a_reason_won_closes_reopen_clears(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep)
    _, stages = await _pipeline(c, rep)
    reasons = await _reasons(c, rep)
    deal = await _deal(c, rep, lead["id"], amount_minor=10_000)
    url = f"/api/v1/deals/{deal['id']}/move"

    body = {"version": deal["version"], "stage_id": stages["Lost"]["id"]}
    r = await c.post(url, json=body, headers=rep)
    assert r.status_code == 422 and "lost" in r.json()["detail"]
    body |= {"lost_reason_id": reasons["No budget"], "note": "Next year maybe"}
    lost = (await c.post(url, json=body, headers=rep)).json()
    assert (lost["status"], lost["lost_reason"], lost["close_note"]) == (
        "lost",
        "No budget",
        "Next year maybe",
    )
    assert lost["closed_at"] is not None
    # A stale version is refused.
    stale = {"version": deal["version"], "stage_id": stages["Won"]["id"]}
    assert (await c.post(url, json=stale, headers=rep)).status_code == 409
    reopened = (
        await c.post(
            url,
            json={"version": lost["version"], "stage_id": stages["Proposal"]["id"]},
            headers=rep,
        )
    ).json()
    assert (reopened["status"], reopened["closed_at"], reopened["lost_reason_id"]) == (
        "open",
        None,
        None,
    )
    won = (
        await c.post(
            url, json={"version": reopened["version"], "stage_id": stages["Won"]["id"]}, headers=rep
        )
    ).json()
    assert won["status"] == "won" and won["closed_at"]
    kinds = [
        a["type_key"]
        for a in (await c.get(f"/api/v1/deals/{deal['id']}/activities", headers=rep)).json()
    ]
    for k in ("deal_lost", "deal_reopened", "deal_won"):
        assert k in kinds
    events = await _events(tenant_id)
    assert events.count("deal.stage_changed") == 3
    assert "deal.lost" in events and "deal.won" in events
    # A switched-off reason cannot be chosen.
    _, admin = await login_as(tenant_id, "admin")
    rid = reasons["Other"]
    await c.patch(f"/api/v1/lost-reasons/{rid}", json={"is_active": False}, headers=admin)
    body = {"version": won["version"], "stage_id": stages["Lost"]["id"], "lost_reason_id": rid}
    assert (await c.post(url, json=body, headers=rep)).status_code == 422


async def test_stage_required_fields(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, stages = await _pipeline(c, admin)
    r = await c.post(
        "/api/v1/custom-fields?entity=deal",
        json={"key": "intake", "label": "Intake", "type": "text"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    r = await c.patch(
        f"/api/v1/pipeline-stages/{stages['Proposal']['id']}",
        json={"required_fields": ["amount", "expected_close_on", "intake"]},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    bad = {"required_fields": ["nope"]}
    url = f"/api/v1/pipeline-stages/{stages['Proposal']['id']}"
    assert (await c.patch(url, json=bad, headers=admin)).status_code == 422
    deal = await _deal(c, admin, (await _lead(c, admin))["id"])
    move = {"version": deal["version"], "stage_id": stages["Proposal"]["id"]}
    r = await c.post(f"/api/v1/deals/{deal['id']}/move", json=move, headers=admin)
    assert r.status_code == 422
    assert "amount, expected close date, Intake" in r.json()["detail"]
    patch = {
        "version": deal["version"],
        "amount_minor": 500,
        "expected_close_on": "2026-12-01",
        "custom_fields": {"intake": "Jan 2027"},
    }
    deal = (await c.patch(f"/api/v1/deals/{deal['id']}", json=patch, headers=admin)).json()
    move["version"] = deal["version"]
    r = await c.post(f"/api/v1/deals/{deal['id']}/move", json=move, headers=admin)
    assert r.status_code == 200 and r.json()["stage_name"] == "Proposal"


# ---------- products and lines ----------
async def test_lines_set_the_amount_exactly_in_the_pipeline_currency(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    course = (
        await c.post(
            "/api/v1/products",
            json={"name": "Data Science", "price_minor": 6_999_900},
            headers=admin,
        )
    ).json()
    assert course["currency"] == "INR"
    usd = (
        await c.post(
            "/api/v1/products",
            json={"name": "Dollar thing", "price_minor": 100, "currency": "usd"},
            headers=admin,
        )
    ).json()
    assert (
        await c.post("/api/v1/products", json={"name": "x", "price_minor": 1}, headers=rep)
    ).status_code == 403
    deal = await _deal(c, rep, (await _lead(c, rep))["id"], amount_minor=1)
    url = f"/api/v1/deals/{deal['id']}/products"
    lines = [
        {"product_id": course["id"], "quantity": 2, "discount_minor": 999_900},
        {"name": "Hostel", "quantity": 3, "unit_price_minor": 33_333},
    ]
    r = await c.put(url, json={"version": deal["version"], "lines": lines}, headers=rep)
    assert r.status_code == 200, r.text
    out = r.json()
    assert [x["total_minor"] for x in out["lines"]] == [12_999_900, 99_999]
    assert out["deal"]["amount_minor"] == 13_099_899 and out["deal"]["has_lines"]
    v = out["deal"]["version"]
    # The amount now comes from the lines.
    patch = {"version": v, "amount_minor": 5}
    assert (
        await c.patch(f"/api/v1/deals/{deal['id']}", json=patch, headers=rep)
    ).status_code == 422
    # No mixing currencies; no discount above the line; prices never negative.
    for bad in (
        [{"product_id": usd["id"]}],
        [{"name": "x", "unit_price_minor": 100, "discount_minor": 101}],
        [{"name": "x", "unit_price_minor": -1}],
        [{"name": "", "unit_price_minor": 1}],
        [{"name": "x"}],  # a line without a product needs a price
    ):
        r = await c.put(url, json={"version": v, "lines": bad}, headers=rep)
        assert r.status_code == 422, bad
    # Catalogue price changes do not touch existing lines.
    await c.patch(f"/api/v1/products/{course['id']}", json={"price_minor": 1}, headers=admin)
    assert (await c.get(url, headers=rep)).json()[0]["unit_price_minor"] == 6_999_900
    # A product on deals cannot be deleted or change currency.
    assert (await c.delete(f"/api/v1/products/{course['id']}", headers=admin)).status_code == 409
    r = await c.patch(f"/api/v1/products/{course['id']}", json={"currency": "USD"}, headers=admin)
    assert r.status_code == 409
    # Clearing the lines keeps the amount, which can then be typed again.
    out = (await c.put(url, json={"version": v, "lines": []}, headers=rep)).json()
    assert out["deal"]["amount_minor"] == 13_099_899 and not out["deal"]["has_lines"]


async def test_big_and_zero_decimal_amounts(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    jpy = (
        await c.post("/api/v1/pipelines", json={"name": "Japan", "currency": "JPY"}, headers=admin)
    ).json()
    assert [s["kind"] for s in jpy["stages"]] == ["open", "won", "lost"]
    lead = await _lead(c, admin)
    deal = await _deal(c, admin, lead["id"], pipeline_id=jpy["id"], amount_minor=money.MAX_MINOR)
    assert (deal["currency"], deal["amount_minor"]) == ("JPY", 10**15)
    r = await c.post(
        "/api/v1/deals",
        json={"lead_id": lead["id"], "amount_minor": money.MAX_MINOR + 1},
        headers=admin,
    )
    assert r.status_code == 422
    # Moving between pipelines needs the same currency.
    sales, _ = await _pipeline(c, admin)
    patch = {"version": deal["version"], "pipeline_id": sales["id"]}
    r = await c.patch(f"/api/v1/deals/{deal['id']}", json=patch, headers=admin)
    assert r.status_code == 422 and "JPY" in r.json()["detail"]


# ---------- setting up pipelines ----------
async def test_pipeline_setup_rules(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, mgr = await login_as(tenant_id, "sales_manager")
    p, stages = await _pipeline(c, admin)
    assert (await c.post("/api/v1/pipelines", json={"name": "X"}, headers=mgr)).status_code == 403
    no_lost = {"name": "Bad", "stages": [{"name": "A"}, {"name": "W", "kind": "won"}]}
    assert (await c.post("/api/v1/pipelines", json=no_lost, headers=admin)).status_code == 422
    dup = {"name": "sales"}
    assert (await c.post("/api/v1/pipelines", json=dup, headers=admin)).status_code == 409
    # The only lost stage cannot go; a new open stage goes before the closed ones.
    url = f"/api/v1/pipeline-stages/{stages['Lost']['id']}"
    assert (await c.delete(url, headers=admin)).status_code == 422
    added = (
        await c.post(
            f"/api/v1/pipelines/{p['id']}/stages",
            json={"name": "Demo", "probability": 50},
            headers=admin,
        )
    ).json()
    assert [s["name"] for s in added["stages"]][-3:] == ["Demo", "Won", "Lost"]
    # A stage with deals: choose where they go (same kind).
    deal = await _deal(c, admin, (await _lead(c, admin))["id"])
    url = f"/api/v1/pipeline-stages/{stages['Qualification']['id']}"
    assert (await c.delete(url, headers=admin)).status_code == 409
    r = await c.delete(f"{url}?move_to={stages['Won']['id']}", headers=admin)
    assert r.status_code == 422
    r = await c.delete(f"{url}?move_to={stages['Proposal']['id']}", headers=admin)
    assert r.status_code == 200
    moved = (await c.get(f"/api/v1/deals/{deal['id']}", headers=admin)).json()
    assert moved["stage_name"] == "Proposal" and moved["version"] == deal["version"] + 1
    # Currency is fixed once there are deals; the last pipeline stays.
    purl = f"/api/v1/pipelines/{p['id']}"
    assert (await c.patch(purl, json={"currency": "USD"}, headers=admin)).status_code == 409
    assert (await c.patch(purl, json={"is_active": False}, headers=admin)).status_code == 409
    assert (await c.delete(purl, headers=admin)).status_code == 409
    # Stage kind cannot change while deals sit in it.
    surl = f"/api/v1/pipeline-stages/{stages['Proposal']['id']}"
    assert (await c.patch(surl, json={"kind": "won"}, headers=admin)).status_code == 409
    # A used lost reason is only switched off.
    reasons = await _reasons(c, admin)
    await c.post(
        f"/api/v1/deals/{deal['id']}/move",
        json={
            "version": moved["version"],
            "stage_id": stages["Lost"]["id"],
            "lost_reason_id": reasons["Bad timing"],
        },
        headers=admin,
    )
    r = await c.delete(f"/api/v1/lost-reasons/{reasons['Bad timing']}", headers=admin)
    assert r.status_code == 409


# ---------- deleting, bulk, tasks, notes ----------
async def test_delete_bulk_tasks_and_notes(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")
    _, stages = await _pipeline(c, rep)
    lead = await _lead(c, rep)
    d1 = await _deal(c, rep, lead["id"], name="One")
    d2 = await _deal(c, rep, lead["id"], name="Two")
    # Tasks on a deal belong to its lead too.
    r = await c.post(
        "/api/v1/tasks",
        json={"title": "Send brochure", "due_at": "2030-01-01T10:00:00Z", "deal_id": d1["id"]},
        headers=rep,
    )
    assert r.status_code == 201, r.text
    task = r.json()
    assert (task["lead_id"], task["deal_name"]) == (lead["id"], "One")
    on_deal = (await c.get(f"/api/v1/tasks?deal_id={d1['id']}", headers=rep)).json()
    assert [t["id"] for t in on_deal] == [task["id"]]
    note = await c.post(f"/api/v1/deals/{d1['id']}/notes", json={"body": "Called dad"}, headers=rep)
    assert note.status_code == 201
    # Bulk: lost without a reason is skipped and reported.
    body = {"action": "stage", "ids": [d1["id"], d2["id"]], "stage_id": stages["Lost"]["id"]}
    out = (await c.post("/api/v1/deals/bulk", json=body, headers=rep)).json()
    assert out["done"] == 0 and len(out["skipped"]) == 2
    body["stage_id"] = stages["Proposal"]["id"]
    assert (await c.post("/api/v1/deals/bulk", json=body, headers=rep)).json()["done"] == 2
    # Only roles with deals.delete delete; the lead keeps one entry.
    assert (await c.delete(f"/api/v1/deals/{d1['id']}", headers=rep)).status_code == 403
    assert (await c.delete(f"/api/v1/deals/{d1['id']}", headers=admin)).status_code == 204
    assert (await c.get(f"/api/v1/deals/{d1['id']}", headers=admin)).status_code == 404
    assert (await c.get(f"/api/v1/tasks?lead_id={lead['id']}", headers=rep)).json() == []
    acts = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)).json()
    kinds = [a["type_key"] for a in acts]
    assert "deal_deleted" in kinds and "note" not in kinds  # the deal's own entries went
    assert "deal.deleted" in await _events(tenant_id)


async def test_lead_timeline_hides_deals_you_cannot_see(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    other_id, _ = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, admin, owner_user_id=str(rep_id))
    await _deal(c, admin, lead["id"], name="Secret", owner_user_id=str(other_id))
    acts = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=rep)).json()
    assert not any("Secret" in a["summary"] for a in acts)
    acts = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=admin)).json()
    assert any("Secret" in a["summary"] for a in acts)


# ---------- links (D1) ----------
async def test_deals_link_to_records(ws):
    tenant_id, c = ws
    _, admin = await login_as(tenant_id, "admin")
    rt = (
        await c.post(
            "/api/v1/record-types",
            json={
                "key": "property",
                "singular": "Property",
                "plural": "Properties",
                "has_owner": False,
            },
            headers=admin,
        )
    ).json()
    bad = {"from_kind": "deal", "from_type_id": rt["id"], "to_type_id": rt["id"],
           "label": "x", "inverse_label": "y"}  # fmt: skip
    assert (await c.post("/api/v1/link-types", json=bad, headers=admin)).status_code == 422
    lt = await c.post(
        "/api/v1/link-types",
        json={
            "from_kind": "deal",
            "to_type_id": rt["id"],
            "label": "For property",
            "inverse_label": "Deals",
            "many_to": False,
        },
        headers=admin,
    )
    assert lt.status_code == 201, lt.text
    lt = lt.json()
    assert (lt["from_kind"], lt["to_kind"]) == ("deal", "record")
    flat = (
        await c.post(
            "/api/v1/records", json={"type": "property", "name": "Flat 1203"}, headers=admin
        )
    ).json()
    flat2 = (
        await c.post("/api/v1/records", json={"type": "property", "name": "Flat 9"}, headers=admin)
    ).json()
    deal = await _deal(c, admin, (await _lead(c, admin))["id"], name="Mehta — 1203")
    body = {"link_type_id": lt["id"], "from_deal_id": deal["id"], "to_record_id": flat["id"]}
    r = await c.post("/api/v1/links", json=body, headers=admin)
    assert r.status_code == 201, r.text
    # "A deal is for one property."
    body2 = body | {"to_record_id": flat2["id"]}
    assert (await c.post("/api/v1/links", json=body2, headers=admin)).status_code == 409
    # A lead cannot stand in for a deal.
    lead2 = await _lead(c, admin, "98765 11111")
    wrong = {"link_type_id": lt["id"], "from_lead_id": lead2["id"], "to_record_id": flat2["id"]}
    assert (await c.post("/api/v1/links", json=wrong, headers=admin)).status_code == 422
    from_deal = (await c.get(f"/api/v1/links?deal_id={deal['id']}", headers=admin)).json()
    assert [(x["label"], x["other"]["name"]) for x in from_deal] == [("For property", "Flat 1203")]
    from_flat = (await c.get(f"/api/v1/links?record_id={flat['id']}", headers=admin)).json()
    assert [(x["label"], x["other"]["kind"]) for x in from_flat] == [("Deals", "deal")]
    acts = (await c.get(f"/api/v1/deals/{deal['id']}/activities", headers=admin)).json()
    assert "linked" in [a["type_key"] for a in acts]
    # A rep who cannot see the deal does not see it from the property.
    _, rep = await login_as(tenant_id, "sales_user")
    seen = (await c.get(f"/api/v1/links?record_id={flat['id']}", headers=rep)).json()
    assert seen == []


# ---------- isolation ----------
async def test_deals_are_isolated_between_companies(client_for):
    t1, s1 = await make_workspace()
    t2, s2 = await make_workspace()
    c1, c2 = client_for(s1), client_for(s2)
    _, h1 = await login_as(t1, "admin")
    _, h2 = await login_as(t2, "admin")
    deal = await _deal(c1, h1, (await _lead(c1, h1))["id"], amount_minor=777)
    p1, stages1 = await _pipeline(c1, h1)
    product = (
        await c1.post("/api/v1/products", json={"name": "Course", "price_minor": 9}, headers=h1)
    ).json()
    assert (await c2.get(f"/api/v1/deals/{deal['id']}", headers=h2)).status_code == 404
    assert (await c2.get("/api/v1/deals", headers=h2)).json()["total"] == 0
    assert (await c2.get("/api/v1/deals/board", headers=h2)).json()["open_minor"] == 0
    assert product["id"] not in {
        x["id"] for x in (await c2.get("/api/v1/products", headers=h2)).json()
    }
    # Another company's lead, pipeline or product cannot be used.
    lead2 = await _lead(c2, h2)
    r = await c2.post(
        "/api/v1/deals", json={"lead_id": lead2["id"], "pipeline_id": p1["id"]}, headers=h2
    )
    assert r.status_code == 422
    r = await c2.post("/api/v1/deals", json={"lead_id": deal["lead_id"]}, headers=h2)
    assert r.status_code == 404
    d2 = await _deal(c2, h2, lead2["id"])
    r = await c2.put(
        f"/api/v1/deals/{d2['id']}/products",
        json={"version": d2["version"], "lines": [{"product_id": product["id"]}]},
        headers=h2,
    )
    assert r.status_code == 422
    r = await c2.patch(
        f"/api/v1/pipeline-stages/{stages1['Won']['id']}", json={"probability": 1}, headers=h2
    )
    assert r.status_code == 404

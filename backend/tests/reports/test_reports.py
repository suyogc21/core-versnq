"""Step 7 (Decision log #35): dashboard numbers, who sees which tab, and CSV exports."""

import csv
import io
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.modules import set_module
from app.core.tenancy import tenant_session
from app.modules.audit.models import AuditLog
from app.modules.crm.models import Lead, Notification
from app.modules.reports import numbers as N
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as, make_workspace

PDF = b"%PDF-1.4\n" + b"x" * 200
IST = ZoneInfo("Asia/Kolkata")


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
        await set_module(db, tenant_id, "money", True)
    return tenant_id, client_for(slug)


def follow_up() -> str:
    return (datetime.now(UTC) + timedelta(days=1)).isoformat()


async def _lead(c, h, phone, **extra):
    _, sources = await setup_ids(c, h)
    r = await new_lead(c, h, sources["Website"], phone=phone, **extra)
    assert r.status_code == 201, r.text
    return r.json()


async def _call(c, h, lead_id):
    r = await c.post(
        f"/api/v1/leads/{lead_id}/activities",
        json={
            "type_key": "call",
            "data": {"disposition": "interested"},
            "next_follow_up_at": follow_up(),
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text


async def _won(c, h, lead_id, amount, currency=None):
    body = {"lead_id": lead_id, "amount_minor": amount}
    if currency:
        pipe = (
            await c.post(
                "/api/v1/pipelines", json={"name": f"P {currency}", "currency": currency}, headers=h
            )
        ).json()
        body["pipeline_id"] = pipe["id"]
    deal = (await c.post("/api/v1/deals", json=body, headers=h)).json()
    pipes = (await c.get("/api/v1/pipelines", headers=h)).json()
    pipe = next(p for p in pipes if p["id"] == deal["pipeline_id"])
    won = next(s for s in pipe["stages"] if s["kind"] == "won")
    r = await c.post(
        f"/api/v1/deals/{deal['id']}/move",
        json={"version": deal["version"], "stage_id": won["id"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _company(tenant_id, c):
    """Rep A (2 leads, a call, a won deal, a customer who paid), rep B (1 lead), a manager of
    A's team, an admin and Finance."""
    a_id, a = await login_as(tenant_id, "sales_user")
    b_id, b = await login_as(tenant_id, "sales_user")
    m_id, m = await login_as(tenant_id, "sales_manager")
    await make_team(tenant_id, m_id, [a_id])
    _, admin = await login_as(tenant_id, "admin")
    _, fin = await login_as(tenant_id, "finance")
    l1 = await _lead(c, a, "98765 11111")
    await _lead(c, a, "98765 22222")
    await _lead(c, b, "98765 33333")
    await _call(c, a, l1["id"])
    deal = await _won(c, a, l1["id"], 100_000)
    cust = (
        await c.post(f"/api/v1/leads/{l1['id']}/customer", json={"deal_id": deal["id"]}, headers=a)
    ).json()
    inv = (
        await c.post(
            "/api/v1/invoices", json={"customer_id": cust["id"], "deal_id": deal["id"]}, headers=a
        )
    ).json()
    inv = (await c.post(f"/api/v1/invoices/{inv['id']}/issue", json={}, headers=a)).json()
    async with tenant_session(tenant_id) as db:
        from app.modules.money.service import company_today

        today = await company_today(db)
    r = await c.post(
        f"/api/v1/invoices/{inv['id']}/payments",
        params={"amount_minor": 40_000, "method": "bank", "paid_on": str(today), "name": "p.pdf"},
        content=PDF,
        headers=a | {"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 201, r.text
    return {
        "a": a,
        "b": b,
        "m": m,
        "admin": admin,
        "fin": fin,
        "a_id": a_id,
        "lead": l1,
        "inv": inv,
    }


# ---------- periods ----------
def test_periods_follow_the_company_day_and_week():
    from datetime import date

    today = date(2026, 11, 12)  # a Thursday
    p = N.period("week", "Asia/Kolkata", today)
    assert (p.start_day, p.end_day, p.prev_start_day) == (
        date(2026, 11, 9),
        date(2026, 11, 16),
        date(2026, 11, 2),
    )
    m = N.period("month", "Asia/Kolkata", today)
    assert (m.start_day, m.end_day, m.prev_start_day) == (
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2026, 10, 1),
    )
    assert m.start == datetime(2026, 10, 31, 18, 30, tzinfo=UTC)  # midnight in India
    q = N.period("quarter", "UTC", today)
    assert (q.start_day, q.end_day, q.prev_start_day) == (
        date(2026, 10, 1),
        date(2027, 1, 1),
        date(2026, 7, 1),
    )
    lm = N.period("last_month", "UTC", date(2026, 1, 15))
    assert (lm.start_day, lm.end_day) == (date(2025, 12, 1), date(2026, 1, 1))
    c = N.period("custom", "UTC", today, date(2026, 11, 1), date(2026, 11, 10))
    assert (c.start_day, c.end_day, c.prev_start_day) == (
        date(2026, 11, 1),
        date(2026, 11, 11),
        date(2026, 10, 22),
    )


# ---------- numbers and who sees them ----------
async def test_my_numbers_count_only_my_work(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    mine = (await c.get("/api/v1/dashboards/me", headers=x["a"])).json()
    cur = mine["current"]
    assert (cur["new_leads"], cur["calls"], cur["deals_won"], cur["converted"]) == (2, 1, 1, 1)
    assert cur["booked"] == [{"currency": "INR", "minor": 100_000}]
    assert cur["collected"] == [{"currency": "INR", "minor": 40_000}]
    assert mine["now"]["open_deals"] == 0
    theirs = (await c.get("/api/v1/dashboards/me", headers=x["b"])).json()["current"]
    assert (theirs["new_leads"], theirs["calls"], theirs["deals_won"], theirs["collected"]) == (
        1,
        0,
        0,
        [],
    )


async def test_tabs_follow_permissions(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    assert (await c.get("/api/v1/dashboards/team", headers=x["a"])).status_code == 403
    assert (await c.get("/api/v1/dashboards/business", headers=x["m"])).status_code == 403
    assert (await c.get("/api/v1/dashboards/money", headers=x["a"])).status_code == 403
    assert (await c.get("/api/v1/dashboards/money", headers=x["fin"])).status_code == 200
    assert (await c.get("/api/v1/dashboards/team", headers=x["fin"])).status_code == 403
    for tab in ("team", "business", "money"):
        assert (await c.get(f"/api/v1/dashboards/{tab}", headers=x["admin"])).status_code == 200


async def test_team_counts_the_managers_team_and_admin_sees_everyone(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    team = (await c.get("/api/v1/dashboards/team", headers=x["m"])).json()
    assert team["everyone"] is False and team["current"]["new_leads"] == 2  # rep A only
    assert [r["user_id"] for r in team["leaderboard"]] == [str(x["a_id"])]
    funnel = {s["key"]: s["count"] for s in team["funnel"]}
    assert funnel == {"leads": 2, "contacted": 1, "deal": 1, "won": 1, "converted": 1}
    assert team["sources"][0]["name"] == "Website" and team["sources"][0]["conversion_bp"] == 5000
    everyone = (await c.get("/api/v1/dashboards/team", headers=x["admin"])).json()
    assert everyone["everyone"] is True and everyone["current"]["new_leads"] == 3
    biz = (await c.get("/api/v1/dashboards/business", headers=x["admin"])).json()
    assert len(biz["trend"]) == 6 and biz["trend"][-1]["new_leads"] == 3


async def test_trend_matches_the_headline_month_by_month(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    biz = (await c.get("/api/v1/dashboards/business", headers=x["admin"])).json()
    month = (await c.get("/api/v1/dashboards/business?period=month", headers=x["admin"])).json()
    last, cur = biz["trend"][-1], month["current"]
    for k in ("new_leads", "converted", "booked", "collected"):
        assert last[k] == cur[k], k
    assert cur["booked"] and cur["collected"]  # the company has a won deal and a payment
    assert all(m["new_leads"] == 0 for m in biz["trend"][:-1])


async def test_money_dashboard_matches_the_invoices(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    money = (await c.get("/api/v1/dashboards/money", headers=x["fin"])).json()["current"]
    total = x["inv"]["total_minor"]
    assert (
        money["invoiced"] == [{"currency": "INR", "minor": total}] and money["invoices_issued"] == 1
    )
    assert money["collected"] == [{"currency": "INR", "minor": 40_000}]
    assert money["due"] == [{"currency": "INR", "minor": total - 40_000}]
    assert money["overdue"] == [] and money["by_method"] == [
        {"method": "bank", "currency": "INR", "minor": 40_000}
    ]
    assert money["due_next_30_days"] == [{"currency": "INR", "minor": total - 40_000}]


async def test_currencies_are_never_added_together(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    lead = await _lead(c, h, "98765 44444")
    await _won(c, h, lead["id"], 5_000)
    lead2 = await _lead(c, h, "98765 55555")
    await _won(c, h, lead2["id"], 700, currency="USD")
    cur = (await c.get("/api/v1/dashboards/me", headers=h)).json()["current"]
    assert cur["booked"] == [{"currency": "INR", "minor": 5_000}, {"currency": "USD", "minor": 700}]


async def test_period_edges_use_the_company_midnight(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    a = await _lead(c, h, "98765 66666")
    b = await _lead(c, h, "98765 77777")
    today = datetime.now(IST).date()
    midnight = datetime.combine(today, datetime.min.time(), IST)
    async with tenant_session(tenant_id) as db:
        for lid, when in (
            (a["id"], midnight - timedelta(minutes=1)),
            (b["id"], midnight + timedelta(minutes=1)),
        ):
            await db.execute(
                update(Lead).where(Lead.id == lid).values(created_at=when, assigned_at=when)
            )
    today_n = (await c.get("/api/v1/dashboards/me", params={"period": "today"}, headers=h)).json()
    assert today_n["current"]["new_leads"] == 1 and today_n["previous"]["new_leads"] == 1
    r = await c.get(
        "/api/v1/dashboards/me", params={"period": "custom", "from": str(today)}, headers=h
    )
    assert r.status_code == 422


async def test_another_company_sees_nothing(ws, client_for):
    tenant_id, c = ws
    await _company(tenant_id, c)
    other_id, slug = await make_workspace()
    _, h = await login_as(other_id, "admin")
    team = (await client_for(slug).get("/api/v1/dashboards/team", headers=h)).json()
    assert team["current"]["new_leads"] == 0 and team["leaderboard"] == []


# ---------- export ----------
def _rows(r) -> list[list[str]]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


async def test_export_is_admin_only_by_default_audited_and_alerts_admins(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    _, admin2 = await login_as(tenant_id, "admin")
    for who in ("a", "m", "fin"):
        assert (await c.get("/api/v1/leads/export", headers=x[who])).status_code == 403
    assert (await c.get("/api/v1/invoices/export", headers=x["fin"])).status_code == 403
    rows = _rows(await c.get("/api/v1/leads/export", headers=x["admin"]))
    listed = (await c.get("/api/v1/leads", params={"limit": 200}, headers=x["admin"])).json()
    assert rows[0][:3] == ["Name", "Email", "Phone"] and len(rows) - 1 == listed["total"] == 3
    filtered = _rows(
        await c.get("/api/v1/leads/export", params={"owner": [str(x["a_id"])]}, headers=x["admin"])
    )
    assert len(filtered) - 1 == 2
    async with tenant_session(tenant_id) as db:
        logged = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "data.exported", AuditLog.tenant_id == tenant_id
                )
            )
        ).all()
        assert sorted(a.after["rows"] for a in logged) == [2, 3]
        alerts = (
            await db.scalars(select(Notification).where(Notification.kind == "data_exported"))
        ).all()
        assert alerts and all("exported" in n.title for n in alerts)


async def test_admin_can_give_a_role_export(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    roles = (await c.get("/api/v1/roles", headers=x["admin"])).json()
    finance = next(r for r in roles if r["key"] == "finance")
    perms = sorted({*finance["permissions"], "invoices.export"})
    r = await c.patch(
        f"/api/v1/roles/{finance['id']}", json={"permissions": perms}, headers=x["admin"]
    )
    assert r.status_code == 200, r.text
    rows = _rows(await c.get("/api/v1/invoices/export", headers=x["fin"]))
    assert len(rows) == 2 and rows[1][0].startswith("INV-")
    pays = _rows(await c.get("/api/v1/payments/export", headers=x["fin"]))
    assert pays[1][5] == "400.00"  # 40,000 paise as rupees, exactly


async def test_export_cells_cannot_run_as_formulas_and_other_lists_export(ws):
    tenant_id, c = ws
    x = await _company(tenant_id, c)
    await _lead(c, x["admin"], "98765 88888", first_name='=HYPERLINK("http://evil")')
    rows = _rows(await c.get("/api/v1/leads/export", params={"q": "HYPERLINK"}, headers=x["admin"]))
    assert rows[1][0].startswith("'=")
    deals = _rows(await c.get("/api/v1/deals/export", params={"status": "won"}, headers=x["admin"]))
    assert len(deals) == 2 and deals[1][6] == "1000.00" and deals[1][7] == "INR"
    customers = _rows(await c.get("/api/v1/customers/export", headers=x["admin"]))
    assert len(customers) == 2 and customers[1][0].startswith("C-")

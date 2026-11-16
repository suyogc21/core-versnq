"""Batch 5c of the finishing plan: custom reports.

A report counts only what the person may see (a rep's numbers differ from an admin's); hidden
fields can't be grouped or summed; money is never added across currencies; an invalid
definition is refused; money needs invoices.read; saved reports are private unless shared by
someone allowed to share, and a shared report runs with the viewer's own visibility; another
company sees nothing."""

import csv
import io
import uuid

from sqlalchemy import select, update

from app.core.tenancy import tenant_session
from app.modules.crm.models import Deal
from app.modules.roles.models import Role
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_custom_role, make_workspace

RUN = "/api/v1/reports/run"


async def _company(client_for):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    admin_id, admin = await login_as(tenant_id, "admin")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin)
    for i, owner in enumerate([rep_id, rep_id, admin_id]):
        r = await new_lead(c, admin, sources["Website"], phone=f"98765 4321{i}",
                           owner_user_id=str(owner), city="Pune")  # fmt: skip
        assert r.status_code == 201, r.text
    return tenant_id, c, admin, rep, rep_id


async def _role(tenant_id, key):
    async with tenant_session(tenant_id) as db:
        return await db.scalar(select(Role.id).where(Role.key == key))


async def test_a_report_counts_only_what_the_person_can_see(client_for):
    tenant_id, c, admin, rep, rep_id = await _company(client_for)
    body = {"source": "leads", "group_by": ["owner"]}

    everyone = (await c.post(RUN, json=body, headers=admin)).json()
    mine = (await c.post(RUN, json=body, headers=rep)).json()
    by_month = (await c.post(RUN, json={"source": "leads", "group_by": ["created:month"]},
                             headers=admin)).json()  # fmt: skip
    filtered = (await c.post(RUN, json={"source": "leads", "filters": {"owner": [str(rep_id)]}},
                             headers=admin)).json()  # fmt: skip

    assert sum(r["value"] for r in everyone["rows"]) == 3 and len(everyone["rows"]) == 2
    assert [(r["keys"][0], r["value"]) for r in mine["rows"]] == [(str(rep_id), 2)]
    assert mine["columns"] == ["Owner", "Count"] and mine["rows"][0]["labels"] == ["Member"]
    assert len(by_month["rows"]) == 1 and by_month["rows"][0]["value"] == 3
    assert filtered["rows"][0]["value"] == 2


async def test_hidden_fields_cant_be_grouped_and_bad_definitions_are_refused(client_for):
    tenant_id, c, admin, rep, _ = await _company(client_for)
    r = await c.put(f"/api/v1/field-access/lead/{await _role(tenant_id, 'sales_user')}",
                    json={"access": {"city": "hidden"}}, headers=admin)  # fmt: skip
    assert r.status_code == 200, r.text

    hidden = await c.post(RUN, json={"source": "leads", "group_by": ["city"]}, headers=rep)
    admin_ok = await c.post(RUN, json={"source": "leads", "group_by": ["city"]}, headers=admin)
    unknown = await c.post(
        RUN, json={"source": "leads", "group_by": ["password_hash"]}, headers=admin
    )
    sql = await c.post(
        RUN, json={"source": "deals", "group_by": ["status; drop table"]}, headers=admin
    )
    sum_id = {"source": "leads", "measure": {"op": "sum", "field": "id"}}
    bad_measure = await c.post(RUN, json=sum_id, headers=admin)
    bad_source = await c.post(RUN, json={"source": "users"}, headers=admin)
    bad_filter = await c.post(
        RUN, json={"source": "deals", "filters": {"name": "x"}}, headers=admin
    )
    catalogue = (await c.get("/api/v1/reports/catalogue", headers=rep)).json()
    no_money_role = await make_custom_role(tenant_id, "Caller", "own", ("leads.edit",))
    _, caller = await login_as(tenant_id, role_id=no_money_role)
    caller_sources = {
        s["key"] for s in (await c.get("/api/v1/reports/catalogue", headers=caller)).json()
    }
    caller_money = await c.post(RUN, json={"source": "invoices"}, headers=caller)

    assert hidden.status_code == 422 and hidden.json()["code"] == "field_hidden"
    assert admin_ok.status_code == 200 and admin_ok.json()["rows"][0]["labels"] == ["Pune"]
    assert {unknown.json()["code"], sql.json()["code"], bad_measure.json()["code"]} == {
        "report_invalid"
    }
    assert bad_source.status_code == 422 and bad_filter.json()["code"] == "report_invalid"
    leads = next(s for s in catalogue if s["key"] == "leads")
    assert "city" not in {d["key"] for d in leads["dimensions"]}
    assert "invoices" not in caller_sources and caller_money.status_code == 403  # no invoices.read


async def test_money_is_never_added_across_currencies(client_for):
    tenant_id, c, admin, rep, _ = await _company(client_for)
    leads = (await c.get("/api/v1/leads", headers=admin)).json()["items"]
    for lead, amount in zip(leads, [100_000, 250_000, 70_000], strict=True):
        r = await c.post("/api/v1/deals", json={"lead_id": lead["id"], "amount_minor": amount},
                         headers=admin)  # fmt: skip
        assert r.status_code == 201, r.text
    async with tenant_session(tenant_id) as db:
        await db.execute(update(Deal).where(Deal.amount_minor == 70_000).values(currency="USD"))

    r = (await c.post(RUN, json={"source": "deals", "measure": {"op": "sum", "field": "amount"}},
                      headers=admin)).json()  # fmt: skip
    avg = (await c.post(RUN, json={"source": "deals", "group_by": ["status"],
                                   "measure": {"op": "avg", "field": "amount"}},
                        headers=admin)).json()  # fmt: skip

    assert r["money"] and r["columns"] == ["Currency", "Total value"]
    assert sorted((x["currency"], x["value"]) for x in r["rows"]) == [
        ("INR", 350_000),
        ("USD", 70_000),
    ]
    assert sorted((x["currency"], x["value"]) for x in avg["rows"]) == [
        ("INR", 175_000),
        ("USD", 70_000),
    ]
    assert all(isinstance(x["value"], int) for x in r["rows"])


async def test_saved_reports_private_shared_and_csv(client_for):
    tenant_id, c, admin, rep, rep_id = await _company(client_for)
    _, other_rep = await login_as(tenant_id, "sales_user")
    rep_role = str(await _role(tenant_id, "sales_user"))
    body = {"name": "Leads by owner", "definition": {"source": "leads", "group_by": ["owner"],
                                                    "display": "bar"}}  # fmt: skip

    private = await c.post("/api/v1/reports/saved", json=body, headers=rep)
    rep_shares = await c.post("/api/v1/reports/saved", json={**body, "shared_role_ids": [rep_role]},
                              headers=rep)  # fmt: skip
    shared = await c.post("/api/v1/reports/saved", json={**body, "shared_role_ids": [rep_role]},
                          headers=admin)  # fmt: skip
    seen_by_other = (await c.get("/api/v1/reports/saved", headers=other_rep)).json()
    peek = await c.get(f"/api/v1/reports/saved/{private.json()['id']}", headers=other_rep)
    run_as_rep = (
        await c.post(f"/api/v1/reports/saved/{shared.json()['id']}/run", headers=rep)
    ).json()
    run_as_admin = (await c.post(f"/api/v1/reports/saved/{shared.json()['id']}/run",
                                 headers=admin)).json()  # fmt: skip
    edit_by_rep = await c.put(f"/api/v1/reports/saved/{shared.json()['id']}",
                              json={**body, "name": "Mine now"}, headers=rep)  # fmt: skip
    gone = await c.delete(f"/api/v1/reports/saved/{private.json()['id']}", headers=rep)
    file = await c.post("/api/v1/reports/run.csv", json=body["definition"], headers=admin)

    assert private.status_code == 201 and rep_shares.status_code == 403
    assert shared.status_code == 201
    assert [r["name"] for r in seen_by_other] == ["Leads by owner"] and not seen_by_other[0][
        "yours"
    ]
    assert peek.status_code == 404
    assert sum(r["value"] for r in run_as_rep["rows"]) == 2  # the viewer's own visibility
    assert sum(r["value"] for r in run_as_admin["rows"]) == 3
    assert edit_by_rep.status_code == 403 and gone.status_code == 204
    rows = list(csv.reader(io.StringIO(file.text)))
    assert rows[0] == ["Owner", "Count"] and len(rows) == 3


async def test_another_company_sees_no_reports_and_no_numbers(client_for):
    tenant_id, c, admin, rep, _ = await _company(client_for)
    saved = await c.post("/api/v1/reports/saved", headers=admin,
                         json={"name": "All", "definition": {"source": "leads"}})  # fmt: skip
    other_id, other_slug = await make_workspace()
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)

    numbers = (await oc.post(RUN, json={"source": "leads"}, headers=other_admin)).json()
    listed = (await oc.get("/api/v1/reports/saved", headers=other_admin)).json()
    peek = await oc.get(f"/api/v1/reports/saved/{saved.json()['id']}", headers=other_admin)

    assert numbers["rows"] == [{"keys": [], "labels": [], "currency": None, "value": 0}]
    assert listed == [] and peek.status_code == 404
    assert uuid.UUID(saved.json()["id"])


async def test_every_grouping_and_measure_runs(client_for):
    tenant_id, c, admin, rep, _ = await _company(client_for)
    fields = (
        {
            "key": "course",
            "label": "Course",
            "type": "select",
            "options": [{"value": "data", "label": "Data"}],
        },
        {"key": "budget", "label": "Budget", "type": "number"},
    )
    for f in fields:
        r = await c.post("/api/v1/custom-fields", json={"entity": "lead", **f}, headers=admin)
        assert r.status_code == 201, r.text
    catalogue = (await c.get("/api/v1/reports/catalogue", headers=admin)).json()
    failures = []
    for s in catalogue:
        for d in s["dimensions"]:
            body = {"source": s["key"], "group_by": [d["key"]], "date_from": "2020-01-01",
                    "date_to": "2030-01-01"}  # fmt: skip
            r = await c.post(RUN, json=body, headers=admin)
            if r.status_code != 200:
                failures.append((s["key"], d["key"], r.text[:200]))
        for m in s["measures"]:
            for op in ("sum", "avg"):
                body = {"source": s["key"], "measure": {"op": op, "field": m["key"]},
                        "group_by": [s["dimensions"][0]["key"]]}  # fmt: skip
                r = await c.post(RUN, json=body, headers=admin)
                if r.status_code != 200:
                    failures.append((s["key"], m["key"], op, r.text[:200]))
    assert failures == []
    leads = next(s for s in catalogue if s["key"] == "leads")
    assert "cf.course" in {d["key"] for d in leads["dimensions"]}
    assert "cf.budget" in {m["key"] for m in leads["measures"]}

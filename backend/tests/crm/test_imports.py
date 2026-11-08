"""Step 1: CSV import."""

import csv
import io

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.crm import imports as IM
from app.modules.crm.models import Lead
from tests.crm.intake_helpers import capture, notifications
from tests.factories import login_as


def _csv(rows: list[list[str]], delimiter=",") -> str:
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter).writerows(rows)
    return out.getvalue()


async def _upload(c, h, text, name="leads.csv"):
    r = await c.post("/api/v1/imports", json={"file_name": name, "content": text}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _start(c, h, imp, **body):
    r = await c.post(
        f"/api/v1/imports/{imp['id']}/start",
        json={"mapping": imp["suggested"], **body},
        headers=h,
    )
    return r


async def _sources(c, h):
    return {s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources", headers=h)).json()}


async def _leads(tenant_id):
    async with tenant_session(tenant_id) as db:
        return list((await db.scalars(select(Lead).order_by(Lead.created_at))).all())


async def test_upload_reads_the_file_and_suggests_columns(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    text = "﻿" + _csv(
        [
            ["Full Name", "Mobile", "E-mail", "City", "Lead Owner", "Status", "Notes", ""],
            ["Rahul Mehta", "98765 43210", "rahul@example.org", "Pune", "", "", "Hot", ""],
            ["", "", "", "", "", "", "", ""],
            ["Asha", "9876500001", "", "", "", "", "", "x"],
        ],
        delimiter=";",
    )
    imp = await _upload(c, h, text)
    assert imp["row_count"] == 2 and imp["status"] == "uploaded"
    assert imp["headers"][-1] == "Column 8"
    assert imp["suggested"] == {
        "Full Name": "full_name",
        "Mobile": "phone",
        "E-mail": "email",
        "City": "city",
        "Lead Owner": "owner_email",
        "Status": "stage",
        "Notes": "message",
    }
    assert imp["sample"][0][0] == "Rahul Mehta"


async def test_import_creates_updates_and_reports_problem_rows(ws):
    tenant_id, c = ws
    admin_id, h = await login_as(tenant_id, "admin")
    rep, rep_email = await login_as(tenant_id, "sales_user"), None
    _, existing = await capture(tenant_id, phone="98765 00099", fields={"first_name": "Old"})
    async with tenant_session(tenant_id) as db:
        from app.modules.users.models import User

        rep_email = (await db.get(User, rep[0])).email
    text = _csv(
        [
            ["Name", "Phone", "Email", "Owner", "Status", "Source"],
            ["Rahul Mehta", "98765 43210", "", rep_email, "Qualified", "Referral"],
            ["Old Name", "+91 98765 00099", "old@example.org", "", "", ""],
            ["No Contact", "", "", "", "", ""],
            ["Bad Stage", "9876500002", "", "", "Nope", ""],
            ["Bad Owner", "9876500003", "", "ghost@example.org", "", ""],
            ["Bad Phone", "12", "", "", "", ""],
        ]
    )
    imp = await _upload(c, h, text)
    r = await _start(c, h, imp, source_id=(await _sources(c, h))["Website"], owner="none")
    assert r.status_code == 200 and r.json()["status"] == "queued"

    result = await IM.run_import(tenant_id, imp["id"])
    assert result == {"created": 1, "updated": 1, "skipped": 0, "failed": 4}
    done = (await c.get(f"/api/v1/imports/{imp['id']}", headers=h)).json()
    assert done["status"] == "done" and done["failed_count"] == 4

    leads = {x.display_name: x for x in await _leads(tenant_id)}
    rahul = leads["Rahul Mehta"]
    assert rahul.owner_user_id == rep[0] and rahul.created_via == "csv"
    old = leads["Old Name"]  # blank last name and email filled, first name kept
    assert (old.first_name, old.primary_email) == ("Old", "old@example.org")

    problems = (await c.get(f"/api/v1/imports/{imp['id']}/problems", headers=h)).text
    rows = list(csv.reader(io.StringIO(problems)))
    assert rows[0][-2:] == ["Result", "Why"]
    why = {r[0]: r[-1] for r in rows[1:]}
    assert "phone, email or LinkedIn" in why["No Contact"]
    assert "Unknown stage 'Nope'" in why["Bad Stage"]
    assert "ghost@example.org" in why["Bad Owner"]
    assert "not a valid phone" in why["Bad Phone"]
    assert any(k == "import_done" for k, _ in await notifications(tenant_id, admin_id))


async def test_reps_import_only_for_themselves_and_never_touch_others_leads(ws):
    tenant_id, c = ws
    rep_id, rep_h = await login_as(tenant_id, "sales_user")
    _, admin_h = await login_as(tenant_id, "admin")
    # Sales users don't have leads.import by default; give it to them for this test.
    roles = (await c.get("/api/v1/roles", headers=admin_h)).json()
    sales = next(r for r in roles if r["key"] == "sales_user")
    perms = sorted(set(sales["permissions"]) | {"leads.import"})
    assert (
        await c.patch(f"/api/v1/roles/{sales['id']}", json={"permissions": perms}, headers=admin_h)
    ).status_code == 200

    owner_id, _ = await login_as(tenant_id, "sales_user")
    await capture(tenant_id, phone="98765 00100", owner=owner_id)
    imp = await _upload(
        c, rep_h, _csv([["Phone", "City"], ["98765 00100", "Goa"], ["9876500101", "Goa"]])
    )
    src = (await _sources(c, rep_h))["Website"]
    assert (await _start(c, rep_h, imp, source_id=src, owner="rules")).status_code == 422
    assert (await _start(c, rep_h, imp, source_id=src)).status_code == 200
    await IM.run_import(tenant_id, imp["id"])
    done = (await c.get(f"/api/v1/imports/{imp['id']}", headers=rep_h)).json()
    assert (done["created_count"], done["skipped_count"]) == (1, 1)
    leads = {x.primary_phone: x for x in await _leads(tenant_id)}
    assert leads["+919876500100"].city is None  # someone else's lead: untouched
    assert leads["+919876500101"].owner_user_id == rep_id
    # Another rep cannot see this import.
    _, other_h = await login_as(tenant_id, "sales_manager")
    assert (await c.get(f"/api/v1/imports/{imp['id']}", headers=other_h)).status_code == 404


async def test_mapping_is_checked_before_starting(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    imp = await _upload(c, h, _csv([["Name", "City"], ["Asha", "Pune"]]))
    src = (await _sources(c, h))["Website"]
    no_contact = await _start(c, h, imp, source_id=src)
    assert (
        no_contact.status_code == 422 and "phone, email or LinkedIn" in no_contact.json()["detail"]
    )
    bad_target = await c.post(
        f"/api/v1/imports/{imp['id']}/start",
        json={"mapping": {"Name": "password", "City": "phone"}, "source_id": src},
        headers=h,
    )
    assert bad_target.status_code == 422
    no_source = await c.post(
        f"/api/v1/imports/{imp['id']}/start", json={"mapping": {"City": "phone"}}, headers=h
    )
    assert no_source.status_code == 422


async def test_cancel_stops_and_delete_removes_the_rows(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    rows = [["Phone"]] + [[f"98765{i:05d}"] for i in range(500)]
    imp = await _upload(c, h, _csv(rows))
    await _start(c, h, imp, source_id=(await _sources(c, h))["Website"])
    assert (await c.post(f"/api/v1/imports/{imp['id']}/cancel", headers=h)).json()[
        "status"
    ] == "cancelled"
    assert await IM.run_import(tenant_id, imp["id"]) == {"skipped": True}
    assert await _leads(tenant_id) == []
    assert (await c.delete(f"/api/v1/imports/{imp['id']}", headers=h)).status_code == 204
    assert (await c.get(f"/api/v1/imports/{imp['id']}", headers=h)).status_code == 404


async def test_large_import_runs_in_batches_with_progress(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    rows = [["Phone", "Name"]] + [[f"9876{i:06d}", f"Person {i}"] for i in range(1000)]
    imp = await _upload(c, h, _csv(rows))
    await _start(c, h, imp, source_id=(await _sources(c, h))["Website"])
    assert await IM.run_queued_imports() == 1
    done = (await c.get(f"/api/v1/imports/{imp['id']}", headers=h)).json()
    assert (done["status"], done["created_count"]) == ("done", 1000)


async def test_bad_files_are_refused(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    for text in (" ", "Phone\n", "\n\n"):
        r = await c.post("/api/v1/imports", json={"file_name": "x.csv", "content": text}, headers=h)
        assert r.status_code == 422, text
    _, rep_h = await login_as(tenant_id, "sales_user")
    r = await c.post(
        "/api/v1/imports", json={"file_name": "x.csv", "content": "Phone\n1"}, headers=rep_h
    )
    assert r.status_code == 403

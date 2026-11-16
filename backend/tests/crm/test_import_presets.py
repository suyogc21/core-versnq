"""Finishing plan, batch 2: HubSpot and LeadSquared exports import without matching columns by
hand. The file is recognised from its headers; the columns are pre-matched; a stage, owner or
source that isn't in Core keeps the row (default stage, assignment rules, the chosen source)
with the original value in the lead's note; owners match by email or by a unique name."""

import csv
import io

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.crm import import_presets as PR
from app.modules.crm import imports as IM
from app.modules.crm.models import Activity, Lead, LeadStage
from app.modules.users.models import User
from tests.factories import login_as


def _csv(rows: list[list[str]]) -> str:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


HUBSPOT = [
    "Record ID", "First Name", "Last Name", "Email", "Phone Number", "Mobile Phone Number",
    "Company Name", "Lifecycle Stage", "Lead Status", "Contact owner", "Original Source",
    "City", "State/Region", "Country/Region", "Create Date",
]  # fmt: skip
LEADSQUARED = [
    "Prospect ID", "First Name", "Last Name", "Email Address", "Phone Number", "Mobile Number",
    "Lead Stage", "Lead Source", "Owner", "City", "State", "Country", "Created On",
]  # fmt: skip


def test_the_file_is_recognised_from_its_headers():
    assert PR.detect(HUBSPOT) == "hubspot"
    assert PR.detect(LEADSQUARED) == "leadsquared"
    assert PR.detect([h.upper().replace(" ", "_") for h in HUBSPOT]) == "hubspot"
    assert PR.detect(["Name", "Phone", "Email", "City"]) is None
    assert PR.detect(["Name", "Lead Stage", "Phone"]) is None  # one marker isn't enough


async def _upload(c, h, rows, name="export.csv"):
    r = await c.post("/api/v1/imports", json={"file_name": name, "content": _csv(rows)}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _ids(c, h):
    sources = {s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources", headers=h)).json()}
    return sources


async def _person(tenant_id, user_id):
    async with tenant_session(tenant_id) as db:
        user = await db.get(User, user_id)
        user.name = f"Ravi Kumar {str(user_id)[:4]}"  # test people are all "Member"
        await db.commit()
        return user


async def _lead(tenant_id, phone):
    async with tenant_session(tenant_id) as db:
        lead = await db.scalar(select(Lead).where(Lead.primary_phone == phone))
        notes = (await db.scalars(select(Activity).where(Activity.lead_id == lead.id))).all()
        stage = await db.get(LeadStage, lead.stage_id)
        return lead, stage.name, "\n".join(a.body or "" for a in notes)


async def test_a_hubspot_export_imports_with_owners_stages_and_notes(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    rep_id, _ = await login_as(tenant_id, "sales_user")
    rep = await _person(tenant_id, rep_id)
    async with tenant_session(tenant_id) as db:
        stage = (await db.scalars(select(LeadStage).order_by(LeadStage.position))).all()[1]
    rows = [
        HUBSPOT,
        ["101", "Asha", "Rao", "asha@example.org", "+91 98765 11111", "", "Rao Ltd",
         stage.name.upper(), "Attempted to contact", rep.name, "Organic Search",
         "Pune", "Maharashtra", "India", "2026-01-05 10:00"],
        ["102", "Ben", "Ng", "", "", "98765 22222", "", "subscriber", "", "Nobody Known",
         "Website", "", "", "", ""],
    ]  # fmt: skip
    imp = await _upload(c, h, rows)

    assert (imp["preset"], imp["preset_name"]) == ("hubspot", "HubSpot")
    s = imp["suggested"]
    assert s["Record ID"] == "external_id" and s["Lifecycle Stage"] == "stage"
    assert s["Phone Number"] == s["Mobile Phone Number"] == "phone"
    assert s["Contact owner"] == "owner_email" and s["Original Source"] == "source"
    assert s["State/Region"] == "region" and s["Lead Status"] == "message"

    no_fallback = await c.post(f"/api/v1/imports/{imp['id']}/start", json={
        "mapping": s, "unknown_values": "note", "preset": "hubspot"}, headers=h)  # fmt: skip
    assert no_fallback.status_code == 422  # a source for rows whose source isn't in Core
    r = await c.post(f"/api/v1/imports/{imp['id']}/start", json={
        "mapping": s, "unknown_values": "note", "preset": "hubspot", "owner": "rules",
        "source_id": (await _ids(c, h))["Website"]}, headers=h)  # fmt: skip
    assert r.status_code == 200, r.text
    result = await IM.run_import(tenant_id, imp["id"])
    assert result == {"created": 2, "updated": 0, "skipped": 0, "failed": 0}

    asha, asha_stage, asha_notes = await _lead(tenant_id, "+919876511111")
    assert asha.owner_user_id == rep_id  # matched by name
    assert asha_stage == stage.name and asha.region == "Maharashtra"
    assert (
        "Lead Status: Attempted to contact" in asha_notes and "Country/Region: India" in asha_notes
    )
    assert "Source in the file: Organic Search" in asha_notes
    ben, ben_stage, ben_notes = await _lead(tenant_id, "+919876522222")
    assert "Stage in the file: subscriber" in ben_notes
    assert "Owner in the file: Nobody Known" in ben_notes
    assert ben_stage != "subscriber"


async def test_a_leadsquared_export_matches_owner_by_email(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    rep_id, _ = await login_as(tenant_id, "sales_user")
    rep = await _person(tenant_id, rep_id)
    rows = [
        LEADSQUARED,
        ["p-1", "Kiran", "Shah", "kiran@example.org", "", "98765 33333", "Prospect",
         "Referral", rep.email.upper(), "Goa", "Goa", "IN", "05/01/2026"],
    ]  # fmt: skip
    imp = await _upload(c, h, rows)
    assert imp["preset"] == "leadsquared"
    s = imp["suggested"]
    assert (
        s["Lead Stage"] == "stage" and s["Lead Source"] == "source" and s["Owner"] == "owner_email"
    )
    r = await c.post(f"/api/v1/imports/{imp['id']}/start", json={
        "mapping": s, "unknown_values": "note", "owner": "rules",
        "source_id": (await _ids(c, h))["Website"]}, headers=h)  # fmt: skip
    assert r.status_code == 200, r.text
    await IM.run_import(tenant_id, imp["id"])
    kiran, _, notes = await _lead(tenant_id, "+919876533333")
    assert kiran.owner_user_id == rep_id and kiran.city == "Goa"
    assert "Stage in the file: Prospect" in notes  # no such stage in a new company


async def test_without_note_mode_unknown_values_still_fail_the_row(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    rows = [LEADSQUARED, ["p-2", "Zed", "", "", "", "98765 44444", "Nope", "", "", "", "", "",
                          ""]]  # fmt: skip
    imp = await _upload(c, h, rows)
    body = {"mapping": imp["suggested"], "source_id": (await _ids(c, h))["Website"]}
    await c.post(f"/api/v1/imports/{imp['id']}/start", json=body, headers=h)
    assert (await IM.run_import(tenant_id, imp["id"]))["failed"] == 1


async def test_another_company_never_sees_the_import(ws, client_for):
    from tests.factories import make_workspace

    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    imp = await _upload(c, h, [HUBSPOT, ["1", "A", "", "", "98765 55555"] + [""] * 10])
    other_id, other_slug = await make_workspace()
    _, oh = await login_as(other_id, "admin")
    other = client_for(other_slug)
    assert (await other.get(f"/api/v1/imports/{imp['id']}", headers=oh)).status_code == 404

"""Step 5: customers, the document checklist, files on our server, secure customer links."""

import os

import pytest
from sqlalchemy import select

from app.core import storage
from app.core.config import get_settings
from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.crm import customers as C
from app.modules.crm.models import Notification, StoredFile, Task
from app.modules.settings.models import TenantSettings
from tests.crm.helpers import make_team, new_lead, setup_ids
from tests.factories import login_as, make_workspace

PDF = b"%PDF-1.4\n" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200
DOCX = b"PK\x03\x04" + b"x" * 200
EXE = b"MZ\x90\x00" + b"x" * 200


@pytest.fixture(autouse=True)
def files_dir(tmp_path):
    settings = get_settings()
    old = settings.files_dir
    settings.files_dir = str(tmp_path / "files")
    yield tmp_path / "files"
    settings.files_dir = old


async def _lead(c, h, phone="98765 43210", **extra):
    _, sources = await setup_ids(c, h)
    r = await new_lead(c, h, sources["Website"], phone=phone, **extra)
    assert r.status_code == 201, r.text
    return r.json()


async def _customer(c, h, lead_id, **body):
    r = await c.post(f"/api/v1/leads/{lead_id}/customer", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _req(c, h, name, **body):
    r = await c.post("/api/v1/document-requirements", json={"name": name, **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _docs(c, h, customer_id):
    r = await c.get(f"/api/v1/customers/{customer_id}/documents", headers=h)
    assert r.status_code == 200, r.text
    return {d["name"]: d for d in r.json()["documents"]}


def _up(c, h, customer_id, doc_id, data, name="file.pdf"):
    return c.post(
        f"/api/v1/customers/{customer_id}/documents/{doc_id}/files",
        params={"name": name},
        content=data,
        headers=h | {"Content-Type": "application/octet-stream"},
    )


# ---------- becoming a customer ----------
async def test_make_customer_numbers_timeline_events_and_checklist(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    await _req(c, h, "Aadhaar")
    await _req(c, h, "Photo", is_required=False)
    a = await _lead(c, h)
    b = await _lead(c, h, phone="98765 43211")
    ca = await _customer(c, h, a["id"])
    cb = await _customer(c, h, b["id"])
    assert (ca["number"], cb["number"]) == ("C-0001", "C-0002")
    assert (ca["docs_done"], ca["docs_required"]) == (0, 1)
    # Once only; the same record keeps its timeline.
    again = await c.post(f"/api/v1/leads/{a['id']}/customer", json={}, headers=h)
    assert again.status_code == 409
    acts = (await c.get(f"/api/v1/leads/{a['id']}/activities", headers=h)).json()
    assert any(x["type_key"] == "became_customer" for x in acts)
    assert (await c.get(f"/api/v1/leads/{a['id']}/customer", headers=h)).json()["id"] == ca["id"]
    docs = await _docs(c, h, ca["id"])
    assert {k: v["status"] for k, v in docs.items()} == {"Aadhaar": "pending", "Photo": "pending"}
    async with tenant_session(tenant_id) as db:
        types = (await db.scalars(select(Event.type).where(Event.type == "customer.created"))).all()
    assert len(types) == 2
    # A customer cannot be deleted; they are set inactive instead.
    r = await c.delete(f"/api/v1/leads/{a['id']}", headers=h)
    assert r.status_code == 422 and "Inactive" in r.json()["detail"]
    r = await c.patch(
        f"/api/v1/customers/{ca['id']}",
        json={"version": ca["version"], "status": "inactive"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["status"] == "inactive"


async def test_product_items_apply_only_with_a_won_deal_for_that_product(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    prod = (
        await c.post(
            "/api/v1/products", json={"name": "Study abroad", "price_minor": 100}, headers=h
        )
    ).json()
    await _req(c, h, "ID proof")
    await _req(c, h, "Visa papers", product_ids=[prod["id"]])
    lead = await _lead(c, h)
    cust = await _customer(c, h, lead["id"])
    assert set(await _docs(c, h, cust["id"])) == {"ID proof"}
    deal = (
        await c.post("/api/v1/deals", json={"lead_id": lead["id"], "name": "Abroad"}, headers=h)
    ).json()
    lines = await c.put(
        f"/api/v1/deals/{deal['id']}/products",
        json={"version": deal["version"], "lines": [{"product_id": prod["id"]}]},
        headers=h,
    )
    assert lines.status_code == 200, lines.text
    deal = (await c.get(f"/api/v1/deals/{deal['id']}", headers=h)).json()
    pipe = (await c.get("/api/v1/pipelines", headers=h)).json()[0]
    won = next(s for s in pipe["stages"] if s["kind"] == "won")
    r = await c.post(
        f"/api/v1/deals/{deal['id']}/move",
        json={"version": deal["version"], "stage_id": won["id"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert set(await _docs(c, h, cust["id"])) == {"ID proof", "Visa papers"}


# ---------- who sees and does what ----------
async def test_visibility_finance_reads_all_and_only_verifiers_review(ws):
    tenant_id, c = ws
    mgr_id, mgr = await login_as(tenant_id, "sales_manager")
    rep_id, rep = await login_as(tenant_id, "sales_user")
    other_id, other = await login_as(tenant_id, "sales_user")
    await make_team(tenant_id, mgr_id, [rep_id])
    _, fin = await login_as(tenant_id, "finance")
    _, admin = await login_as(tenant_id, "admin")
    await _req(c, admin, "Aadhaar")
    lead = await _lead(c, rep)
    cust = await _customer(c, rep, lead["id"])
    doc = (await _docs(c, rep, cust["id"]))["Aadhaar"]

    # Another rep sees nothing; Finance sees every customer but no leads, and cannot change.
    assert (await c.get(f"/api/v1/customers/{cust['id']}", headers=other)).status_code == 404
    assert (await c.get("/api/v1/customers", headers=other)).json()["total"] == 0
    assert (await c.get("/api/v1/customers", headers=fin)).json()["total"] == 1
    assert (await c.get(f"/api/v1/leads/{lead['id']}", headers=fin)).status_code == 404
    assert (await c.get("/api/v1/leads", headers=fin)).json()["total"] == 0
    assert (await _up(c, fin, cust["id"], doc["id"], PDF)).status_code == 403
    assert (
        await c.post(f"/api/v1/leads/{lead['id']}/customer", json={}, headers=fin)
    ).status_code == 403

    # The rep uploads; the rep cannot verify; the manager can.
    assert (await _up(c, rep, cust["id"], doc["id"], PDF)).status_code == 201
    url = f"/api/v1/customers/{cust['id']}/documents/{doc['id']}"
    assert (await c.post(f"{url}/verify", headers=rep)).status_code == 403
    assert (await c.post(f"{url}/reject", json={"reason": " "}, headers=mgr)).status_code == 422
    r = await c.post(f"{url}/reject", json={"reason": "Blurry photo"}, headers=mgr)
    assert r.status_code == 200
    assert r.json()["documents"][0]["status"] == "rejected"
    r = await c.post(f"{url}/verify", headers=mgr)
    assert r.json()["documents"][0]["status"] == "verified"
    assert r.json()["done"] == 1
    # Only Admin deletes files.
    fid = r.json()["documents"][0]["files"][0]["id"]
    assert (
        await c.delete(f"/api/v1/customers/{cust['id']}/files/{fid}", headers=mgr)
    ).status_code == 403
    assert (
        await c.delete(f"/api/v1/customers/{cust['id']}/files/{fid}", headers=admin)
    ).status_code == 204
    assert (await _docs(c, admin, cust["id"]))["Aadhaar"]["status"] == "pending"


# ---------- files ----------
async def test_files_type_size_quota_download_and_cleanup(ws, files_dir):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    await _req(c, h, "Aadhaar")
    await _req(c, h, "Agreement", allow_office=True)
    lead = await _lead(c, h)
    cust = await _customer(c, h, lead["id"])
    docs = await _docs(c, h, cust["id"])
    aadhaar, agreement = docs["Aadhaar"]["id"], docs["Agreement"]["id"]

    # The real type is read from the bytes: a renamed program is refused.
    r = await _up(c, h, cust["id"], aadhaar, EXE, "aadhaar.pdf")
    assert r.status_code == 422 and "not accepted" in r.json()["detail"]
    assert (await _up(c, h, cust["id"], aadhaar, DOCX, "a.docx")).status_code == 422
    assert (await _up(c, h, cust["id"], agreement, DOCX, "a.docx")).status_code == 201
    too_big = b"%PDF-" + b"x" * (storage.MAX_FILE_BYTES + 1)
    assert (await _up(c, h, cust["id"], aadhaar, too_big)).status_code == 422
    r = await _up(c, h, cust["id"], aadhaar, PNG, "../../etc/passwd.png")
    assert r.status_code == 201
    f = r.json()
    assert f["original_name"] == "passwd.png" and f["previewable"]

    # Downloads go through the API with safe headers.
    r = await c.get(f"/api/v1/customers/{cust['id']}/files/{f['id']}", headers=h)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("inline")
    r = await c.get(
        f"/api/v1/customers/{cust['id']}/files/{f['id']}", params={"download": 1}, headers=h
    )
    assert r.headers["content-disposition"].startswith("attachment")

    # Quota: the company's storage is full.
    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).storage_quota_bytes = 500
    r = await _up(c, h, cust["id"], aadhaar, PDF)
    assert r.status_code == 422 and "storage" in r.json()["detail"]
    usage = (await c.get("/api/v1/storage", headers=h)).json()
    assert usage["used_bytes"] == len(PNG) + len(DOCX) and usage["quota_bytes"] == 500

    # Nightly clean-up: a file on disk without a record goes; a missing file is reported.
    stray = files_dir / str(tenant_id) / "2026" / "01" / "stray.pdf"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(PDF)
    os.utime(stray, (0, 0))
    async with tenant_session(tenant_id) as db:
        gone = await db.scalar(select(StoredFile).where(StoredFile.id == f["id"]))
        storage.remove(gone.path)
        report = await C.clean_files(db, tenant_id)
    assert report["removed"] == 1 and not stray.exists()
    assert report["missing"] == [gone.path]


async def test_files_never_cross_companies(client_for):
    a_id, a_slug = await make_workspace()
    b_id, b_slug = await make_workspace()
    a, b = client_for(a_slug), client_for(b_slug)
    _, ah = await login_as(a_id, "admin")
    _, bh = await login_as(b_id, "admin")
    await _req(a, ah, "Aadhaar")
    cust = await _customer(a, ah, (await _lead(a, ah))["id"])
    doc = (await _docs(a, ah, cust["id"]))["Aadhaar"]
    f = (await _up(a, ah, cust["id"], doc["id"], PDF)).json()
    for url in (
        f"/api/v1/customers/{cust['id']}",
        f"/api/v1/customers/{cust['id']}/documents",
        f"/api/v1/customers/{cust['id']}/files/{f['id']}",
        f"/api/v1/customers/{cust['id']}/links",
    ):
        assert (await b.get(url, headers=bh)).status_code == 404, url
    assert (await _up(b, bh, cust["id"], doc["id"], PDF)).status_code == 404
    assert (await b.get("/api/v1/customers", headers=bh)).json()["total"] == 0
    # B's own customer cannot reach A's file by id either.
    cb = await _customer(b, bh, (await _lead(b, bh))["id"])
    assert (
        await b.get(f"/api/v1/customers/{cb['id']}/files/{f['id']}", headers=bh)
    ).status_code == 404
    # A's link code does not open on B's address.
    code = (await a.post(f"/api/v1/customers/{cust['id']}/links", json={}, headers=ah)).json()[
        "code"
    ]
    assert (await b.get(f"/api/v1/public/links/{code}")).status_code == 404
    assert (await a.get(f"/api/v1/public/links/{code}")).status_code == 200


# ---------- the customer's link ----------
async def test_link_page_upload_submit_and_every_dead_link(ws):
    tenant_id, c = ws
    owner_id, h = await login_as(tenant_id, "sales_user")
    _, admin = await login_as(tenant_id, "admin")
    await _req(c, admin, "Aadhaar", hint="Front and back")
    r = await c.post(
        "/api/v1/custom-fields",
        params={"entity": "customer"},
        json={"key": "passport_no", "label": "Passport number", "type": "text", "required": True},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    lead = await _lead(c, h)
    cust = await _customer(c, h, lead["id"])
    other = await _customer(c, h, (await _lead(c, h, phone="98765 43219"))["id"])
    other_doc = (await _docs(c, h, other["id"]))["Aadhaar"]

    bad = await c.post(
        f"/api/v1/customers/{cust['id']}/links", json={"field_keys": ["nope"]}, headers=h
    )
    assert bad.status_code == 422
    first = (
        await c.post(
            f"/api/v1/customers/{cust['id']}/links", json={"field_keys": ["passport_no"]}, headers=h
        )
    ).json()
    link = (
        await c.post(
            f"/api/v1/customers/{cust['id']}/links", json={"field_keys": ["passport_no"]}, headers=h
        )
    ).json()
    # A new link cancels the earlier one.
    assert (await c.get(f"/api/v1/public/links/{first['code']}")).status_code == 404
    assert (await c.get("/api/v1/public/links/not-a-real-code")).status_code == 404

    page = (await c.get(f"/api/v1/public/links/{link['code']}")).json()
    assert page["customer_name"] == "Rahul" and page["fields"][0]["key"] == "passport_no"
    doc = page["documents"][0]
    assert (doc["name"], doc["hint"], doc["status"]) == ("Aadhaar", "Front and back", "pending")

    up = f"/api/v1/public/links/{link['code']}/documents"
    hdr = {"Content-Type": "application/octet-stream"}
    r = await c.post(f"{up}/{doc['id']}/files", params={"name": "a.pdf"}, content=PDF, headers=hdr)
    assert r.status_code == 201 and r.json()["documents"][0]["status"] == "received"
    # The link reaches only its own customer's documents.
    r = await c.post(
        f"{up}/{other_doc['id']}/files", params={"name": "a.pdf"}, content=PDF, headers=hdr
    )
    assert r.status_code == 404

    sub = f"/api/v1/public/links/{link['code']}/submit"
    assert (await c.post(sub, json={"values": {}})).status_code == 422  # required field
    assert (await c.post(sub, json={"values": {"secret": "x"}})).status_code == 422
    assert (await c.post(sub, json={"values": {"passport_no": "P123"}})).status_code == 204
    # Submitted: the link is closed, values are on the customer, the owner is told.
    assert (await c.get(f"/api/v1/public/links/{link['code']}")).status_code == 404
    got = (await c.get(f"/api/v1/customers/{cust['id']}", headers=h)).json()
    assert got["custom_fields"] == {"passport_no": "P123"}
    acts = (await c.get(f"/api/v1/leads/{lead['id']}/activities", headers=h)).json()
    kinds = [a["type_key"] for a in acts]
    assert "customer_submitted" in kinds and "document_uploaded" in kinds
    async with tenant_session(tenant_id) as db:
        note = await db.scalar(select(Notification).where(Notification.user_id == owner_id))
    assert note is not None and note.kind == "customer_submitted"

    # Cancelled and expired links are dead too.
    third = (await c.post(f"/api/v1/customers/{cust['id']}/links", json={}, headers=h)).json()
    assert (
        await c.delete(f"/api/v1/customers/{cust['id']}/links/{third['id']}", headers=h)
    ).status_code == 204
    assert (await c.get(f"/api/v1/public/links/{third['code']}")).status_code == 404
    fourth = (await c.post(f"/api/v1/customers/{cust['id']}/links", json={}, headers=h)).json()
    async with tenant_session(tenant_id) as db:
        from app.modules.crm.models import CustomerLink

        row = await db.get(CustomerLink, fourth["id"])
        row.expires_at = C.L.now()
    assert (await c.get(f"/api/v1/public/links/{fourth['code']}")).status_code == 404
    states = {
        x["id"]: x["state"]
        for x in (await c.get(f"/api/v1/customers/{cust['id']}/links", headers=h)).json()
    }
    assert states[link["id"]] == "submitted" and states[third["id"]] == "cancelled"
    assert states[fourth["id"]] == "expired"


# ---------- rules ----------
async def test_two_customers_cannot_merge_and_reminders_are_created_once(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    await _req(c, h, "Aadhaar")
    a = await _lead(c, h, owner_user_id=None)
    b = await _lead(c, h, phone="98765 43212")
    await _customer(c, h, a["id"])
    await _customer(c, h, b["id"])
    la = (await c.get(f"/api/v1/leads/{a['id']}", headers=h)).json()
    lb = (await c.get(f"/api/v1/leads/{b['id']}", headers=h)).json()
    r = await c.post(
        "/api/v1/leads/merge",
        json={
            "survivor_id": a["id"],
            "survivor_version": la["version"],
            "other_id": b["id"],
            "other_version": lb["version"],
            "take_from_other": [],
        },
        headers=h,
    )
    assert r.status_code == 422 and "customers" in r.json()["detail"]

    async with tenant_session(tenant_id) as db:
        (await db.get(TenantSettings, tenant_id)).document_reminder_days = 1
    async with tenant_session(tenant_id) as db:
        from app.modules.crm.models import Customer

        for cust in (await db.scalars(select(Customer))).all():
            cust.since = C.L.now().replace(year=2025)
    async with tenant_session(tenant_id) as db:
        first = await C.remind_pending(db)
    async with tenant_session(tenant_id) as db:
        second = await C.remind_pending(db)
        tasks = (await db.scalars(select(Task).where(Task.created_from == "documents"))).all()
    owned = sum(1 for x in (la, lb) if x["owner_user_id"])
    assert first == owned and second == 0 and len(tasks) == owned


async def test_automation_runs_when_a_lead_becomes_a_customer(ws):
    from app.modules.crm import automation as A

    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    tag = (await c.post("/api/v1/tags", json={"name": "Enrolled"}, headers=h)).json()
    r = await c.post(
        "/api/v1/automations",
        json={
            "name": "Tag new customers",
            "trigger": {"type": "customer.created"},
            "actions": [{"type": "add_tag", "tag_id": tag["id"]}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    lead = await _lead(c, h)
    await A.process_tenant(tenant_id)  # the lead.created event: nothing to do
    await _customer(c, h, lead["id"])
    assert await A.process_tenant(tenant_id) >= 1
    got = (await c.get(f"/api/v1/leads/{lead['id']}", headers=h)).json()
    assert [t["name"] for t in got["tags"]] == ["Enrolled"]

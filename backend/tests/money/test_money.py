"""Step 6 (Decision log #34): invoices, installments, payments, links, emails, reminders.
No real money moves: gateways are faked and emails land in a folder."""

import asyncio
import email
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.events_model import Event
from app.core.modules import set_module
from app.core.tenancy import tenant_session
from app.modules.crm.models import Notification, Suppression, Task
from app.modules.money import gateways, links, nightly
from app.modules.money import service as S
from app.modules.money.models import GatewayAccount, Installment, Invoice, MoneyMessage
from app.modules.money.worker import send_one, sweep
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace

PDF = b"%PDF-1.4\n" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200


@pytest.fixture(autouse=True)
def folders(tmp_path):
    s = get_settings()
    old = s.files_dir, s.mail_outbox_dir
    s.files_dir, s.mail_outbox_dir = str(tmp_path / "files"), str(tmp_path / "outbox")
    yield tmp_path
    s.files_dir, s.mail_outbox_dir = old


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "money", True)
    return tenant_id, client_for(slug)


# ---------- a fake gateway ----------
class FakeGateway:
    def __init__(self):
        self.links: dict[str, dict] = {}
        self.calls: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        self.calls.append(f"{req.method} {path}")
        if path.endswith("/payment_links") and req.method == "GET":
            return httpx.Response(200, json={"items": []})
        if path == "/v1/balance":
            return httpx.Response(200, json={"available": []})
        if path == "/v1/payment_links" and req.method == "POST":
            n = f"plink_{len(self.links) + 1}"
            if req.url.host == "api.stripe.com":
                self.links[n] = {"status": "active"}
                return httpx.Response(200, json={"id": n, "url": f"https://buy.stripe.com/{n}"})
            body = json.loads(req.content)
            self.links[n] = {
                "status": "created",
                "amount": body["amount"],
                "currency": body["currency"],
            }
            return httpx.Response(200, json={"id": n, "short_url": f"https://rzp.io/i/{n}"})
        if path == "/v1/prices":
            return httpx.Response(200, json={"id": "price_1"})
        if path.startswith("/v1/payment_links/") and req.method == "GET":
            link = self.links[path.rsplit("/", 1)[1]]
            payments = link.get("payments", [])
            return httpx.Response(200, json={**link, "payments": payments})
        if path.endswith("/cancel") or path.startswith("/v1/payment_links/"):
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": {"description": "unknown"}})


@pytest.fixture
def fake(monkeypatch):
    gw = FakeGateway()
    monkeypatch.setattr(
        gateways, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(gw.handler))
    )
    return gw


def rzp_sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def rzp_paid(link_id: str, amount: int, pay_id: str = "pay_1", currency: str = "INR") -> bytes:
    return json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {"id": link_id, "amount": amount, "status": "paid"}},
                "payment": {"entity": {"id": pay_id, "amount": amount, "currency": currency}},
            },
        }
    ).encode()


# ---------- helpers ----------
async def _customer(c, h, phone="98765 43210", email_="rahul@example.com"):
    _, sources = await setup_ids(c, h)
    extra = {"identities": [{"type": "phone", "value": phone}, {"type": "email", "value": email_}]}
    lead = (await new_lead(c, h, sources["Website"], phone=phone, **extra)).json()
    r = await c.post(f"/api/v1/leads/{lead['id']}/customer", json={}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _rates(c, h):
    return {r["name"]: r["id"] for r in (await c.get("/api/v1/money/tax-rates", headers=h)).json()}


async def _draft(c, h, customer_id, lines=None):
    r = await c.post("/api/v1/invoices", json={"customer_id": customer_id}, headers=h)
    assert r.status_code == 201, r.text
    inv = r.json()
    if lines is None:
        gst = (await _rates(c, h))["GST 18%"]
        lines = [
            {
                "description": "Course fee",
                "quantity": 1,
                "unit_price_minor": 1_000_000,
                "tax_rate_id": gst,
            }
        ]
    r = await c.patch(
        f"/api/v1/invoices/{inv['id']}", json={"version": inv["version"], "lines": lines}, headers=h
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _issue(c, h, inv_id, **body):
    r = await c.post(f"/api/v1/invoices/{inv_id}/issue", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _pay(c, h, inv_id, amount, data=PDF, **extra):
    params = {
        "amount_minor": amount,
        "method": "bank",
        "paid_on": extra.pop("paid_on", None),
        "name": "proof.pdf",
        **extra,
    }
    return c.post(
        f"/api/v1/invoices/{inv_id}/payments",
        params={k: v for k, v in params.items() if v is not None},
        content=data,
        headers=h | {"Content-Type": "application/octet-stream"},
    )


async def _today(tenant_id):
    async with tenant_session(tenant_id) as db:
        return await S.company_today(db)


async def _events(tenant_id, prefix):
    async with tenant_session(tenant_id) as db:
        return [
            e.type
            for e in (await db.scalars(select(Event).order_by(Event.occurred_at))).all()
            if e.type.startswith(prefix)
        ]


async def _connect_razorpay(c, h, fake):
    entity = (await c.get("/api/v1/money/entities", headers=h)).json()[0]
    r = await c.post(
        "/api/v1/money/gateways",
        json={
            "entity_id": entity["id"],
            "gateway": "razorpay",
            "key_id": "rzp_test_key",
            "secret": "secret-123456",
            "webhook_secret": "whsec-abcdefgh",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- the life of an invoice ----------
async def test_draft_issue_numbering_lock_pdf_and_events(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    inv = await _draft(c, h, cust["id"])
    assert inv["status"] == "draft" and inv["number"] is None
    # 18% GST as CGST 9% + SGST 9% on ₹10,000
    assert (inv["subtotal_minor"], inv["tax_minor"], inv["total_minor"]) == (
        1_000_000,
        180_000,
        1_180_000,
    )
    assert {b["name"]: b["amount"] for b in inv["tax_breakdown"]} == {
        "CGST": 90_000,
        "SGST": 90_000,
    }
    day = await _today(tenant_id)
    issued = await _issue(c, h, inv["id"])
    first = day.year if day.month >= 4 else day.year - 1
    period = f"{first}-{(first + 1) % 100:02d}"
    assert issued["number"] == f"INV-{period}/0001"  # India: numbers restart each April
    assert issued["status"] == "issued" and issued["due_date"] == str(day + timedelta(days=7))
    assert (
        len(issued["installments"]) == 1 and issued["installments"][0]["amount_minor"] == 1_180_000
    )
    # Locked once issued.
    r = await c.patch(
        f"/api/v1/invoices/{inv['id']}",
        json={"version": issued["version"], "notes": "x"},
        headers=h,
    )
    assert r.status_code == 409
    assert (await c.delete(f"/api/v1/invoices/{inv['id']}", headers=h)).status_code == 409
    pdf = await c.get(f"/api/v1/invoices/{inv['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    assert "invoice.created" in await _events(tenant_id, "invoice.")
    timeline = (await c.get(f"/api/v1/leads/{cust['lead_id']}/activities", headers=h)).json()
    assert any(a["type_key"] == "invoice_issued" for a in timeline)
    second = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    assert second["number"] == f"INV-{period}/0002"


async def test_numbers_never_repeat_or_skip_when_issued_together(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    drafts = [await _draft(c, h, cust["id"]) for _ in range(5)]
    results = await asyncio.gather(
        *[c.post(f"/api/v1/invoices/{d['id']}/issue", json={}, headers=h) for d in drafts]
    )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    numbers = sorted(int(r.json()["number"].rsplit("/", 1)[1]) for r in results)
    assert numbers == [1, 2, 3, 4, 5]


async def test_installments_split_exactly_and_must_add_up(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    inv = await _draft(
        c, h, cust["id"], [{"description": "Fee", "quantity": 1, "unit_price_minor": 1_000_000}]
    )
    day = await _today(tenant_id)
    url = f"/api/v1/invoices/{inv['id']}/installments"
    r = await c.put(
        url, json={"count": 3, "first_due_date": str(day), "months_between": 1}, headers=h
    )
    assert r.status_code == 200, r.text
    assert [i["amount_minor"] for i in r.json()["installments"]] == [333_334, 333_333, 333_333]
    bad = [
        {"amount_minor": 500_000, "due_date": str(day)},
        {"amount_minor": 400_000, "due_date": str(day)},
    ]
    assert (await c.put(url, json={"items": bad}, headers=h)).status_code == 422
    issued = await _issue(c, h, inv["id"])
    assert issued["due_date"] == r.json()["installments"][-1]["due_date"]
    # Changing lines on a draft drops a schedule that no longer adds up.
    d2 = await _draft(
        c, h, cust["id"], [{"description": "Fee", "quantity": 1, "unit_price_minor": 900}]
    )
    await c.put(
        f"/api/v1/invoices/{d2['id']}/installments",
        json={"count": 3, "first_due_date": str(day)},
        headers=h,
    )
    d2 = (await c.get(f"/api/v1/invoices/{d2['id']}", headers=h)).json()
    lines = [{"description": "Fee", "quantity": 1, "unit_price_minor": 1000}]
    r = await c.patch(
        f"/api/v1/invoices/{d2['id']}", json={"version": d2["version"], "lines": lines}, headers=h
    )
    assert r.json()["installments"] == []


async def test_payments_oldest_first_balances_receipts_and_reversal(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    inv = await _draft(
        c, h, cust["id"], [{"description": "Fee", "quantity": 1, "unit_price_minor": 1_000_000}]
    )
    day = await _today(tenant_id)
    await c.put(
        f"/api/v1/invoices/{inv['id']}/installments",
        json={"count": 2, "first_due_date": str(day), "months_between": 1},
        headers=h,
    )
    await _issue(c, h, inv["id"])
    # Proof is required, and only real files.
    r = c.post(
        f"/api/v1/invoices/{inv['id']}/payments",
        params={"amount_minor": 100, "method": "bank", "paid_on": str(day), "name": "x.exe"},
        content=b"MZ\x90\x00" + b"x" * 50,
        headers=h | {"Content-Type": "application/octet-stream"},
    )
    assert (await r).status_code == 422
    assert (await _pay(c, h, inv["id"], 1_000_001, paid_on=str(day))).status_code == 422  # overpaid
    future = str(day + timedelta(days=2))
    assert (await _pay(c, h, inv["id"], 100, paid_on=future)).status_code == 422
    r = await _pay(c, h, inv["id"], 600_000, paid_on=str(day), reference="UTR123")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "partly_paid" and out["paid_minor"] == 600_000
    assert [i["paid_minor"] for i in out["installments"]] == [500_000, 100_000]
    assert [i["state"] for i in out["installments"]] == ["paid", "partly_paid"]
    p1 = out["payments"][0]
    assert p1["receipt_number"].startswith("RCT-") and p1["receipt_number"].endswith("/0001")
    assert p1["has_proof"]
    receipt = await c.get(f"/api/v1/payments/{p1['id']}/receipt", headers=h)
    assert receipt.status_code == 200 and receipt.content.startswith(b"%PDF")
    proof = await c.get(f"/api/v1/payments/{p1['id']}/proof", headers=h)
    assert proof.content == PDF and proof.headers["x-content-type-options"] == "nosniff"
    money = (await c.get(f"/api/v1/customers/{cust['id']}/money", headers=h)).json()
    assert money["balances"] == [
        {
            "currency": "INR",
            "billed_minor": 1_000_000,
            "paid_minor": 600_000,
            "due_minor": 400_000,
            "overdue_minor": 0,
        }
    ]
    r = await _pay(c, h, inv["id"], 400_000, paid_on=str(day))
    assert r.json()["status"] == "paid"
    assert (await _pay(c, h, inv["id"], 1, paid_on=str(day))).status_code == 409
    # A payment cannot be voided away; reverse it with a reason first.
    assert (
        await c.post(f"/api/v1/invoices/{inv['id']}/void", json={"reason": "x"}, headers=h)
    ).status_code == 409
    r = await c.post(f"/api/v1/payments/{p1['id']}/reverse", json={"reason": "Bounced"}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "partly_paid" and out["paid_minor"] == 400_000
    assert [i["paid_minor"] for i in out["installments"]] == [0, 400_000]
    assert (
        await c.post(f"/api/v1/payments/{p1['id']}/reverse", json={"reason": "x"}, headers=h)
    ).status_code == 409
    assert {"payment.received", "payment.reversed"} <= set(await _events(tenant_id, "payment."))


async def test_void_keeps_the_number_and_needs_a_reason(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    draft = await _draft(c, h, cust["id"])
    assert (
        await c.post(f"/api/v1/invoices/{draft['id']}/void", json={"reason": "x"}, headers=h)
    ).status_code == 422
    issued = await _issue(c, h, draft["id"])
    r = await c.post(
        f"/api/v1/invoices/{draft['id']}/void", json={"reason": "Wrong course"}, headers=h
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "void"
        and r.json()["number"] == issued["number"]
    )
    nxt = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    assert nxt["number"].endswith("/0002")  # the voided number stays used
    assert "invoice.voided" in await _events(tenant_id, "invoice.")
    # Drafts are deleted instead.
    d = await _draft(c, h, cust["id"])
    assert (await c.delete(f"/api/v1/invoices/{d['id']}", headers=h)).status_code == 204


# ---------- who may do what ----------
async def test_reps_see_only_their_customers_and_finance_runs_money(ws):
    tenant_id, c = ws
    _, rep = await login_as(tenant_id, "sales_user")
    _, other = await login_as(tenant_id, "sales_user")
    _, fin = await login_as(tenant_id, "finance")
    cust = await _customer(c, rep)
    inv = await _issue(c, rep, (await _draft(c, rep, cust["id"]))["id"])
    assert (await c.get(f"/api/v1/invoices/{inv['id']}", headers=other)).status_code == 404
    assert (await c.get("/api/v1/invoices", headers=other)).json()["total"] == 0
    assert (await c.get(f"/api/v1/invoices/{inv['id']}", headers=fin)).status_code == 200
    # Reps cannot void, reverse or change money settings; Finance can.
    assert (
        await c.post(f"/api/v1/invoices/{inv['id']}/void", json={"reason": "x"}, headers=rep)
    ).status_code == 403
    assert (await c.get("/api/v1/money/gateways", headers=rep)).status_code == 403
    day = await _today(tenant_id)
    paid = (await _pay(c, rep, inv["id"], 1000, paid_on=str(day))).json()
    pid = paid["payments"][0]["id"]
    assert (
        await c.post(f"/api/v1/payments/{pid}/reverse", json={"reason": "x"}, headers=rep)
    ).status_code == 403
    assert (
        await c.post(f"/api/v1/payments/{pid}/reverse", json={"reason": "x"}, headers=fin)
    ).status_code == 200
    assert (
        await c.post(f"/api/v1/invoices/{inv['id']}/void", json={"reason": "x"}, headers=fin)
    ).status_code == 200
    assert (await c.get("/api/v1/money/gateways", headers=fin)).status_code == 200


async def test_companies_never_see_each_others_money(ws, client_for):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    inv = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    other_id, other_slug = await make_workspace()
    async with tenant_session(other_id) as db:
        await set_module(db, other_id, "money", True)
    c2 = client_for(other_slug)
    _, h2 = await login_as(other_id, "admin")
    assert (await c2.get(f"/api/v1/invoices/{inv['id']}", headers=h2)).status_code == 404
    assert (await c2.get(f"/api/v1/invoices/{inv['id']}/pdf", headers=h2)).status_code == 404
    assert (await c2.get("/api/v1/invoices", headers=h2)).json()["total"] == 0
    assert (await c2.get("/api/v1/money/aging", headers=h2)).json() == []


async def test_money_switched_off_answers_404(client_for):
    tenant_id, slug = await make_workspace()
    c = client_for(slug)
    _, h = await login_as(tenant_id, "admin")
    assert (await c.get("/api/v1/invoices", headers=h)).status_code == 404


# ---------- gateways ----------
async def test_razorpay_link_webhook_repeat_bad_signature_and_wrong_amount(ws, fake):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    acct = await _connect_razorpay(c, h, fake)
    assert acct["secret_hint"] == "••••3456" and "secret" not in acct
    async with tenant_session(tenant_id) as db:
        stored = await db.get(GatewayAccount, uuid.UUID(acct["id"]))
        assert "secret-123456" not in stored.secret_enc  # encrypted at rest
    cust = await _customer(c, h)
    inv = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    r = await c.post(f"/api/v1/invoices/{inv['id']}/links", json={}, headers=h)
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["url"] == "https://rzp.io/i/plink_1" and link["amount_minor"] == 1_180_000
    again = await c.post(f"/api/v1/invoices/{inv['id']}/links", json={}, headers=h)
    assert again.json()["id"] == link["id"]  # same amount: same link
    hook = f"/api/v1/webhooks/razorpay/{acct['id']}"
    body = rzp_paid("plink_1", 1_180_000)
    bad = await c.post(
        hook, content=body, headers={"X-Razorpay-Signature": "nope", "X-Razorpay-Event-Id": "e1"}
    )
    assert bad.status_code == 403
    sig = {"X-Razorpay-Signature": rzp_sign("whsec-abcdefgh", body), "X-Razorpay-Event-Id": "e1"}
    r = await c.post(hook, content=body, headers=sig)
    assert r.status_code == 200 and r.json()["result"] == "applied", r.text
    again = await c.post(hook, content=body, headers=sig)
    assert again.json()["result"] == "duplicate"
    sig2 = sig | {"X-Razorpay-Event-Id": "e2"}  # same payment, new event id: still once
    assert (await c.post(hook, content=body, headers=sig2)).json()["result"] == "ignored"
    out = (await c.get(f"/api/v1/invoices/{inv['id']}", headers=h)).json()
    assert out["status"] == "paid" and len(out["payments"]) == 1
    assert out["payments"][0]["method"] == "gateway" and out["links"][0]["status"] == "paid"
    # A payment that does not match its link is kept for Finance, never applied.
    inv2 = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    await c.post(f"/api/v1/invoices/{inv2['id']}/links", json={}, headers=h)
    wrong = rzp_paid("plink_2", 5, pay_id="pay_2")
    r = await c.post(
        hook,
        content=wrong,
        headers={
            "X-Razorpay-Signature": rzp_sign("whsec-abcdefgh", wrong),
            "X-Razorpay-Event-Id": "e3",
        },
    )
    assert r.json()["result"] == "flagged"
    out2 = (await c.get(f"/api/v1/invoices/{inv2['id']}", headers=h)).json()
    assert out2["paid_minor"] == 0 and out2["links"][0]["status"] == "flagged"
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(
            select(Notification.id).where(Notification.kind == "payment_flagged")
        )


async def test_stripe_webhook_signature_and_age(ws, fake):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    entity = (await c.get("/api/v1/money/entities", headers=h)).json()[0]
    acct = (
        await c.post(
            "/api/v1/money/gateways",
            json={
                "entity_id": entity["id"],
                "gateway": "stripe",
                "secret": "sk_test_12345678",
                "webhook_secret": "whsec_stripe1",
            },
            headers=h,
        )
    ).json()
    cust = await _customer(c, h)
    inv = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    link = (await c.post(f"/api/v1/invoices/{inv['id']}/links", json={}, headers=h)).json()
    assert link["url"].startswith("https://buy.stripe.com/")

    def signed(stamp: int, evt: str):
        body = json.dumps(
            {
                "id": evt,
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_1",
                        "payment_link": "plink_1",
                        "payment_status": "paid",
                        "amount_total": 1_180_000,
                        "currency": "inr",
                        "payment_intent": "pi_1",
                    }
                },
            }
        ).encode()
        v1 = hmac.new(b"whsec_stripe1", f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
        return body, {"Stripe-Signature": f"t={stamp},v1={v1}"}

    hook = f"/api/v1/webhooks/stripe/{acct['id']}"
    body, hdr = signed(int(time.time()) - 3600, "evt_old")
    assert (await c.post(hook, content=body, headers=hdr)).status_code == 403
    body, hdr = signed(int(time.time()), "evt_1")
    r = await c.post(hook, content=body, headers=hdr)
    assert r.json()["result"] == "applied", r.text
    # The webhook belongs to Stripe; posting it to the Razorpay address is refused.
    assert (
        await c.post(f"/api/v1/webhooks/razorpay/{acct['id']}", content=body, headers=hdr)
    ).status_code == 404


async def test_nightly_check_catches_a_missed_webhook(ws, fake):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    await _connect_razorpay(c, h, fake)
    cust = await _customer(c, h)
    inv = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    await c.post(f"/api/v1/invoices/{inv['id']}/links", json={}, headers=h)
    fake.links["plink_1"] |= {
        "status": "paid",
        "payments": [{"payment_id": "pay_9", "amount": 1_180_000, "status": "captured"}],
    }
    async with tenant_session(tenant_id) as db:
        from app.modules.money.models import PaymentLink

        await db.execute(
            update(PaymentLink).values(created_at=PaymentLink.created_at - timedelta(hours=1))
        )
    async with tenant_session(tenant_id) as db:
        assert await links.check_open_links(db) == 1
    out = (await c.get(f"/api/v1/invoices/{inv['id']}", headers=h)).json()
    assert out["status"] == "paid"


# ---------- emails ----------
async def _mailbox(c, h):
    r = await c.put(
        "/api/v1/money/mailbox",
        json={
            "host": "smtp.gmail.com",
            "port": 587,
            "security": "starttls",
            "username": "accounts@acme.in",
            "password": "app-password",
            "from_name": "Acme Accounts",
            "from_email": "accounts@acme.in",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert "app-password" not in r.text


async def test_invoice_and_receipt_emails_from_the_company_mailbox(ws, folders):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    draft = await _draft(c, h, cust["id"])
    issued = await _issue(c, h, draft["id"])
    # No mailbox yet: nothing is queued automatically, and a manual send says why.
    assert issued["messages"] == []
    r = await c.post(f"/api/v1/invoices/{draft['id']}/email", headers=h)
    assert r.status_code == 422 and "mailbox" in r.json()["detail"]
    await _mailbox(c, h)
    r = await c.post(f"/api/v1/invoices/{draft['id']}/email", headers=h)
    assert r.status_code == 200 and r.json()["messages"][0]["status"] == "queued"
    day = await _today(tenant_id)
    await _pay(c, h, draft["id"], 1000, paid_on=str(day))
    async with tenant_session(tenant_id) as db:
        ids = (await db.scalars(select(MoneyMessage.id).order_by(MoneyMessage.created_at))).all()
    for mid in ids:
        assert await send_one(tenant_id, mid, last_try=True) == "sent"
    files = sorted((folders / "outbox").glob("*.eml"))
    assert len(files) == 2
    first = email.message_from_bytes(files[0].read_bytes())
    assert (
        first["To"] == "rahul@example.com" and first["From"] == "Acme Accounts <accounts@acme.in>"
    )
    assert first["Subject"].startswith(f"Invoice {issued['number']}")
    parts = [p.get_filename() for p in first.walk() if p.get_filename()]
    assert parts == [f"{issued['number']}.pdf"]
    second = email.message_from_bytes(files[1].read_bytes())
    assert second["Subject"].startswith("Receipt RCT-")
    timeline = (await c.get(f"/api/v1/leads/{cust['lead_id']}/activities", headers=h)).json()
    assert sum(a["type_key"] == "invoice_emailed" for a in timeline) == 2


async def test_unsubscribed_customers_get_no_email_and_failures_are_kept(ws, folders):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    await _mailbox(c, h)
    cust = await _customer(c, h, phone="98765 00001", email_="gone@example.com")
    async with tenant_session(tenant_id) as db:
        db.add(
            Suppression(
                tenant_id=tenant_id,
                channel="email",
                value_normalized="gone@example.com",
                reason="opt_out",
            )
        )
    inv = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    assert inv["messages"] == []
    r = await c.post(f"/api/v1/invoices/{inv['id']}/email", headers=h)
    assert r.status_code == 422 and "unsubscribed" in r.json()["detail"]
    # A message that can never go is marked failed (the mailbox was removed).
    cust2 = await _customer(c, h, phone="98765 00002", email_="ok@example.com")
    inv2 = await _issue(c, h, (await _draft(c, h, cust2["id"]))["id"])
    assert inv2["messages"][0]["status"] == "queued"
    await c.delete("/api/v1/money/mailbox", headers=h)
    async with tenant_session(tenant_id) as db:
        mid = await db.scalar(select(MoneyMessage.id))
        await db.execute(
            update(MoneyMessage).values(created_at=MoneyMessage.created_at - timedelta(minutes=5))
        )
    assert await sweep([tenant_id]) == 0
    async with tenant_session(tenant_id) as db:
        msg = await db.get(MoneyMessage, mid)
        assert msg.status == "failed" and "mailbox" in msg.error


async def test_mailbox_on_a_private_address_is_refused_in_production(monkeypatch):
    from app.core.errors import Invalid
    from app.modules.money import mailbox

    monkeypatch.setattr(get_settings(), "environment", "prod")
    with pytest.raises(Invalid):
        mailbox._check_host("127.0.0.1", 587)
    with pytest.raises(Invalid):
        mailbox._check_host("smtp.example.com", 8080)


# ---------- reminders, repeat, aging ----------
async def test_reminders_overdue_task_events_and_no_repeats(ws):
    tenant_id, c = ws
    _, rep_id_h = await login_as(tenant_id, "sales_user")
    cust = await _customer(c, rep_id_h)
    inv = await _issue(c, rep_id_h, (await _draft(c, rep_id_h, cust["id"]))["id"])
    day = await _today(tenant_id)
    async with tenant_session(tenant_id) as db:
        await db.execute(update(Installment).values(due_date=day - timedelta(days=40)))
    async with tenant_session(tenant_id) as db:
        assert await nightly.remind(db) == 1
    async with tenant_session(tenant_id) as db:
        assert await nightly.remind(db) == 0  # once per week while overdue
        assert await db.scalar(select(Task.id).where(Task.created_from == "money"))
        assert await db.scalar(
            select(Notification.id).where(Notification.kind == "payment_overdue")
        )
    assert "payment.overdue" in await _events(tenant_id, "payment.")
    aging = (await c.get("/api/v1/money/aging", headers=rep_id_h)).json()
    assert aging[0]["buckets"] == {"0-30": 0, "31-60": 1_180_000, "61-90": 0, "90+": 0}
    listed = (await c.get("/api/v1/invoices", params={"overdue": True}, headers=rep_id_h)).json()
    assert [i["id"] for i in listed["items"]] == [inv["id"]]
    money = (await c.get(f"/api/v1/customers/{cust['id']}/money", headers=rep_id_h)).json()
    assert money["balances"][0]["overdue_minor"] == 1_180_000


async def test_due_soon_reminder_then_due_today(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    day = await _today(tenant_id)
    async with tenant_session(tenant_id) as db:
        await db.execute(update(Installment).values(due_date=day + timedelta(days=2)))
    async with tenant_session(tenant_id) as db:
        assert await nightly.remind(db) == 1
    async with tenant_session(tenant_id) as db:
        await db.execute(update(Installment).values(due_date=day))
    async with tenant_session(tenant_id) as db:
        assert await nightly.remind(db) == 1
    assert (await _events(tenant_id, "payment.")).count("payment.due") == 2


async def test_repeat_invoice_issues_the_next_one(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    inv = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    r = await c.post(f"/api/v1/invoices/{inv['id']}/repeat", json={"months": 1}, headers=h)
    assert r.status_code == 200 and r.json()["repeat_next_date"]
    day = await _today(tenant_id)
    async with tenant_session(tenant_id) as db:
        await db.execute(update(Invoice).values(repeat_next_date=day))
    async with tenant_session(tenant_id) as db:
        assert await nightly.repeat(db) == 1
    async with tenant_session(tenant_id) as db:
        assert await nightly.repeat(db) == 0
    items = (await c.get("/api/v1/invoices", headers=h)).json()["items"]
    assert len(items) == 2 and {i["status"] for i in items} == {"issued"}
    assert items[0]["total_minor"] == items[1]["total_minor"]


async def test_entity_settings_and_tax_rate_changes_never_touch_old_invoices(ws):
    tenant_id, c = ws
    _, h = await login_as(tenant_id, "admin")
    cust = await _customer(c, h)
    inv = await _issue(c, h, (await _draft(c, h, cust["id"]))["id"])
    gst = (await _rates(c, h))["GST 18%"]
    r = await c.patch(
        f"/api/v1/money/tax-rates/{gst}",
        json={"parts": [{"name": "GST", "rate_bp": 2800}]},
        headers=h,
    )
    assert r.status_code == 200
    again = (await c.get(f"/api/v1/invoices/{inv['id']}", headers=h)).json()
    assert again["tax_minor"] == 180_000 and again["lines"][0]["tax_minor"] == 180_000
    entity = (await c.get("/api/v1/money/entities", headers=h)).json()[0]
    assert entity["country"] == "IN" and entity["currency"] == "INR" and entity["yearly_reset"]
    r = await c.patch(f"/api/v1/money/entities/{entity['id']}", json={"currency": "USD"}, headers=h)
    assert r.status_code == 409  # it has invoices
    r = await c.patch(
        f"/api/v1/money/entities/{entity['id']}", json={"next_invoice_number": 1}, headers=h
    )
    assert r.status_code == 422  # numbers only move forward
    r = await c.post(
        "/api/v1/money/entities",
        json={"name": "Dubai", "legal_name": "Acme FZ-LLC", "country": "ae", "currency": "aed"},
        headers=h,
    )
    assert (
        r.status_code == 201
        and r.json()["currency"] == "AED"
        and r.json()["next_number"] == "INV-0001"
    )
    # A draft cannot move to an entity in another currency once it has lines.
    d = await _draft(c, h, cust["id"])
    r = await c.patch(
        f"/api/v1/invoices/{d['id']}",
        json={"version": d["version"], "entity_id": r.json()["id"]},
        headers=h,
    )
    assert r.status_code == 422

"""Payment gateways behind one interface (Decision log #34). Nothing else in Core talks to a
gateway, so another provider (e.g. an orchestrator such as Hyperswitch) is one more class here.

The customer always pays on the gateway's own hosted page; Core only creates the link, checks
signed webhooks and, nightly, asks about links still open (in case a webhook was missed).

- Razorpay: Payment Links API; webhook `payment_link.paid`, signed with HMAC-SHA256 of the body
  (`X-Razorpay-Signature`), event id in `X-Razorpay-Event-Id`.
- Stripe: a Price plus a Payment Link limited to one completed payment; webhook
  `checkout.session.completed`, signed `Stripe-Signature: t=…,v1=…` over "t.body", 5-minute window.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import httpx

from app.core.errors import Invalid

TIMEOUT = httpx.Timeout(15.0)
STRIPE_TOLERANCE_S = 300


@dataclass(frozen=True)
class Keys:
    gateway: str
    key_id: str | None
    secret: str
    webhook_secret: str


@dataclass(frozen=True)
class NewLink:
    link_id: str
    url: str


@dataclass(frozen=True)
class Paid:
    """A payment the gateway says was completed for one of our links."""

    event_id: str
    link_id: str
    payment_id: str
    amount_minor: int
    currency: str


@dataclass(frozen=True)
class Webhook:
    event_id: str
    event_type: str
    payload: dict
    paid: Paid | None  # None: an event we do not act on


class GatewayError(Invalid):
    pass


def _client() -> httpx.AsyncClient:
    """Swapped out in tests for a fake gateway (no real money, no network)."""
    return httpx.AsyncClient(timeout=TIMEOUT)


def _fail(resp: httpx.Response, what: str) -> GatewayError:
    try:
        body = resp.json()
        msg = (body.get("error") or {}).get("description") or (body.get("error") or {}).get(
            "message"
        )
    except ValueError:
        msg = None
    return GatewayError(f"{what}: {msg or f'the gateway answered {resp.status_code}'}")


# ---------- Razorpay ----------
class Razorpay:
    BASE = "https://api.razorpay.com/v1"

    def __init__(self, keys: Keys):
        self.keys = keys
        self.auth = (keys.key_id or "", keys.secret)

    async def check(self) -> None:
        async with _client() as c:
            r = await c.get(f"{self.BASE}/payment_links", params={"count": 1}, auth=self.auth)
        if r.status_code != 200:
            raise _fail(r, "Razorpay did not accept these keys")

    async def create(
        self, *, amount: int, currency: str, description: str, reference: str, customer: dict
    ) -> NewLink:
        body = {
            "amount": amount,
            "currency": currency,
            "description": description[:2048],
            "reference_id": reference[:40],
            "customer": {k: v for k, v in customer.items() if v},
            # Core sends the link itself (email / WhatsApp); Razorpay stays quiet.
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        }
        async with _client() as c:
            r = await c.post(f"{self.BASE}/payment_links", json=body, auth=self.auth)
        if r.status_code not in (200, 201):
            raise _fail(r, "Razorpay could not create the link")
        data = r.json()
        return NewLink(link_id=data["id"], url=data["short_url"])

    async def cancel(self, link_id: str) -> None:
        async with _client() as c:
            r = await c.post(f"{self.BASE}/payment_links/{link_id}/cancel", auth=self.auth)
        if r.status_code not in (200, 400):  # 400: already paid / cancelled
            raise _fail(r, "Razorpay could not cancel the link")

    async def lookup(self, link_id: str) -> Paid | None:
        async with _client() as c:
            r = await c.get(f"{self.BASE}/payment_links/{link_id}", auth=self.auth)
        if r.status_code != 200:
            raise _fail(r, "Razorpay could not find the link")
        data = r.json()
        if data.get("status") != "paid":
            return None
        pay = next((p for p in data.get("payments") or [] if p.get("status") == "captured"), None)
        if pay is None:
            return None
        return Paid(
            event_id=f"lookup:{pay['payment_id']}",
            link_id=link_id,
            payment_id=pay["payment_id"],
            amount_minor=int(pay["amount"]),
            currency=data["currency"],
        )

    def webhook(self, headers: dict, body: bytes) -> Webhook:
        sig = headers.get("x-razorpay-signature", "")
        good = hmac.new(self.keys.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        if not sig or not hmac.compare_digest(sig, good):
            raise GatewayError("Bad signature")
        data = json.loads(body)
        event_type = data.get("event", "")
        event_id = headers.get("x-razorpay-event-id") or hashlib.sha256(body).hexdigest()
        paid = None
        if event_type == "payment_link.paid":
            link = data["payload"]["payment_link"]["entity"]
            pay = data["payload"]["payment"]["entity"]
            paid = Paid(
                event_id=event_id,
                link_id=link["id"],
                payment_id=pay["id"],
                amount_minor=int(pay["amount"]),
                currency=pay["currency"],
            )
        return Webhook(event_id=event_id, event_type=event_type, payload=data, paid=paid)


# ---------- Stripe ----------
class Stripe:
    BASE = "https://api.stripe.com/v1"

    def __init__(self, keys: Keys):
        self.keys = keys
        self.auth = (keys.secret, "")

    async def check(self) -> None:
        async with _client() as c:
            r = await c.get(f"{self.BASE}/balance", auth=self.auth)
        if r.status_code != 200:
            raise _fail(r, "Stripe did not accept this key")

    async def create(
        self, *, amount: int, currency: str, description: str, reference: str, customer: dict
    ) -> NewLink:
        async with _client() as c:
            price = await c.post(
                f"{self.BASE}/prices",
                auth=self.auth,
                data={
                    "currency": currency.lower(),
                    "unit_amount": str(amount),
                    "product_data[name]": description[:250],
                },
            )
            if price.status_code != 200:
                raise _fail(price, "Stripe could not create the price")
            r = await c.post(
                f"{self.BASE}/payment_links",
                auth=self.auth,
                data={
                    "line_items[0][price]": price.json()["id"],
                    "line_items[0][quantity]": "1",
                    "restrictions[completed_sessions][limit]": "1",
                    "metadata[reference]": reference[:40],
                },
            )
        if r.status_code != 200:
            raise _fail(r, "Stripe could not create the link")
        data = r.json()
        return NewLink(link_id=data["id"], url=data["url"])

    async def cancel(self, link_id: str) -> None:
        async with _client() as c:
            r = await c.post(
                f"{self.BASE}/payment_links/{link_id}", auth=self.auth, data={"active": "false"}
            )
        if r.status_code != 200:
            raise _fail(r, "Stripe could not switch the link off")

    async def lookup(self, link_id: str) -> Paid | None:
        async with _client() as c:
            r = await c.get(
                f"{self.BASE}/checkout/sessions",
                auth=self.auth,
                params={"payment_link": link_id, "limit": 3},
            )
        if r.status_code != 200:
            raise _fail(r, "Stripe could not look up the link")
        s = next((s for s in r.json().get("data", []) if s.get("payment_status") == "paid"), None)
        if s is None:
            return None
        return Paid(
            event_id=f"lookup:{s['id']}",
            link_id=link_id,
            payment_id=s.get("payment_intent") or s["id"],
            amount_minor=int(s["amount_total"]),
            currency=s["currency"].upper(),
        )

    def webhook(self, headers: dict, body: bytes) -> Webhook:
        parts = dict(
            p.split("=", 1) for p in headers.get("stripe-signature", "").split(",") if "=" in p
        )
        stamp, sig = parts.get("t", ""), parts.get("v1", "")
        signed = f"{stamp}.".encode() + body
        good = hmac.new(self.keys.webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
        if not (stamp.isdigit() and sig and hmac.compare_digest(sig, good)):
            raise GatewayError("Bad signature")
        if abs(time.time() - int(stamp)) > STRIPE_TOLERANCE_S:
            raise GatewayError("The webhook is too old")
        data = json.loads(body)
        event_type = data.get("type", "")
        paid = None
        obj = (data.get("data") or {}).get("object") or {}
        if (
            event_type == "checkout.session.completed"
            and obj.get("payment_link")
            and obj.get("payment_status") == "paid"
        ):
            paid = Paid(
                event_id=data["id"],
                link_id=obj["payment_link"],
                payment_id=obj.get("payment_intent") or obj["id"],
                amount_minor=int(obj["amount_total"]),
                currency=obj["currency"].upper(),
            )
        return Webhook(event_id=data["id"], event_type=event_type, payload=data, paid=paid)


GATEWAYS = {"razorpay": Razorpay, "stripe": Stripe}


def gateway(keys: Keys) -> Razorpay | Stripe:
    return GATEWAYS[keys.gateway](keys)

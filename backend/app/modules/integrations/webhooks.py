"""Outbound webhooks (spec §11, Decision log #37).

Every ten seconds the worker turns each company's new events into one delivery per endpoint
that asked for that event, then sends deliveries that are due. A delivery is a POST of
`{id, type, occurred_at, data}` signed like automation webhooks:
`X-Versnq-Signature: sha256=HMAC(secret, "<X-Versnq-Timestamp>.<body>")`, plus
`X-Versnq-Event` and `X-Versnq-Delivery`. The event id in the body lets receivers ignore a
repeat. Any 2xx answer is success; otherwise it is retried 1 min, 5 min, 30 min, 2 h, 6 h, 12 h
and 24 h later (8 tries), then marked failed. An endpoint failing for 3 days is switched off and
admins are told. The address is checked again at every send (public https only, no redirects).
"""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.core.events_model import Event
from app.core.secrets import decrypt
from app.core.tenancy import tenant_session
from app.modules.crm.automation import check_url, sign
from app.modules.crm.notify import notify
from app.modules.integrations.models import WebhookDelivery, WebhookEndpoint
from app.modules.roles.models import Role
from app.modules.users.models import User

RETRY_DELAYS = [60, 300, 1800, 7200, 21600, 43200, 86400]  # seconds after try 1, 2, ... 7
MAX_TRIES = len(RETRY_DELAYS) + 1
SWITCH_OFF_AFTER = timedelta(days=3)
LEASE = timedelta(minutes=2)  # a delivery being sent is not picked up again meanwhile
EVENT_BATCH = 500
SEND_BATCH = 20


def now() -> datetime:
    return datetime.now(UTC)


def _client() -> httpx.AsyncClient:  # patched in tests
    return httpx.AsyncClient(timeout=10, follow_redirects=False)


def body_for(event: Event) -> str:
    payload = event.payload or {}
    data = {k: v for k, v in payload.items() if k not in ("_via", "_actor")}
    # who caused it, so a subscriber (ACE) can skip its own writes (Decision log #43)
    data |= payload.get("_actor") or {"actor_user_id": None, "actor_type": "system"}
    return json.dumps(
        {
            "id": str(event.id),
            "type": event.type,
            "occurred_at": event.occurred_at.isoformat(),
            "data": data,
        }
    )


def wants(endpoint: WebhookEndpoint, event_type: str) -> bool:
    return "*" in endpoint.events or event_type in endpoint.events


async def fan_out(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """New events → deliveries. Events nobody listens to are simply marked as handled."""
    endpoints = (
        await db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.is_active.is_(True)))
    ).all()
    if not endpoints:
        await db.execute(
            update(Event).where(Event.published_at.is_(None)).values(published_at=now())
        )
        return 0
    events = (
        await db.scalars(
            select(Event)
            .where(Event.published_at.is_(None))
            .order_by(Event.occurred_at, Event.id)
            .limit(EVENT_BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    made = 0
    for event in events:
        for ep in endpoints:
            if wants(ep, event.type) and event.occurred_at >= ep.created_at:
                db.add(
                    WebhookDelivery(
                        tenant_id=tenant_id,
                        endpoint_id=ep.id,
                        event_id=event.id,
                        event_type=event.type,
                        body=body_for(event),
                        status="pending",
                        attempts=0,
                        next_try_at=now(),
                    )
                )
                made += 1
        event.published_at = now()
    await db.flush()
    return made


async def post(url: str, secret: str, delivery_id: uuid.UUID, event_type: str, body: str) -> dict:
    """One attempt. Never raises: returns code / error / duration / snippet."""
    started = time.perf_counter()
    result: dict = {"code": None, "error": None, "snippet": None}
    try:
        check_url(url)
        ts = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Versnq-Core-Webhooks/1",
            "X-Versnq-Event": event_type,
            "X-Versnq-Delivery": str(delivery_id),
            "X-Versnq-Timestamp": str(ts),
            "X-Versnq-Signature": f"sha256={sign(secret, ts, body)}",
        }
        async with _client() as client:
            r = await client.post(url, content=body, headers=headers)
        result["code"] = r.status_code
        result["snippet"] = r.text[:500] if r.text else None
        if not 200 <= r.status_code < 300:
            result["error"] = f"Answered {r.status_code}"
    except Invalid as e:
        result["error"] = str(e.detail)[:300]
    except httpx.TimeoutException:
        result["error"] = "No answer within 10 seconds"
    except httpx.HTTPError as e:
        result["error"] = f"Could not connect ({type(e).__name__})"
    result["ms"] = int((time.perf_counter() - started) * 1000)
    return result


async def _admins(db: AsyncSession) -> list[uuid.UUID]:
    return list(
        (
            await db.scalars(
                select(User.id)
                .join(Role, Role.id == User.role_id)
                .where(Role.key.in_(["owner", "admin"]), User.status == "active")
            )
        ).all()
    )


async def record(db: AsyncSession, d: WebhookDelivery, ep: WebhookEndpoint, res: dict) -> None:
    """Save one attempt's result; schedule the next try, or finish."""
    t = now()
    d.attempts += 1
    d.last_status_code, d.last_error = res["code"], res["error"]
    d.last_duration_ms, d.response_snippet = res["ms"], res["snippet"]
    if res["error"] is None:
        d.status, d.delivered_at, d.next_try_at = "ok", t, None
        ep.failing_since = None
        return
    if d.attempts >= MAX_TRIES or d.event_type == "ping":
        d.status, d.next_try_at = "failed", None
    else:
        d.next_try_at = t + timedelta(seconds=RETRY_DELAYS[d.attempts - 1])
    if d.event_type == "ping":
        return  # a test send never switches an endpoint off
    if ep.failing_since is None:
        ep.failing_since = t
    elif ep.is_active and t - ep.failing_since >= SWITCH_OFF_AFTER:
        ep.is_active = False
        ep.switched_off_reason = (
            f"Switched off: failing since {ep.failing_since:%d %b %Y %H:%M} UTC"
        )
        await db.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.endpoint_id == ep.id, WebhookDelivery.status == "pending")
            .values(status="failed", next_try_at=None, last_error="Endpoint switched off")
        )
        await notify(
            db, ep.tenant_id, await _admins(db), "webhook",
            f"Webhook switched off after 3 days of failures: {ep.name}",
        )  # fmt: skip


async def send_due(tenant_id: uuid.UUID) -> int:
    """Send the deliveries that are due (claimed first, so two workers never send one twice)."""
    async with tenant_session(tenant_id) as db:
        due = (
            await db.scalars(
                select(WebhookDelivery)
                .where(WebhookDelivery.status == "pending", WebhookDelivery.next_try_at <= now())
                .order_by(WebhookDelivery.next_try_at)
                .limit(SEND_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not due:
            return 0
        ids = [d.id for d in due]
        for d in due:
            d.next_try_at = now() + LEASE
        eps = {
            e.id: e
            for e in (
                await db.scalars(
                    select(WebhookEndpoint).where(
                        WebhookEndpoint.id.in_({d.endpoint_id for d in due})
                    )
                )
            ).all()
        }
        jobs = [
            (
                d.id,
                eps[d.endpoint_id].url,
                decrypt(eps[d.endpoint_id].secret_enc),
                d.event_type,
                d.body,
            )
            for d in due
        ]
    results = await asyncio.gather(*(post(u, s, i, t, b) for i, u, s, t, b in jobs))
    async with tenant_session(tenant_id) as db:
        for delivery_id, res in zip(ids, results, strict=True):
            d = await db.get(WebhookDelivery, delivery_id, with_for_update=True)
            ep = await db.get(WebhookEndpoint, d.endpoint_id, with_for_update=True)
            if d.status == "pending":
                await record(db, d, ep, res)
    return len(ids)


async def test_send(db: AsyncSession, ep: WebhookEndpoint) -> WebhookDelivery:
    d = WebhookDelivery(
        id=uuid.uuid4(), tenant_id=ep.tenant_id, endpoint_id=ep.id, event_type="ping",
        status="pending", attempts=0,
    )  # fmt: skip
    d.body = json.dumps(
        {"id": str(d.id), "type": "ping", "occurred_at": now().isoformat(), "data": {}}
    )
    db.add(d)
    res = await post(ep.url, decrypt(ep.secret_enc), d.id, "ping", d.body)
    await record(db, d, ep, res)
    await db.flush()
    return d


async def resend(db: AsyncSession, old: WebhookDelivery) -> WebhookDelivery:
    d = WebhookDelivery(
        id=uuid.uuid4(), tenant_id=old.tenant_id, endpoint_id=old.endpoint_id,
        event_id=old.event_id, event_type=old.event_type, body=old.body, status="pending",
        attempts=0, next_try_at=now(),
    )  # fmt: skip
    db.add(d)
    await db.flush()
    return d


async def run_all(tenant_ids: list[uuid.UUID]) -> dict:
    made = sent = 0
    for t in tenant_ids:
        async with tenant_session(t) as db:
            made += await fan_out(db, t)
        sent += await send_due(t)
    return {"deliveries": made, "sent": sent}

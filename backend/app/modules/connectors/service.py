"""Sending calls and WhatsApp messages to the company's connected CRM.

Every ten seconds, for each company with a connected CRM:
1. new call.logged / message.received / message.sent (WhatsApp) events since the connection's
   cursor become crm_syncs rows (one per event: a repeat is harmless);
2. due rows are sent one at a time (CRMs limit requests per second): the lead is found in the
   CRM by its id kept on Core's lead, else by phone; if it isn't there, it's created when the
   company asked for that (calls from a number the rep said is a new lead), else skipped.
A failure is tried again 1 min, 5 min, 30 min, 2 h and 6 h later, then marked failed; wrong keys
or a refused request fail at once. The company's settings page shows the latest sends.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events_model import Event
from app.core.secrets import decrypt
from app.core.tenancy import tenant_session
from app.modules.calls.models import Call
from app.modules.connectors import base as B
from app.modules.connectors.custom import CustomCrm
from app.modules.connectors.leadsquared import LeadSquared
from app.modules.connectors.models import CrmConnection, CrmSync
from app.modules.crm.models import ExternalRef, Lead, LeadIdentity
from app.modules.engage.models import Message
from app.modules.users.models import User

RETRY_DELAYS = [60, 300, 1800, 7200, 21600]
MAX_TRIES = len(RETRY_DELAYS) + 1
LEASE = timedelta(minutes=2)
BATCH = 20
DEFAULTS = {"send_calls": True, "send_whatsapp": True, "create_leads": True}


def now() -> datetime:
    return datetime.now(UTC)


def options(conn: CrmConnection) -> dict:
    return {**DEFAULTS, **(conn.config or {})}


def connector_for(conn: CrmConnection) -> B.Connector:
    secret = decrypt(conn.secret_enc)
    if conn.provider == "leadsquared":
        return LeadSquared(conn.host or "", json.loads(secret), conn.config or {})
    return CustomCrm(conn.config or {}, secret)


def _kind(event: Event) -> str | None:
    if event.type == "call.logged":
        return "call"
    channel = (event.payload or {}).get("channel")
    if event.type in ("message.received", "message.sent") and channel in (
        "whatsapp", "whatsapp_extension"
    ):  # fmt: skip
        return "whatsapp"
    return None


async def collect(db: AsyncSession, conn: CrmConnection) -> int:
    """New events since the cursor → sends (only what the company chose to send)."""
    opts = options(conn)
    events = (
        await db.scalars(
            select(Event)
            .where(
                Event.type.in_(("call.logged", "message.received", "message.sent")),
                Event.occurred_at >= conn.cursor_at,
            )
            .order_by(Event.occurred_at)
            .limit(500)
        )
    ).all()
    made = 0
    for e in events:
        kind = _kind(e)
        p = e.payload or {}
        ref = p.get("call_id") if kind == "call" else p.get("message_id")
        if not kind or not ref or not p.get("lead_id"):
            continue
        if not opts["send_calls" if kind == "call" else "send_whatsapp"]:
            continue
        r = await db.execute(
            insert(CrmSync)
            .values(
                id=uuid.uuid4(),
                tenant_id=conn.tenant_id,
                connection_id=conn.id,
                event_id=e.id,
                kind=kind,
                ref_id=uuid.UUID(ref),
                lead_id=uuid.UUID(p["lead_id"]),
                status="pending",
                attempts=0,
                next_try_at=now(),
            )  # fmt: skip
            .on_conflict_do_nothing(constraint="uq_crm_syncs_event")
        )
        made += r.rowcount or 0
    if events:
        conn.cursor_at = events[-1].occurred_at
    return made


async def _email(db: AsyncSession, lead_id: uuid.UUID) -> str | None:
    return await db.scalar(
        select(LeadIdentity.value)
        .where(LeadIdentity.lead_id == lead_id, LeadIdentity.type == "email")
        .order_by(LeadIdentity.is_primary.desc())
        .limit(1)
    )


async def _user(db: AsyncSession, user_id: uuid.UUID | None) -> User | None:
    return await db.get(User, user_id) if user_id else None


async def _external_lead(
    db: AsyncSession, crm: B.Connector, conn: CrmConnection, lead: Lead, phone: str | None
) -> str | None:
    """The lead's id in the CRM: kept in external_refs, else found by phone, else created (when the
    company asked for that and there's a number). None: not in the CRM."""
    key = conn.provider
    known = await db.scalar(
        select(ExternalRef.external_id).where(
            ExternalRef.lead_id == lead.id, ExternalRef.system == key
        )
    )
    if known:
        return known
    found = await crm.find_by_phone(phone) if phone else None
    if not found and phone and options(conn)["create_leads"]:
        owner = await _user(db, lead.owner_user_id)
        found = await crm.create_lead(B.NewLead(
            name=lead.display_name, phone=phone, email=await _email(db, lead.id),
            owner_email=owner.email if owner else None,
        ))  # fmt: skip
    if found:  # one CRM lead may match two Core leads (same number): the first keeps the ref
        await db.execute(
            insert(ExternalRef)
            .values(
                id=uuid.uuid4(),
                tenant_id=lead.tenant_id,
                system=key,
                external_id=found,
                lead_id=lead.id,
            )  # fmt: skip
            .on_conflict_do_nothing(constraint="uq_external_ref")
        )
    return found


async def _send_one(db: AsyncSession, crm: B.Connector, conn: CrmConnection, s: CrmSync) -> str:
    """Returns 'sent' or 'skipped'; raises CrmError."""
    lead = await db.get(Lead, s.lead_id) if s.lead_id else None
    if lead is None:
        s.last_error = "The lead is no longer in Core"
        return "skipped"
    if s.kind == "call":
        call = await db.get(Call, s.ref_id)
        if call is None:
            return "skipped"
        rep = await _user(db, call.user_id)
        ext = await _external_lead(db, crm, conn, lead, call.number)
        if not ext:
            s.last_error = "Not in the CRM, and leads aren't created there"
            return "skipped"
        s.external_lead_id = ext
        s.external_activity_id = await crm.log_call(ext, B.CallInfo(
            call_id=call.id, direction=call.direction, status=call.status, number=call.number,
            started_at=call.started_at, seconds=call.duration_seconds,
            rep_email=rep.email if rep else None, rep_phone=rep.phone if rep else None,
        ))  # fmt: skip
        return "sent"
    msg = await db.get(Message, s.ref_id)
    if msg is None:
        return "skipped"
    phone = await db.scalar(
        select(LeadIdentity.value_normalized)
        .where(LeadIdentity.lead_id == lead.id, LeadIdentity.type == "phone")
        .order_by(LeadIdentity.is_primary.desc())
        .limit(1)
    )
    ext = await _external_lead(db, crm, conn, lead, phone)
    if not ext:
        s.last_error = "Not in the CRM, and leads aren't created there"
        return "skipped"
    rep = await _user(db, msg.sent_by_user_id)
    s.external_lead_id = ext
    s.external_activity_id = await crm.log_message(ext, B.MessageInfo(
        message_id=msg.id, direction=msg.direction, text=msg.body or "",
        at=msg.sent_at or msg.created_at, rep_email=rep.email if rep else None,
    ))  # fmt: skip
    return "sent"


def _failed(conn: CrmConnection, s: CrmSync, e: B.CrmError) -> None:
    s.attempts += 1
    s.last_error = str(e)
    conn.last_error = str(e)
    if e.retry and s.attempts < MAX_TRIES:
        s.next_try_at = now() + timedelta(seconds=RETRY_DELAYS[s.attempts - 1])
    else:
        s.status, s.next_try_at = "failed", None


async def run_tenant(tenant_id: uuid.UUID) -> dict:
    async with tenant_session(tenant_id) as db:
        conn = await db.scalar(select(CrmConnection).where(CrmConnection.is_active.is_(True)))
        if conn is None:
            return {"made": 0, "sent": 0}
        made = await collect(db, conn)
        due = (
            await db.scalars(
                select(CrmSync.id)
                .where(CrmSync.status == "pending", CrmSync.next_try_at <= now())
                .order_by(CrmSync.next_try_at)
                .limit(BATCH)
            )
        ).all()
        conn_id = conn.id
    sent = 0
    for sync_id in due:  # each in its own transaction, so one bad send never undoes another
        async with tenant_session(tenant_id) as db:
            s = await db.get(CrmSync, sync_id, with_for_update=True, populate_existing=True)
            conn = await db.get(CrmConnection, conn_id)
            if s is None or conn is None or s.status != "pending" or not conn.is_active:
                continue
            try:
                crm = connector_for(conn)
                s.status = await _send_one(db, crm, conn, s)
                s.attempts += 1
                s.next_try_at = None
                if s.status == "sent":
                    s.sent_at = conn.last_ok_at = now()
                    conn.last_error = None
                    sent += 1
            except B.CrmError as e:
                _failed(conn, s, e)
            except ValueError as e:  # keys that can't be read any more
                _failed(conn, s, B.CrmError(str(e), retry=False))
    return {"made": made, "sent": sent}


async def run_all(tenant_ids: list[uuid.UUID]) -> dict:
    made = sent = 0
    for t in tenant_ids:
        r = await run_tenant(t)
        made, sent = made + r["made"], sent + r["sent"]
    return {"made": made, "sent": sent}

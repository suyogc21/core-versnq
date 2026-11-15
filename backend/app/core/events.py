"""Event catalogue (from the spec) and emit(). Every important change calls emit()."""

import uuid
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events_model import Event
from app.core.modules import is_enabled

# event type -> module that owns it. Source: spec §11 "Outbound event catalogue (v1)".
CATALOGUE: dict[str, str] = {
    "lead.created": "crm",
    "lead.updated": "crm",
    "lead.assigned": "crm",
    "lead.stage_changed": "crm",
    "lead.merged": "crm",  # step 1 (Decision log #22): survivor id + merged lead id
    "lead.intent_changed": "crm",
    "record.created": "crm",  # step 2 (Decision log #23): company-defined record types
    "record.updated": "crm",
    "record.stage_changed": "crm",
    "record.deleted": "crm",
    "link.created": "crm",
    "link.deleted": "crm",  # produced by ACE through the API (Decision log #5)
    "activity.logged": "crm",
    "call.recorded": "ace",  # call intelligence belongs to ACE (Decision log #3)
    "call.analyzed": "ace",
    "task.created": "crm",
    "task.due": "crm",
    "sequence.enrolled": "sequences",
    "sequence.replied": "sequences",
    "message.received": "inbox",  # Decision log #43: every email / WhatsApp in or out
    "message.sent": "inbox",
    "contact.converted": "outreach",  # step O2: a campaign contact became a lead
    # step O3: replies sorted into the company's categories, and drafts (the contract with ACE)
    "reply.classified": "inbox",
    "draft.requested": "inbox",
    "draft.created": "inbox",
    "draft.approved": "inbox",
    "draft.rejected": "inbox",
    "draft.superseded": "inbox",
    "reply_categories.changed": "inbox",
    "deal.created": "crm",  # step 3 (Decision log #25)
    "deal.updated": "crm",
    "deal.stage_changed": "crm",
    "deal.deleted": "crm",
    "deal.won": "crm",
    "deal.lost": "crm",
    "customer.created": "crm",
    "account.updated": "key_accounts",  # step 7b (Decision log #36)
    "document.received": "crm",  # step 5 (Decision log #32)
    "document.verified": "crm",
    "document.rejected": "crm",
    "invoice.created": "money",  # step 6 (Decision log #34): fired when issued
    "invoice.voided": "money",
    "payment.reversed": "money",
    "payment.due": "money",
    "payment.received": "money",
    "payment.overdue": "money",
}


class UnknownEvent(ValueError):
    pass


# Set while an automation runs its actions: {"id", "name", "chain": [ids], "depth"}. Events
# written meanwhile carry it as "_via", so automations can stop loops (Decision log #27).
automation_context: ContextVar[dict | None] = ContextVar("automation_context", default=None)
# Who is signed in for this request: (user id, "user" | "integration"). Set by the auth
# dependency; a request's own copy, so nothing carries over between requests (Decision log #43).
request_actor: ContextVar[tuple[uuid.UUID, str] | None] = ContextVar("request_actor", default=None)


def _actor() -> dict:
    """Who caused the event: an automation, a signed-in person / API key, or Core itself."""
    if automation_context.get():
        return {"actor_user_id": None, "actor_type": "automation"}
    who = request_actor.get()
    if who:
        return {"actor_user_id": str(who[0]), "actor_type": who[1]}
    return {"actor_user_id": None, "actor_type": "system"}


async def emit(db: AsyncSession, tenant_id: uuid.UUID, type_: str, payload: dict) -> bool:
    """Write the event in the caller's transaction. Returns False when the owning module
    is switched off for this tenant (nothing is written)."""
    module = CATALOGUE.get(type_)
    if module is None:
        raise UnknownEvent(f"Unknown event type: {type_}")
    if not await is_enabled(db, tenant_id, module):
        return False
    via = automation_context.get()
    if via:
        payload = payload | {"_via": {k: via[k] for k in ("chain", "depth")}}
    payload = payload | {"_actor": _actor()}
    db.add(Event(tenant_id=tenant_id, type=type_, payload=payload))
    await db.flush()
    return True

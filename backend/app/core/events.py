"""Event catalogue (from the spec) and emit(). Every important change calls emit()."""

import uuid

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
    "deal.created": "crm",  # step 3 (Decision log #25)
    "deal.updated": "crm",
    "deal.stage_changed": "crm",
    "deal.deleted": "crm",
    "deal.won": "crm",
    "deal.lost": "crm",
    "customer.created": "crm",
    "document.received": "crm",
    "invoice.created": "money",
    "payment.due": "money",
    "payment.received": "money",
    "payment.overdue": "money",
}


class UnknownEvent(ValueError):
    pass


async def emit(db: AsyncSession, tenant_id: uuid.UUID, type_: str, payload: dict) -> bool:
    """Write the event in the caller's transaction. Returns False when the owning module
    is switched off for this tenant (nothing is written)."""
    module = CATALOGUE.get(type_)
    if module is None:
        raise UnknownEvent(f"Unknown event type: {type_}")
    if not await is_enabled(db, tenant_id, module):
        return False
    db.add(Event(tenant_id=tenant_id, type=type_, payload=payload))
    await db.flush()
    return True

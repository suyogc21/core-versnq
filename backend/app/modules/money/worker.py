"""Money work done by the worker: sending queued emails and the nightly round."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.errors import Invalid
from app.core.modules import is_enabled
from app.core.tenancy import tenant_session
from app.modules.crm import leads as L
from app.modules.money import links, messages, nightly
from app.modules.money.models import MoneyMessage

MAX_TRIES = 3


async def send_one(tenant_id: uuid.UUID, message_id: uuid.UUID, last_try: bool) -> str:
    """Send one email. A failure is retried; on the last try the message is marked failed."""
    try:
        async with tenant_session(tenant_id) as db:
            return await messages.send(db, message_id)
    except Invalid as e:
        if not last_try:
            raise
        async with tenant_session(tenant_id) as db:
            msg = await db.get(MoneyMessage, message_id)
            if msg is not None and msg.status == "queued":
                msg.status, msg.error = "failed", e.detail[:500]
        return "failed"


async def sweep(tenant_ids: list[uuid.UUID]) -> int:
    """Every minute: queued emails whose job was lost (Redis down, worker restarted)."""
    sent = 0
    cutoff = L.now() - timedelta(seconds=30)
    for t in tenant_ids:
        async with tenant_session(t) as db:
            ids = (
                await db.scalars(
                    select(MoneyMessage.id)
                    .where(MoneyMessage.status == "queued", MoneyMessage.created_at < cutoff)
                    .limit(50)
                )
            ).all()
        for message_id in ids:
            sent += await send_one(t, message_id, last_try=True) == "sent"
    return sent


async def nightly_tenant(tenant_id: uuid.UUID) -> dict:
    async with tenant_session(tenant_id) as db:
        if not await is_enabled(db, tenant_id, "money"):
            return {}
    async with tenant_session(tenant_id) as db:
        repeated = await nightly.repeat(db)
    async with tenant_session(tenant_id) as db:
        reminded = await nightly.remind(db)
    async with tenant_session(tenant_id) as db:
        recovered = await links.check_open_links(db)
    return {"repeated": repeated, "reminded": reminded, "links_recovered": recovered}

"""Consent (email / WhatsApp opt-in and opt-out, with history) and the suppression list.

Rules:
- Every change is a new `consents` row; the lead carries the current state for filtering.
- An opt-out puts the lead's identifiers on the suppression list. The list is not linked to the
  lead, so it outlives deletion and merges (Decision log #18).
- Automatic paths (form, import, API) can never undo an opt-out. Only a person with
  `leads.edit`, giving a note, can record a new opt-in, which lifts the opt-out suppression.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import Consent, Lead, LeadIdentity, Suppression

CHANNELS = ("email", "whatsapp")
AUTOMATIC = ("form", "import", "api")


async def _identifiers(db: AsyncSession, lead: Lead, channel: str) -> list[str]:
    kind = "email" if channel == "email" else "phone"
    return list(
        (
            await db.scalars(
                select(LeadIdentity.value_normalized).where(
                    LeadIdentity.lead_id == lead.id, LeadIdentity.type == kind
                )
            )
        ).all()
    )


async def is_suppressed(db: AsyncSession, channel: str, values: list[str]) -> bool:
    if not values:
        return False
    found = await db.scalar(
        select(Suppression.id)
        .where(Suppression.channel == channel, Suppression.value_normalized.in_(values))
        .limit(1)
    )
    return found is not None


async def suppress(
    db: AsyncSession, tenant_id: uuid.UUID, channel: str, values: list[str], reason: str
) -> None:
    for value in values:
        await db.execute(
            insert(Suppression)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                channel=channel,
                value_normalized=value,
                reason=reason,
            )
            # one row per address: a bounce or complaint replaces an earlier opt-out (it is the
            # stronger "never email" reason); otherwise the first reason stays
            .on_conflict_do_update(
                constraint="uq_suppression_value",
                set_={"reason": reason},
                where=(Suppression.reason == "opt_out") & (reason != "opt_out"),
            )
        )


async def record(
    db: AsyncSession,
    lead: Lead,
    channel: str,
    status: str,
    source: str,
    *,
    actor: CurrentUser | None = None,
    wording: str | None = None,
    evidence: dict | None = None,
    captured_at: datetime | None = None,
) -> bool:
    """Record a consent change. Returns False when an automatic opt-in was refused because the
    lead (or one of its identifiers) has opted out."""
    if channel not in CHANNELS or status not in ("opted_in", "opted_out"):
        raise Invalid("Unknown consent")
    current = getattr(lead, f"{channel}_consent")
    values = await _identifiers(db, lead, channel)
    if status == "opted_in" and source in AUTOMATIC:
        if current == "opted_out" or await is_suppressed(db, channel, values):
            return False
    if status == "opted_in" and source == "manual" and not (wording or "").strip():
        raise Invalid("Add a note saying how the person gave consent")
    if current == status and source in AUTOMATIC:
        return True  # nothing new to record
    db.add(
        Consent(
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            channel=channel,
            status=status,
            source=source,
            wording=(wording or "").strip() or None,
            evidence=evidence or {},
            actor_user_id=actor.user.id if actor else None,
            captured_at=captured_at or L.now(),
        )
    )
    setattr(lead, f"{channel}_consent", status)
    if status == "opted_out":
        await suppress(db, lead.tenant_id, channel, values, "opt_out")
    elif source == "manual":  # a person's fresh opt-in lifts the earlier opt-out
        await db.execute(
            delete(Suppression).where(
                Suppression.channel == channel,
                Suppression.value_normalized.in_(values),
                Suppression.reason == "opt_out",
            )
        )
    label = "Email" if channel == "email" else "WhatsApp"
    await L.log(
        db,
        lead,
        "consent_changed",
        f"{label}: {'opted in' if status == 'opted_in' else 'opted out'}",
        actor,
        {"channel": channel, "status": status, "source": source},
    )
    return True

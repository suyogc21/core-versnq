"""Lead endpoints for other systems and ACE (spec §11, Decision log #4, #5, #37).

ACE uses an ordinary API key; nothing here is special to ACE, so any tool can use them.
- `POST /leads/upsert`: find the person by phone or email (the same duplicate check as every
  other way in); a new person becomes a lead through the normal intake and routing rules, an
  existing one is left untouched. Optional intent and conversation in the same call.
- `POST /leads/{id}/conversation`: one timeline activity per conversation (W5); an
  `external_id` makes retries safe.
- `PUT /leads/{id}/intent`: hot / warm / cold / not interested; writes an activity and emits
  `lead.intent_changed`.
- `PUT /leads/{id}/ace-summary`: ACE's latest summary of the lead (only an integration key).
  Shown at the top of the lead; no timeline line, no version bump; the same body twice is a
  no-op; a change emits `lead.summary_changed`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import Forbidden, Invalid
from app.core.events import emit
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb
from app.modules.crm.models import Activity, Lead, LeadSource
from app.modules.crm.routing import mark_contacted

router = APIRouter(prefix="/api/v1/leads", tags=["lead-api"], dependencies=CRM)
Creator = Annotated[CurrentUser, require("leads.create")]
Editor = Annotated[CurrentUser, require("leads.edit")]

Intent = Literal["hot", "warm", "cold", "not_interested"]
INTENT_LABELS = {"hot": "Hot", "warm": "Warm", "cold": "Cold", "not_interested": "Not interested"}
Channel = Literal["whatsapp", "email", "sms", "linkedin", "call", "chat", "other"]
CHANNEL_LABELS = {
    "whatsapp": "WhatsApp", "email": "Email", "sms": "SMS", "linkedin": "LinkedIn",
    "call": "Call", "chat": "Chat", "other": "Other",
}  # fmt: skip


class MessageIn(BaseModel):
    sender: Literal["lead", "us"] = Field(description="who wrote it: the lead, or our side")
    text: str = Field(min_length=1, max_length=4000)
    at: datetime | None = None


class ConversationIn(BaseModel):
    channel: Channel
    messages: list[MessageIn] = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    external_id: str | None = Field(
        default=None, max_length=200, description="your id for this conversation (safe retries)"
    )


class AceSummaryIn(BaseModel):
    summary: str = Field(min_length=1, max_length=600)
    next_step: str | None = Field(default=None, max_length=200)
    prompt_version: str | None = Field(default=None, max_length=50)


class AceSummaryOut(BaseModel):
    lead_id: uuid.UUID
    ace_summary_at: datetime | None
    changed: bool


class IntentIn(BaseModel):
    intent: Intent
    reason: str | None = Field(default=None, max_length=500)


class UpsertIn(BaseModel):
    phones: list[str] = Field(default=[], max_length=5)
    emails: list[str] = Field(default=[], max_length=5)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    org_name: str | None = Field(default=None, max_length=200)
    source_id: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=80, description="source name, if no id")
    origin: Literal["inbound", "outbound_ace", "outside"] = "inbound"
    custom_fields: dict = Field(default={}, max_length=100)
    intent: IntentIn | None = None
    conversation: ConversationIn | None = None


class UpsertOut(BaseModel):
    result: Literal["created", "existing"]
    lead_id: uuid.UUID | None = Field(
        description="empty when the person exists but this key may not see them"
    )
    name: str | None


class IntentOut(BaseModel):
    lead_id: uuid.UUID
    intent: str | None
    intent_updated_at: datetime | None
    changed: bool


class ConversationOut(BaseModel):
    activity_id: uuid.UUID
    created: bool


async def _source(db, body: UpsertIn) -> uuid.UUID:
    if body.source_id:
        src = await db.get(LeadSource, body.source_id)
    elif body.source:
        src = await db.scalar(
            select(LeadSource).where(func.lower(LeadSource.name) == body.source.strip().lower())
        )
    else:
        raise Invalid("Send source_id or source")
    if src is None or not src.is_active:
        raise Invalid("Choose an active source")
    return src.id


async def set_intent(db, lead: Lead, body: IntentIn, actor: CurrentUser) -> bool:
    if lead.intent == body.intent:
        return False
    previous, lead.intent, lead.intent_updated_at = lead.intent, body.intent, L.now()
    summary = f"Intent: {INTENT_LABELS[body.intent]}"
    await L.log(
        db, lead, "intent_changed", summary, actor,
        {"intent": body.intent, "previous": previous, "reason": body.reason},
        body=body.reason,
    )  # fmt: skip
    lead.version += 1
    await L.event(
        db, lead, "lead.intent_changed",
        {"intent": body.intent, "previous": previous, "reason": body.reason},
    )  # fmt: skip
    return True


async def add_conversation(
    db, lead: Lead, body: ConversationIn, actor: CurrentUser
) -> tuple[Activity, bool]:
    if body.external_id:
        found = await db.scalar(
            select(Activity).where(
                Activity.lead_id == lead.id,
                Activity.type_key == "api_conversation",
                Activity.data["external_id"].astext == body.external_id,
            )
        )
        if found:
            return found, False
    times = [m.at for m in body.messages if m.at]
    when = max(times) if times else L.now()
    if when > L.now():
        raise Invalid("Messages cannot be in the future")
    channel = CHANNEL_LABELS[body.channel]
    n = len(body.messages)
    transcript = "\n".join(
        f"{'Lead' if m.sender == 'lead' else 'Us'}: {m.text}" for m in body.messages
    )
    activity = await L.log(
        db, lead, "api_conversation",
        f"{channel} conversation · {n} message{'s' if n != 1 else ''}", actor,
        {
            "channel": body.channel,
            "summary": body.summary,
            "external_id": body.external_id,
            "messages": [m.model_dump(mode="json") for m in body.messages],
        },
        body="\n\n".join(filter(None, [body.summary, transcript]))[:20000],
        occurred_at=when,
    )  # fmt: skip
    lead.last_activity_at = max(filter(None, [lead.last_activity_at, when]))
    if any(m.sender == "us" for m in body.messages):
        lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, when]))
        lead.first_response_at = lead.first_response_at or when
        await mark_contacted(db, lead)
    lead.version += 1
    await L.event(
        db, lead, "activity.logged",
        {"activity_id": str(activity.id), "type": "api_conversation", "disposition": None},
    )  # fmt: skip
    return activity, True


@router.post("/upsert", response_model=UpsertOut)
async def upsert_lead(body: UpsertIn, db: CrmDb, actor: Creator) -> UpsertOut:
    identities = [
        *(L.IdentityInput("phone", p, is_primary=i == 0) for i, p in enumerate(body.phones)),
        *(L.IdentityInput("email", e, is_primary=i == 0) for i, e in enumerate(body.emails)),
    ]
    if not identities:
        raise Invalid("Send at least one phone or email")
    fields = {
        k: v.strip()
        for k, v in (
            ("first_name", body.first_name),
            ("last_name", body.last_name),
            ("org_name", body.org_name),
        )
        if v and v.strip()
    }
    inc = I.Incoming(
        identities=identities,
        source_id=await _source(db, body),
        created_via="api",
        fields=fields,
        custom_fields=body.custom_fields,
        origin=body.origin,
        owner=I.RULES,
        enforce_required=False,
        via_label="the API",
    )
    out = await I.intake(db, actor.user.tenant_id, inc, policy="skip", actor=actor)
    if out.result == "created":
        lead, result = out.lead, "created"
    else:
        result = "existing"
        lead = out.match if await I._visible(db, actor, out.match) else None
    if lead is not None:
        if body.intent:
            await set_intent(db, lead, body.intent, actor)
        if body.conversation:
            await add_conversation(db, lead, body.conversation, actor)
    await db.flush()
    return UpsertOut(
        result=result,
        lead_id=lead.id if lead else None,
        name=lead.display_name if lead else None,
    )


@router.post("/{lead_id}/conversation", response_model=ConversationOut)
async def post_conversation(
    lead_id: uuid.UUID, body: ConversationIn, db: CrmDb, actor: Editor
) -> ConversationOut:
    lead = await L.get_visible(db, actor, lead_id)
    activity, created = await add_conversation(db, lead, body, actor)
    await db.flush()
    return ConversationOut(activity_id=activity.id, created=created)


@router.put("/{lead_id}/intent", response_model=IntentOut)
async def put_intent(lead_id: uuid.UUID, body: IntentIn, db: CrmDb, actor: Editor) -> IntentOut:
    lead = await L.get_visible(db, actor, lead_id)
    changed = await set_intent(db, lead, body, actor)
    await db.flush()
    return IntentOut(
        lead_id=lead.id,
        intent=lead.intent,
        intent_updated_at=lead.intent_updated_at,
        changed=changed,
    )


@router.put("/{lead_id}/ace-summary", response_model=AceSummaryOut)
async def put_ace_summary(
    lead_id: uuid.UUID, body: AceSummaryIn, db: CrmDb, actor: Editor
) -> AceSummaryOut:
    if actor.user.status != "integration":
        raise Forbidden("Only ACE's API key can write the ACE summary", code="integration_only")
    lead = await L.get_visible(db, actor, lead_id)
    summary, next_step = body.summary.strip(), (body.next_step or "").strip() or None
    changed = (lead.ace_summary, lead.ace_next_step) != (summary, next_step)
    if changed:
        lead.ace_summary, lead.ace_next_step = summary, next_step
        lead.ace_prompt_version, lead.ace_summary_at = body.prompt_version, L.now()
        await emit(db, lead.tenant_id, "lead.summary_changed", {"lead_id": str(lead.id)})
    await db.flush()
    return AceSummaryOut(lead_id=lead.id, ace_summary_at=lead.ace_summary_at, changed=changed)

"""Reply categories, sorting and drafts (step O3, the contract with ACE). Works in both inboxes:
campaign replies (outreach.reply) and replies from leads (inbox.reply)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.errors import Forbidden, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, has_permission, require
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.engage import inbox as IB
from app.modules.engage.models import Conversation, Message
from app.modules.replies import service as RS
from app.modules.replies.models import Draft, MessageClassification

router = APIRouter(prefix="/api/v1", tags=["replies"], dependencies=CRM)
Admin = Annotated[CurrentUser, require("settings.manage")]
KEY = r"^[a-z][a-z0-9_]{0,39}$"


async def _answerer(actor: ActiveUser) -> CurrentUser:
    if not (
        has_permission(actor.permissions, "inbox.reply")
        or has_permission(actor.permissions, "outreach.reply")
    ):
        raise Forbidden("permission_denied")
    return actor


Answerer = Annotated[CurrentUser, Depends(_answerer)]


# ---------- shapes ----------
class RuleIO(BaseModel):
    action: Literal["convert", "draft", "stop", "unsubscribe", "notify"]
    instructions: str | None = Field(default=None, max_length=1000)


class CategoryIn(BaseModel):
    key: str = Field(pattern=KEY)
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    active: bool = True
    auto_send_allowed: bool = False
    rules: list[RuleIO] = Field(default=[], max_length=10)


class CategoryOut(CategoryIn):
    needs_human: bool
    position: int


class CategoriesOut(BaseModel):
    categories: list[CategoryOut]
    updated_at: datetime | None


class CategoriesIn(BaseModel):
    categories: list[CategoryIn] = Field(min_length=1, max_length=50)


class ClassificationIn(BaseModel):
    category: str = Field(pattern=KEY)
    confidence: int | None = Field(default=None, ge=0, le=100)
    summary: str | None = Field(default=None, max_length=500)
    reasons: list[Annotated[str, Field(max_length=200)]] = Field(default=[], max_length=5)
    language: str | None = Field(default=None, max_length=20)
    prompt_version: str | None = Field(default=None, max_length=60)


class ClassificationOut(BaseModel):
    classification_id: uuid.UUID
    rules_run: list[str]
    draft_requested: bool


class SortingOut(BaseModel):
    """One reply's current sorting (shown in the thread)."""

    message_id: uuid.UUID
    category: str
    confidence: int | None
    summary: str | None
    reasons: list[str]
    by: str
    created_at: datetime


class DraftIn(BaseModel):
    request_id: uuid.UUID | None = None
    reply_to_message_id: uuid.UUID
    body: str = Field(min_length=1, max_length=50000)
    reasons: list[Annotated[str, Field(max_length=200)]] = Field(default=[], max_length=5)
    language: str | None = Field(default=None, max_length=20)


class DraftOut(BaseModel):
    id: uuid.UUID
    status: str
    body: str
    reasons: list[str]
    conversation_id: uuid.UUID
    reply_to_message_id: uuid.UUID
    decided_by_user_id: uuid.UUID | None
    via: str | None
    message_id: uuid.UUID | None
    error: str | None
    created_at: datetime


class ConversationSortingOut(BaseModel):
    sortings: list[SortingOut]
    draft: DraftOut | None


class DecideIn(BaseModel):
    on_behalf_of_user_id: uuid.UUID | None = None
    body: str | None = Field(default=None, max_length=50000)


class RejectIn(BaseModel):
    on_behalf_of_user_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class DecidedOut(BaseModel):
    status: str
    message_id: uuid.UUID | None = None


def _draft_out(d: Draft) -> DraftOut:
    return DraftOut(
        id=d.id, status=d.status, body=d.body, reasons=d.reasons or [],
        conversation_id=d.conversation_id, reply_to_message_id=d.reply_to_message_id,
        decided_by_user_id=d.decided_by_user_id, via=d.via, message_id=d.message_id,
        error=d.error, created_at=d.created_at,
    )  # fmt: skip


async def _conversation(db, actor: CurrentUser, conv_id: uuid.UUID) -> Conversation:
    """A conversation this caller may see: a lead's (normal inbox) or a campaign thread."""
    from app.modules.outreach import service as O

    conds = []
    if has_permission(actor.permissions, "inbox.reply"):
        conds.append(await IB.visible(db, actor))
    if has_permission(actor.permissions, "outreach.reply"):
        conds.append(O.conversation_filter(actor))
    conv = (
        await db.scalar(select(Conversation).where(Conversation.id == conv_id, or_(*conds)))
        if conds
        else None
    )
    if conv is None:
        raise NotFound("Conversation not found")
    return conv


# ---------- categories ----------
async def _categories_out(db, tenant_id) -> CategoriesOut:
    cats = await RS.categories(db, tenant_id)
    out = []
    for c in cats:
        rules = await RS.rules_of(db, c.id)
        out.append(
            CategoryOut(
                key=c.key,
                name=c.name,
                description=c.description,
                active=c.active,
                auto_send_allowed=c.auto_send_allowed,
                needs_human=c.needs_human,
                position=c.position,
                rules=[
                    RuleIO(action=r.action, instructions=r.instructions) for r in rules if r.active
                ],
            )  # fmt: skip
        )
    return CategoriesOut(categories=out, updated_at=max((c.updated_at for c in cats), default=None))


@router.get("/reply-categories", response_model=CategoriesOut)
async def list_categories(db: CrmDb, actor: Answerer) -> CategoriesOut:
    return await _categories_out(db, actor.user.tenant_id)


@router.put("/reply-categories", response_model=CategoriesOut)
async def save_categories(body: CategoriesIn, db: CrmDb, actor: Admin) -> CategoriesOut:
    await RS.save_categories(db, actor.user.tenant_id, [c.model_dump() for c in body.categories])
    await audit(db, actor, "reply_categories.saved", "reply_categories", None, None,
                {"keys": [c.key for c in body.categories]})  # fmt: skip
    return await _categories_out(db, actor.user.tenant_id)


# ---------- sorting ----------
@router.put("/messages/{message_id}/classification", response_model=ClassificationOut)
async def classify(
    message_id: uuid.UUID, body: ClassificationIn, db: CrmDb, actor: Answerer
) -> ClassificationOut:
    """ACE's key sorts as `ace`; a person sorting by hand is `person` (and wins from then on)."""
    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id is None:
        raise NotFound("Message not found")
    conv = await _conversation(db, actor, msg.conversation_id)
    if not await RS.can_answer(db, actor, conv):
        raise Forbidden("permission_denied")
    by = "ace" if actor.user.status == "integration" else "person"
    row, ran, drafted = await RS.classify(
        db, actor, msg, category=body.category, by=by, confidence=body.confidence,
        summary=body.summary, reasons=body.reasons, language=body.language,
        prompt_version=body.prompt_version,
    )  # fmt: skip
    return ClassificationOut(classification_id=row.id, rules_run=ran, draft_requested=drafted)


@router.get("/conversations/{conv_id}/sorting", response_model=ConversationSortingOut)
async def conversation_sorting(
    conv_id: uuid.UUID, db: CrmDb, actor: Answerer
) -> ConversationSortingOut:
    """Each reply's current category, and the waiting draft (for the thread view)."""
    conv = await _conversation(db, actor, conv_id)
    rows = (
        await db.scalars(
            select(MessageClassification).where(
                MessageClassification.conversation_id == conv.id, MessageClassification.is_current
            )
        )
    ).all()
    d = await RS.pending_draft(db, conv.id)
    return ConversationSortingOut(
        sortings=[
            SortingOut(
                message_id=r.message_id,
                category=r.category_key,
                confidence=r.confidence,
                summary=r.summary,
                reasons=r.reasons or [],
                by=r.by,
                created_at=r.created_at,
            )  # fmt: skip
            for r in rows
        ],
        draft=_draft_out(d) if d else None,
    )


# ---------- drafts ----------
@router.post("/conversations/{conv_id}/drafts", response_model=DraftOut)
async def create_draft(conv_id: uuid.UUID, body: DraftIn, db: CrmDb, actor: Answerer) -> DraftOut:
    conv = await _conversation(db, actor, conv_id)
    if not await RS.can_answer(db, actor, conv):
        raise Forbidden("permission_denied")
    d = await RS.create_draft(
        db, actor, conv, request_id=body.request_id, reply_to_message_id=body.reply_to_message_id,
        body=body.body, reasons=body.reasons, language=body.language,
    )  # fmt: skip
    return _draft_out(d)


async def _draft(db, actor: CurrentUser, draft_id: uuid.UUID) -> Draft:
    d = await RS.get_draft(db, draft_id)
    await _conversation(db, actor, d.conversation_id)  # the caller must see the conversation
    return d


@router.get("/drafts/{draft_id}", response_model=DraftOut)
async def get_draft(draft_id: uuid.UUID, db: CrmDb, actor: Answerer) -> DraftOut:
    return _draft_out(await _draft(db, actor, draft_id))


@router.post("/drafts/{draft_id}/approve", response_model=DecidedOut)
async def approve(draft_id: uuid.UUID, body: DecideIn, db: CrmDb, actor: Answerer) -> DecidedOut:
    d = await _draft(db, actor, draft_id)
    sent = await RS.approve(db, actor, d, on_behalf_of=body.on_behalf_of_user_id, body=body.body)
    return DecidedOut(status=d.status, message_id=sent.id)


@router.post("/drafts/{draft_id}/reject", response_model=DecidedOut)
async def reject(draft_id: uuid.UUID, body: RejectIn, db: CrmDb, actor: Answerer) -> DecidedOut:
    d = await _draft(db, actor, draft_id)
    await RS.reject(db, actor, d, on_behalf_of=body.on_behalf_of_user_id, reason=body.reason)
    return DecidedOut(status=d.status)

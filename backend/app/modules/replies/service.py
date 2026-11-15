"""Replies sorted into the company's own categories, the rules that act on them, and drafts
(step O3, the contract with ACE in docs/plans/outreach-plan.md).

ACE (or a person) sorts a reply: PUT /messages/{id}/classification. The category's rules run
once per message: convert to a lead (campaign replies), ask ACE for a draft, stop, unsubscribe,
tell the owner. A person's choice wins over ACE's from then on. A draft waits for a person
(Core or Slack): approve and send from the right inbox in the same thread, or reject. If the
other side writes again first, the waiting draft is out of date (superseded).
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.events import emit
from app.modules.auth.deps import CurrentUser, has_permission
from app.modules.crm import consent as C
from app.modules.crm import leads as L
from app.modules.crm.models import Lead, Suppression
from app.modules.crm.notify import notify
from app.modules.engage import inbox as IB
from app.modules.engage.models import Conversation, ConversationNote, Message
from app.modules.replies.models import (
    Draft,
    DraftRequest,
    MessageClassification,
    ReplyCategory,
    ReplyRule,
)

ACTIONS = ("convert", "draft", "stop", "unsubscribe", "notify")
NEEDS_HUMAN = "needs_human"
# Every company's starting set (Decided Nov 15). key, name, description, actions
DEFAULTS: list[tuple[str, str, str, list[str]]] = [
    ("interested", "Interested", "They want to know more, see a demo, or buy.",
     ["convert", "draft", "notify"]),
    ("meeting", "Meeting request", "They ask for a call or a meeting, or propose a time.",
     ["convert", "draft", "notify"]),
    ("question", "Question", "They ask something about the offer before deciding.", ["draft"]),
    ("not_now", "Not now", "Interested later: wrong time, budget next quarter, ask again later.",
     ["stop"]),
    ("not_interested", "Not interested", "A clear no.", ["stop"]),
    ("unsubscribe", "Unsubscribe me", "They ask not to be emailed again.", ["unsubscribe"]),
    ("wrong_person", "Wrong person", "Not the right person; may name someone else.", ["stop"]),
    (NEEDS_HUMAN, "Needs a human", "Unclear, sensitive, angry, or anything ACE is not sure about.",
     ["notify"]),
]  # fmt: skip


class ClassifiedByPerson(Conflict):
    code = "classified_by_person"


# ---------- categories ----------
async def ensure_defaults(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """The starting categories, made the first time a company needs them."""
    if await db.scalar(select(ReplyCategory.id).limit(1)):
        return
    for pos, (key, name, desc, actions) in enumerate(DEFAULTS):
        cat = ReplyCategory(
            id=uuid.uuid4(), tenant_id=tenant_id, key=key, name=name, description=desc,
            needs_human=key == NEEDS_HUMAN, active=True, position=pos,
        )  # fmt: skip
        db.add(cat)
        await db.flush()
        for i, action in enumerate(actions):
            db.add(ReplyRule(tenant_id=tenant_id, category_id=cat.id, action=action, position=i))
    await db.flush()


async def categories(db: AsyncSession, tenant_id: uuid.UUID) -> list[ReplyCategory]:
    await ensure_defaults(db, tenant_id)
    return list((await db.scalars(select(ReplyCategory).order_by(ReplyCategory.position))).all())


async def rules_of(db: AsyncSession, category_id: uuid.UUID) -> list[ReplyRule]:
    return list(
        (
            await db.scalars(
                select(ReplyRule)
                .where(ReplyRule.category_id == category_id)
                .order_by(ReplyRule.position)
            )
        ).all()
    )


async def save_categories(db: AsyncSession, tenant_id: uuid.UUID, items: list[dict]) -> None:
    """The whole list at once: [{key, name, description, active, rules: [{action,
    instructions}]}]. needs_human is always kept; keys never change once made."""
    existing = {c.key: c for c in await categories(db, tenant_id)}
    keys = [i["key"] for i in items]
    if len(set(keys)) != len(keys):
        raise Invalid("Two categories have the same key")
    if NEEDS_HUMAN not in keys:
        raise Invalid("'Needs a human' can't be removed", code="needs_human_required")
    for pos, item in enumerate(items):
        cat = existing.get(item["key"])
        if cat is None:
            cat = ReplyCategory(id=uuid.uuid4(), tenant_id=tenant_id, key=item["key"])
            db.add(cat)
        cat.name, cat.description = item["name"], item.get("description")
        cat.active = True if cat.key == NEEDS_HUMAN else item.get("active", True)
        cat.needs_human = cat.key == NEEDS_HUMAN
        cat.auto_send_allowed = bool(item.get("auto_send_allowed", False))
        cat.position = pos
        await db.flush()
        await db.execute(ReplyRule.__table__.delete().where(ReplyRule.category_id == cat.id))
        for i, rule in enumerate(item.get("rules") or []):
            if rule["action"] == "convert" and cat.needs_human:
                raise Invalid("'Needs a human' can't convert on its own")
            db.add(ReplyRule(tenant_id=tenant_id, category_id=cat.id, action=rule["action"],
                             instructions=rule.get("instructions"), position=i))  # fmt: skip
    for key, cat in existing.items():
        if key not in keys:
            await db.delete(cat)
    await db.flush()
    await emit(db, tenant_id, "reply_categories.changed", {})


# ---------- sorting ----------
async def current(db: AsyncSession, message_id: uuid.UUID) -> MessageClassification | None:
    return await db.scalar(
        select(MessageClassification).where(
            MessageClassification.message_id == message_id, MessageClassification.is_current
        )
    )


async def classify(
    db: AsyncSession,
    actor: CurrentUser,
    msg: Message,
    *,
    category: str,
    by: str,
    confidence: int | None = None,
    summary: str | None = None,
    reasons: list[str] | None = None,
    language: str | None = None,
    prompt_version: str | None = None,
) -> tuple[MessageClassification, list[str], bool]:
    """Returns (classification, rules that ran now, whether a draft was asked for). Rules run
    once per message and category: the same answer again changes nothing."""
    if msg.direction != "in":
        raise Invalid("Only replies (incoming messages) are sorted", code="not_a_reply")
    cat = await db.scalar(select(ReplyCategory).where(ReplyCategory.key == category))
    await ensure_defaults(db, msg.tenant_id)
    cat = cat or await db.scalar(select(ReplyCategory).where(ReplyCategory.key == category))
    if cat is None or not cat.active:
        raise Invalid(
            f"'{category}' is not one of the company's categories", code="unknown_category"
        )
    before = await current(db, msg.id)
    if before is not None and before.by == "person" and by == "ace":
        raise ClassifiedByPerson("A person already sorted this reply")
    if before is not None and before.category_key == category and before.by == by:
        return before, [], False  # the same answer again
    if before is not None:
        before.is_current = False
        await db.flush()
    row = MessageClassification(
        id=uuid.uuid4(), tenant_id=msg.tenant_id, message_id=msg.id,
        conversation_id=msg.conversation_id, category_key=category, confidence=confidence,
        summary=summary, reasons=reasons or [], language=language, prompt_version=prompt_version,
        by=by, by_user_id=actor.user.id, is_current=True,
    )  # fmt: skip
    db.add(row)
    await db.flush()
    await emit(
        db,
        msg.tenant_id,
        "reply.classified",
        {
            "message_id": str(msg.id),
            "conversation_id": str(msg.conversation_id) if msg.conversation_id else None,
            "contact_id": str(msg.contact_id) if msg.contact_id else None,
            "lead_id": str(msg.lead_id) if msg.lead_id else None,
            "category": category,
            "confidence": confidence,
            "by": by,
            "classification_id": str(row.id),
        },
    )
    ran_before = {
        k
        for (k,) in (
            await db.execute(
                select(MessageClassification.category_key).where(
                    MessageClassification.message_id == msg.id,
                    MessageClassification.rules_run_at.isnot(None),
                )
            )
        ).all()
    }
    if category in ran_before:
        return row, [], False
    ran, drafted = await run_rules(db, actor, msg, cat)
    row.rules_run_at, row.rules_run = L.now(), ran
    return row, ran, drafted


async def run_rules(
    db: AsyncSession, actor: CurrentUser, msg: Message, cat: ReplyCategory
) -> tuple[list[str], bool]:
    from app.modules.outreach import service as O  # outreach builds on the inbox

    conv = await db.get(Conversation, msg.conversation_id) if msg.conversation_id else None
    ran: list[str] = []
    drafted = False
    for rule in await rules_of(db, cat.id):
        if not rule.active:
            continue
        a = rule.action
        if a == "convert":
            if conv is None or conv.lead_id is not None or conv.contact_id is None:
                continue  # leads are already in the CRM
            from app.modules.outreach.models import Contact

            contact = await db.get(Contact, conv.contact_id)
            await O.convert(db, actor, contact)
        elif a == "draft":
            if conv is None or conv.channel != "email":
                continue
            req = DraftRequest(
                id=uuid.uuid4(), tenant_id=msg.tenant_id, message_id=msg.id,
                conversation_id=conv.id, category_key=cat.key, rule_id=rule.id,
                instructions=rule.instructions,
            )  # fmt: skip
            db.add(req)
            await db.flush()
            await emit(
                db,
                msg.tenant_id,
                "draft.requested",
                {
                    "request_id": str(req.id),
                    "message_id": str(msg.id),
                    "conversation_id": str(conv.id),
                    "contact_id": str(conv.contact_id) if conv.contact_id else None,
                    "lead_id": str(conv.lead_id) if conv.lead_id else None,
                    "category": cat.key,
                    "rule_id": str(rule.id),
                    "instructions": rule.instructions,
                },
            )
            drafted = True
        elif a == "stop":
            if conv is not None and conv.lead_id is None and conv.contact_id:
                await O.stop(db, conv.contact_id, "stopped", f"sorted_{cat.key}"[:40],
                             campaign_id=conv.campaign_id)  # fmt: skip
            elif msg.lead_id:
                from app.modules.engage import engine as E

                await E.stop_all(db, msg.lead_id, "reply")
        elif a == "unsubscribe":
            address = (msg.from_address or "").lower()
            if not address:
                continue
            await C.suppress(db, msg.tenant_id, "email", [address], "opt_out")
            if msg.contact_id:
                await O.contact_opted_out(db, msg.contact_id, "opt_out")
            if msg.lead_id and (lead := await db.get(Lead, msg.lead_id)):
                from app.modules.engage import engine as E

                if lead.email_consent != "opted_out":
                    await C.record(
                        db,
                        lead,
                        "email",
                        "opted_out",
                        "unsubscribe",
                        evidence={"message_id": str(msg.id), "reason": "reply"},
                    )
                await E.stop_all(db, lead.id, "unsubscribed")  # fmt: skip
        elif a == "notify":
            if conv is None:
                continue
            owner = await IB.assignee_of(db, conv) if conv.lead_id else conv.assignee_user_id
            if owner is None and conv.campaign_id:
                from app.modules.outreach.models import Campaign

                camp = await db.get(Campaign, conv.campaign_id)
                owner = camp.owner_user_id if camp else None
            if owner:
                await notify(db, msg.tenant_id, [owner], "inbox",
                             f"Reply sorted as {cat.name}: {msg.subject or '(no subject)'}",
                             conv.lead_id)  # fmt: skip
        ran.append(a)
    if ran or cat.needs_human:
        await _note(
            db, conv, actor, f"Sorted as {cat.name}" + (f" → {', '.join(ran)}" if ran else "")
        )
    return ran, drafted


async def _note(db: AsyncSession, conv: Conversation | None, actor: CurrentUser | None,
                text: str) -> None:  # fmt: skip
    if conv is None:
        return
    by = actor.user.id if actor else None
    db.add(
        ConversationNote(tenant_id=conv.tenant_id, conversation_id=conv.id, user_id=by,
                         body=text[:2000])
    )  # fmt: skip


# ---------- drafts ----------
async def pending_draft(db: AsyncSession, conv_id: uuid.UUID) -> Draft | None:
    return await db.scalar(
        select(Draft).where(Draft.conversation_id == conv_id, Draft.status == "pending")
    )


async def supersede(db: AsyncSession, conv_id: uuid.UUID, newer: Message) -> None:
    """The other side wrote again before anyone decided: the waiting draft is out of date."""
    d = await pending_draft(db, conv_id)
    if d is None:
        return
    d.status, d.superseded_by_message_id = "superseded", newer.id
    await db.flush()
    await emit(db, d.tenant_id, "draft.superseded", {
        "draft_id": str(d.id), "conversation_id": str(conv_id), "newer_message_id": str(newer.id),
    })  # fmt: skip


async def _newer_reply(db: AsyncSession, conv_id: uuid.UUID, msg: Message) -> Message | None:
    return await db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conv_id,
            Message.direction == "in",
            Message.auto_submitted.is_(False),
            Message.id != msg.id,
            func.coalesce(Message.sent_at, Message.created_at)
            > func.coalesce(msg.sent_at, msg.created_at),
        )
        .limit(1)
    )


async def create_draft(
    db: AsyncSession,
    actor: CurrentUser,
    conv: Conversation,
    *,
    request_id: uuid.UUID | None,
    reply_to_message_id: uuid.UUID,
    body: str,
    reasons: list[str],
    language: str | None,
) -> Draft:
    if request_id is not None:
        same = await db.scalar(select(Draft).where(Draft.request_id == request_id))
        if same is not None:
            if same.conversation_id != conv.id:
                raise Invalid("That request_id belongs to another conversation")
            return same  # a retry: the same draft
        req = await db.get(DraftRequest, request_id)
        if req is None or req.conversation_id != conv.id:
            raise Invalid("Unknown request_id for this conversation", code="unknown_request")
    if conv.channel != "email":
        raise Invalid("Drafts are for email conversations", code="draft_channel_unsupported")
    if conv.status == "closed":
        raise Invalid("This conversation is closed", code="conversation_closed")
    msg = await db.get(Message, reply_to_message_id)
    if msg is None or msg.conversation_id != conv.id or msg.direction != "in":
        raise Invalid("reply_to_message_id must be a reply in this conversation")
    if await _newer_reply(db, conv.id, msg):
        raise Invalid("A newer reply arrived; draft against that one", code="draft_superseded")
    await _check_sendable(db, conv)
    old = await pending_draft(db, conv.id)
    if old is not None:  # one waiting draft per conversation: the new one replaces it
        old.status, old.superseded_by_message_id = "superseded", msg.id
        await db.flush()
        await emit(db, conv.tenant_id, "draft.superseded", {
            "draft_id": str(old.id), "conversation_id": str(conv.id),
            "newer_message_id": str(msg.id),
        })  # fmt: skip
    d = Draft(
        id=uuid.uuid4(), tenant_id=conv.tenant_id, conversation_id=conv.id,
        reply_to_message_id=msg.id, request_id=request_id, body=body, reasons=reasons[:5],
        language=language, status="pending", created_by_user_id=actor.user.id,
    )  # fmt: skip
    db.add(d)
    await db.flush()
    if request_id is not None:
        await db.execute(
            update(DraftRequest).where(DraftRequest.id == request_id).values(draft_id=d.id)
        )
    await emit(db, conv.tenant_id, "draft.created", {
        "draft_id": str(d.id), "conversation_id": str(conv.id),
        "request_id": str(request_id) if request_id else None,
        "created_by": str(actor.user.id),
    })  # fmt: skip
    return d


async def _check_sendable(db: AsyncSession, conv: Conversation) -> None:
    to = await _their_address(db, conv)
    if not to:
        raise Invalid("There is no address to answer", code="no_email")
    reasons = set(
        (
            await db.scalars(
                select(Suppression.reason).where(
                    Suppression.channel == "email", Suppression.value_normalized == to.lower()
                )
            )
        ).all()
    )
    if reasons & {"bounce", "complaint"}:
        raise Invalid(
            "This address bounced or complained before; it can't be emailed",
            code="email_suppressed",
        )


async def _their_address(db: AsyncSession, conv: Conversation) -> str | None:
    if conv.lead_id:
        lead = await db.get(Lead, conv.lead_id)
        return lead.primary_email if lead else None
    if conv.contact_id:
        from app.modules.outreach.models import Contact

        c = await db.get(Contact, conv.contact_id)
        return c.email if c else None
    return None


# ---------- who may decide ----------
async def can_answer(db: AsyncSession, person: CurrentUser, conv: Conversation) -> bool:
    """The person may answer this conversation (and so approve its draft)."""
    if conv.lead_id is not None:
        if not has_permission(person.permissions, "inbox.reply"):
            return False
        seen = await db.scalar(
            select(Conversation.id).where(Conversation.id == conv.id, await IB.visible(db, person))
        )
        return seen is not None
    from app.modules.outreach import service as O

    if not has_permission(person.permissions, "outreach.reply"):
        return False
    seen = await db.scalar(
        select(Conversation.id).where(Conversation.id == conv.id, O.conversation_filter(person))
    )
    return seen is not None


async def decider(
    db: AsyncSession, actor: CurrentUser, conv: Conversation, on_behalf_of: uuid.UUID | None
) -> tuple[CurrentUser, str]:
    """(the person deciding, via). With on_behalf_of (ACE's Slack clicks) that person's own
    rights are checked, not the key's."""
    if on_behalf_of is None:
        if not await can_answer(db, actor, conv):
            raise Forbidden("permission_denied")
        return actor, "core"
    if not has_permission(actor.permissions, "drafts.approve_for_users"):
        raise Forbidden("permission_denied")
    from app.modules.crm.imports import load_actor
    from app.modules.users.models import User

    user = await db.get(User, on_behalf_of)
    if user is None:
        raise Invalid("That person is not in this company", code="user_cannot_approve")
    if user.status != "active":
        raise Invalid("That person's account is not active", code="user_inactive")
    person = await load_actor(db, on_behalf_of)
    if person is None or not await can_answer(db, person, conv):
        raise Invalid("That person can't answer this conversation", code="user_cannot_approve")
    return person, "slack"


async def _decidable(d: Draft) -> None:
    if d.status == "superseded":
        raise Invalid("A newer reply arrived; this draft is out of date", code="draft_superseded")
    if d.status != "pending":
        raise Invalid("This draft was already decided", code="draft_already_decided")


async def approve(
    db: AsyncSession,
    actor: CurrentUser,
    d: Draft,
    *,
    on_behalf_of: uuid.UUID | None,
    body: str | None,
) -> Message:
    conv = await db.get(Conversation, d.conversation_id)
    person, via = await decider(db, actor, conv, on_behalf_of)
    await _decidable(d)
    text = body if body is not None and body.strip() else d.body
    changed = text != d.body
    if conv.lead_id is not None:
        lead = await db.get(Lead, conv.lead_id)
        subject = conv.subject or "(no subject)"
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        try:
            sent = await IB.send(db, person, lead, conv, subject=subject, body=text, cc=[])
        except Invalid as err:
            d.error = str(err.detail)[:300]
            raise
    else:
        from app.modules.outreach import replying

        try:
            sent = await replying.reply(db, person, conv, text)
        except Invalid as err:
            d.error = str(err.detail)[:300]
            raise
    d.status, d.decided_by_user_id, d.via, d.body_changed = "sent", person.user.id, via, changed
    d.message_id, d.decided_at, d.error = sent.id, L.now(), None
    if changed:
        d.body = text
    who = person.user.name + (" via Slack (ACE)" if via == "slack" else "")
    await _note(db, conv, person, f"Draft {'edited and ' if changed else ''}approved by {who}")
    await emit(db, d.tenant_id, "draft.approved", {
        "draft_id": str(d.id), "conversation_id": str(conv.id),
        "decided_by_user_id": str(person.user.id), "via": via, "body_changed": changed,
        "message_id": str(sent.id),
    })  # fmt: skip
    return sent


async def reject(
    db: AsyncSession,
    actor: CurrentUser,
    d: Draft,
    *,
    on_behalf_of: uuid.UUID | None,
    reason: str | None,
) -> None:
    conv = await db.get(Conversation, d.conversation_id)
    person, via = await decider(db, actor, conv, on_behalf_of)
    await _decidable(d)
    d.status, d.decided_by_user_id, d.via, d.reject_reason = "rejected", person.user.id, via, reason
    d.decided_at = L.now()
    who = person.user.name + (" via Slack (ACE)" if via == "slack" else "")
    await _note(db, conv, person, f"Draft rejected by {who}" + (f": {reason}" if reason else ""))
    await emit(db, d.tenant_id, "draft.rejected", {
        "draft_id": str(d.id), "conversation_id": str(conv.id),
        "decided_by_user_id": str(person.user.id), "via": via, "body_changed": False,
        "reason": reason,
    })  # fmt: skip


async def get_draft(db: AsyncSession, draft_id: uuid.UUID) -> Draft:
    d = await db.get(Draft, draft_id)
    if d is None:
        raise NotFound("Draft not found")
    return d

"""The shared inbox (step 9b-1, Decision log #40): conversations, replies, colleagues, internal
notes, saved replies, attachments, and a test inbound endpoint until real mail arrives."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import distinct_on, insert

from app.core import storage
from app.core.config import get_settings
from app.core.errors import Forbidden, Invalid, NotFound
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm import customers as CU
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import Lead, LeadStage, StoredFile
from app.modules.crm.notify import notify
from app.modules.engage import inbox as IB
from app.modules.engage.models import (
    CannedReply,
    Conversation,
    ConversationMember,
    ConversationNote,
    ConversationRead,
    Message,
    MessageAttachment,
)
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["inbox"], dependencies=CRM)
Replier = Annotated[CurrentUser, require("inbox.reply")]


# ---------- shapes ----------
class ConversationRow(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    lead_name: str
    subject: str | None
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    status: str
    is_private: bool
    last_message_at: datetime | None
    waiting: bool  # the last message is theirs
    unread: bool
    snippet: str | None
    shared: bool  # this person was added to it


class AttachmentOut(BaseModel):
    file_id: uuid.UUID
    name: str
    size_bytes: int
    content_type: str


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: str
    from_address: str | None
    to_address: str
    cc: list[str]
    subject: str | None
    body: str
    status: str
    error: str | None
    sent_at: datetime | None
    created_at: datetime
    opened_at: datetime | None
    clicked_at: datetime | None
    sent_by_name: str | None
    from_sequence: bool
    attachments: list[AttachmentOut]


class NoteOut(BaseModel):
    id: uuid.UUID
    user_name: str | None
    body: str
    created_at: datetime


class Member(BaseModel):
    user_id: uuid.UUID
    name: str


class LeadBasics(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    stage: str | None
    owner_name: str | None
    can_open: bool  # may open the full lead page


class ConversationDetail(BaseModel):
    id: uuid.UUID
    subject: str | None
    status: str
    is_private: bool
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    lead: LeadBasics
    members: list[Member]
    messages: list[MessageOut]
    notes: list[NoteOut]
    can_reply: bool
    can_manage: bool


# ---------- list ----------
View = Literal["mine", "shared", "unassigned", "waiting", "all", "closed"]


@router.get("/inbox", response_model=list[ConversationRow])
async def inbox(
    db: CrmDb,
    actor: Replier,
    view: View = "mine",
    q: str | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConversationRow]:
    me = actor.user.id
    owner = select(Lead.owner_user_id).where(Lead.id == Conversation.lead_id).scalar_subquery()
    mine_cond = or_(
        Conversation.assignee_user_id == me,
        and_(Conversation.assignee_user_id.is_(None), owner == me),
    )
    member_q = select(ConversationMember.conversation_id).where(ConversationMember.user_id == me)
    where = [
        await IB.visible(db, actor),
        # threads only a sequence wrote in stay out of the inbox until the person answers
        or_(Conversation.last_inbound_at.isnot(None), Conversation.created_by_user_id.isnot(None)),
    ]
    if view == "closed":
        where.append(Conversation.status == "closed")
    else:
        where.append(Conversation.status == "open")
    if view == "mine":
        where.append(mine_cond)
    elif view == "shared":
        where.append(Conversation.id.in_(member_q))
    elif view == "unassigned":
        where += [Conversation.assignee_user_id.is_(None), owner.is_(None)]
    elif view == "waiting":
        where.append(Conversation.last_direction == "in")
    if q and q.strip():
        term = f"%{q.strip()}%"
        where.append(
            or_(
                Conversation.subject.ilike(term),
                Conversation.lead_id.in_(select(Lead.id).where(Lead.display_name.ilike(term))),
            )
        )
    if before:
        where.append(Conversation.last_message_at < before)
    rows = (
        await db.scalars(
            select(Conversation)
            .where(*where)
            .order_by(Conversation.last_message_at.desc().nulls_last())
            .limit(limit)
        )
    ).all()
    return await _rows(db, actor, list(rows))


async def _rows(db, actor: CurrentUser, rows: list[Conversation]) -> list[ConversationRow]:
    if not rows:
        return []
    ids = [c.id for c in rows]
    leads = {
        lead.id: lead
        for lead in (
            await db.scalars(select(Lead).where(Lead.id.in_({c.lead_id for c in rows})))
        ).all()
    }
    reads = dict(
        (
            await db.execute(
                select(ConversationRead.conversation_id, ConversationRead.read_at).where(
                    ConversationRead.conversation_id.in_(ids),
                    ConversationRead.user_id == actor.user.id,
                )
            )
        ).all()
    )
    shared = set(
        (
            await db.scalars(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.conversation_id.in_(ids),
                    ConversationMember.user_id == actor.user.id,
                )
            )
        ).all()
    )
    last = {}
    for m in (
        await db.scalars(
            select(Message)
            .ext(distinct_on(Message.conversation_id))
            .where(Message.conversation_id.in_(ids))
            .order_by(Message.conversation_id, Message.created_at.desc())
        )
    ).all():
        last[m.conversation_id] = m
    assignees = {c.id: c.assignee_user_id or leads[c.lead_id].owner_user_id for c in rows}
    names = dict(
        (
            await db.execute(
                select(User.id, User.name).where(User.id.in_({a for a in assignees.values() if a}))
            )
        ).all()
    )
    return [
        ConversationRow(
            id=c.id,
            lead_id=c.lead_id,
            lead_name=leads[c.lead_id].display_name,
            subject=c.subject,
            assignee_id=assignees[c.id],
            assignee_name=names.get(assignees[c.id]),
            status=c.status,
            is_private=c.is_private,
            last_message_at=c.last_message_at,
            waiting=c.last_direction == "in",
            unread=bool(
                c.last_inbound_at and (reads.get(c.id) is None or reads[c.id] < c.last_inbound_at)
            ),
            snippet=(last[c.id].body or "")[:160] if c.id in last else None,
            shared=c.id in shared,
        )
        for c in rows
    ]


@router.get("/leads/{lead_id}/conversations", response_model=list[ConversationRow])
async def lead_conversations(
    lead_id: uuid.UUID, db: CrmDb, actor: Replier
) -> list[ConversationRow]:
    lead = await L.get_visible(db, actor, lead_id)
    rows = (
        await db.scalars(
            select(Conversation)
            .where(Conversation.lead_id == lead.id, await IB.visible(db, actor))
            .order_by(Conversation.last_message_at.desc().nulls_last())
        )
    ).all()
    return await _rows(db, actor, list(rows))


# ---------- one conversation ----------
async def _detail(db, actor: CurrentUser, conv: Conversation) -> ConversationDetail:
    lead = await db.get(Lead, conv.lead_id)
    msgs = (
        await db.scalars(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
        )
    ).all()
    files: dict[uuid.UUID, list[AttachmentOut]] = {}
    if msgs:
        for att, f in (
            await db.execute(
                select(MessageAttachment, StoredFile)
                .join(StoredFile, StoredFile.id == MessageAttachment.file_id)
                .where(MessageAttachment.message_id.in_([m.id for m in msgs]))
            )
        ).all():
            files.setdefault(att.message_id, []).append(
                AttachmentOut(
                    file_id=f.id,
                    name=f.original_name,
                    size_bytes=f.size_bytes,
                    content_type=f.content_type,
                )
            )
    notes = (
        await db.scalars(
            select(ConversationNote)
            .where(ConversationNote.conversation_id == conv.id)
            .order_by(ConversationNote.created_at)
        )
    ).all()
    members = (
        await db.scalars(
            select(ConversationMember).where(ConversationMember.conversation_id == conv.id)
        )
    ).all()
    assignee = await IB.assignee_of(db, conv)
    user_ids = (
        {m.sent_by_user_id for m in msgs}
        | {n.user_id for n in notes}
        | {m.user_id for m in members}
    )
    user_ids |= {assignee, lead.owner_user_id}
    names = dict(
        (
            await db.execute(
                select(User.id, User.name).where(User.id.in_({u for u in user_ids if u}))
            )
        ).all()
    )
    stage = await db.get(LeadStage, lead.stage_id)
    can_open = bool(
        await db.scalar(
            select(Lead.id).where(Lead.id == lead.id, await L.visibility_filter(db, actor))
        )
    )
    return ConversationDetail(
        id=conv.id,
        subject=conv.subject,
        status=conv.status,
        is_private=conv.is_private,
        assignee_id=assignee,
        assignee_name=names.get(assignee),
        lead=LeadBasics(
            id=lead.id,
            name=lead.display_name,
            email=lead.primary_email,
            phone=lead.primary_phone,
            stage=stage.name if stage else None,
            owner_name=names.get(lead.owner_user_id),
            can_open=can_open,
        ),
        members=[Member(user_id=m.user_id, name=names.get(m.user_id, "—")) for m in members],
        messages=[
            MessageOut(
                id=m.id,
                direction=m.direction,
                from_address=m.from_address,
                to_address=m.to_address,
                cc=m.cc or [],
                subject=m.subject,
                body=m.body,
                status=m.status,
                error=m.error,
                sent_at=m.sent_at,
                created_at=m.created_at,
                opened_at=m.opened_at,
                clicked_at=m.clicked_at,
                sent_by_name=names.get(m.sent_by_user_id),
                from_sequence=m.enrolment_id is not None and m.direction == "out",
                attachments=files.get(m.id, []),
            )
            for m in msgs
        ],
        notes=[
            NoteOut(id=n.id, user_name=names.get(n.user_id), body=n.body, created_at=n.created_at)
            for n in notes
        ],
        can_reply=True,
        can_manage=await IB.can_manage(db, actor, conv),
    )


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(conv_id: uuid.UUID, db: CrmDb, actor: Replier) -> ConversationDetail:
    conv = await IB.get_visible(db, actor, conv_id)
    await _mark_read(db, actor, conv)
    return await _detail(db, actor, conv)


async def _mark_read(db, actor: CurrentUser, conv: Conversation) -> None:
    await db.execute(
        insert(ConversationRead)
        .values(
            id=uuid.uuid4(),
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            user_id=actor.user.id,
            read_at=L.now(),
        )
        .on_conflict_do_update(constraint="uq_conversation_reads", set_={"read_at": L.now()})
    )


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=50000)
    cc: list[str] = Field(default=[], max_length=20)


class NewEmailIn(ReplyIn):
    subject: str = Field(min_length=1, max_length=300)


@router.post("/conversations/{conv_id}/reply", response_model=ConversationDetail)
async def reply(conv_id: uuid.UUID, body: ReplyIn, db: CrmDb, actor: Replier) -> ConversationDetail:
    conv = await IB.get_visible(db, actor, conv_id)
    lead = await db.get(Lead, conv.lead_id)
    subject = conv.subject or "(no subject)"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    await IB.send(db, actor, lead, conv, subject=subject, body=body.body, cc=body.cc)
    await _mark_read(db, actor, conv)
    await db.flush()
    return await _detail(db, actor, conv)


@router.post(
    "/leads/{lead_id}/emails",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def new_email(
    lead_id: uuid.UUID, body: NewEmailIn, db: CrmDb, actor: Replier
) -> ConversationDetail:
    """A new email to a lead you can see; starts a conversation."""
    lead = await L.get_visible(db, actor, lead_id)
    msg = await IB.send(db, actor, lead, None, subject=body.subject, body=body.body, cc=body.cc)
    await db.flush()
    return await _detail(db, actor, await db.get(Conversation, msg.conversation_id))


class ConvPatch(BaseModel):
    status: Literal["open", "closed"] | None = None
    is_private: bool | None = None


@router.patch("/conversations/{conv_id}", response_model=ConversationDetail)
async def update_conversation(conv_id: uuid.UUID, body: ConvPatch, db: CrmDb, actor: Replier):
    conv = await IB.get_visible(db, actor, conv_id)
    if body.status:
        conv.status = body.status
    if body.is_private is not None:
        if (
            body.is_private
            and await IB.assignee_of(db, conv) != actor.user.id
            and actor.role.key not in IB.ADMINS
        ):
            raise Forbidden("Only the person it belongs to can make it private")
        conv.is_private, conv.private_user_id = (
            body.is_private,
            actor.user.id if body.is_private else None,
        )
    await db.flush()
    return await _detail(db, actor, conv)


class AssignIn(BaseModel):
    user_id: uuid.UUID | None  # None: back to the lead's owner


@router.put("/conversations/{conv_id}/assignee", response_model=ConversationDetail)
async def assign(conv_id: uuid.UUID, body: AssignIn, db: CrmDb, actor: Replier):
    """Take over (yourself) or hand on (someone else)."""
    conv = await IB.get_visible(db, actor, conv_id)
    if not await IB.can_manage(db, actor, conv):
        raise Forbidden("Only the person it belongs to or a manager can hand it on")
    if body.user_id:
        user = await db.get(User, body.user_id)
        if user is None or user.status != "active":
            raise Invalid("Choose an active team member")
    conv.assignee_user_id = body.user_id
    if body.user_id and body.user_id != actor.user.id:
        await notify(
            db,
            conv.tenant_id,
            [body.user_id],
            "inbox",
            f"{actor.user.name} handed you a conversation: {conv.subject or ''}",
            conv.lead_id,
        )
    await audit(
        db,
        actor,
        "conversation.assigned",
        "conversation",
        conv.id,
        None,
        {"to": str(body.user_id) if body.user_id else None},
    )
    await db.flush()
    return await _detail(db, actor, conv)


class MemberIn(BaseModel):
    user_id: uuid.UUID


async def _add_member(db, actor: CurrentUser, conv: Conversation, user_id: uuid.UUID) -> bool:
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise Invalid("Choose an active team member")
    if await IB.is_member(db, conv, user_id):
        return False
    db.add(
        ConversationMember(
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            user_id=user_id,
            added_by_user_id=actor.user.id,
        )
    )
    await audit(
        db, actor, "conversation.shared", "conversation", conv.id, None, {"with": str(user_id)}
    )
    return True


@router.post("/conversations/{conv_id}/members", response_model=ConversationDetail)
async def add_member(conv_id: uuid.UUID, body: MemberIn, db: CrmDb, actor: Replier):
    """Add a colleague: they see this conversation and the lead's basics, and can reply."""
    conv = await IB.get_visible(db, actor, conv_id)
    if not await IB.can_manage(db, actor, conv):
        raise Forbidden("Only the person it belongs to or a manager can add colleagues")
    if await _add_member(db, actor, conv, body.user_id):
        lead = await db.get(Lead, conv.lead_id)
        await notify(
            db,
            conv.tenant_id,
            [body.user_id],
            "inbox",
            f"{actor.user.name} added you to a conversation with {lead.display_name}",
            lead.id,
        )
    await db.flush()
    return await _detail(db, actor, conv)


@router.delete("/conversations/{conv_id}/members/{user_id}", response_model=ConversationDetail)
async def remove_member(conv_id: uuid.UUID, user_id: uuid.UUID, db: CrmDb, actor: Replier):
    conv = await IB.get_visible(db, actor, conv_id)
    if not await IB.can_manage(db, actor, conv) and user_id != actor.user.id:
        raise Forbidden("Only the person it belongs to or a manager can remove colleagues")
    await db.execute(
        delete(ConversationMember).where(
            ConversationMember.conversation_id == conv.id, ConversationMember.user_id == user_id
        )
    )
    await db.flush()
    if user_id == actor.user.id and not await db.scalar(
        select(Conversation.id).where(Conversation.id == conv.id, await IB.visible(db, actor))
    ):
        raise NotFound("You left the conversation")
    return await _detail(db, actor, conv)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    mention_ids: list[uuid.UUID] = Field(default=[], max_length=20)


@router.post("/conversations/{conv_id}/notes", response_model=ConversationDetail)
async def add_note(conv_id: uuid.UUID, body: NoteIn, db: CrmDb, actor: Replier):
    """An internal note: the team sees it, the lead never does. Mentioned colleagues are told;
    when the writer may add colleagues, mentioned people are added so they can see it."""
    conv = await IB.get_visible(db, actor, conv_id)
    lead = await db.get(Lead, conv.lead_id)
    manage = await IB.can_manage(db, actor, conv)
    told = []
    for uid in dict.fromkeys(body.mention_ids):
        if uid == actor.user.id:
            continue
        if manage:
            await _add_member(db, actor, conv, uid)
            told.append(uid)
        else:
            user = await db.get(User, uid)
            if user and await _can_see(db, user, conv):
                told.append(uid)
    db.add(
        ConversationNote(
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            user_id=actor.user.id,
            body=body.body,
            mentions=[str(u) for u in told],
        )
    )
    if told:
        await notify(
            db,
            conv.tenant_id,
            told,
            "inbox",
            f"{actor.user.name} mentioned you about {lead.display_name}: {body.body[:120]}",
            lead.id,
        )
    await db.flush()
    return await _detail(db, actor, conv)


async def _can_see(db, user: User, conv: Conversation) -> bool:
    from app.modules.auth.deps import effective_permissions
    from app.modules.roles.models import Role

    role = await db.get(Role, user.role_id)
    other = CurrentUser(
        user=user, role=role, restrictions=[], permissions=await effective_permissions(db, role)
    )
    return bool(
        await db.scalar(
            select(Conversation.id).where(Conversation.id == conv.id, await IB.visible(db, other))
        )
    )


# ---------- attachments ----------
async def _attachment(
    db, actor, conv_id: uuid.UUID, file_id: uuid.UUID
) -> tuple[Conversation, StoredFile]:
    conv = await IB.get_visible(db, actor, conv_id)
    f = await db.scalar(
        select(StoredFile)
        .join(MessageAttachment, MessageAttachment.file_id == StoredFile.id)
        .join(Message, Message.id == MessageAttachment.message_id)
        .where(StoredFile.id == file_id, Message.conversation_id == conv.id)
    )
    if f is None:
        raise NotFound("Attachment not found")
    return conv, f


@router.get(
    "/conversations/{conv_id}/attachments/{file_id}",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_attachment(conv_id: uuid.UUID, file_id: uuid.UUID, db: CrmDb, actor: Replier):
    _, f = await _attachment(db, actor, conv_id, file_id)
    path = storage.full_path(f.path)
    if not path.exists():
        raise NotFound("This file is missing on the server")
    return FileResponse(
        path,
        media_type=f.content_type,
        filename=f.original_name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


class ToDocumentIn(BaseModel):
    document_id: uuid.UUID


@router.post(
    "/conversations/{conv_id}/attachments/{file_id}/to-document",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def attachment_to_document(
    conv_id: uuid.UUID, file_id: uuid.UUID, body: ToDocumentIn, db: CrmDb, actor: Replier
) -> None:
    """Put an emailed file (PAN card, signed contract) into the customer's checklist."""
    conv, f = await _attachment(db, actor, conv_id, file_id)
    customer = await CU.of_lead(db, conv.lead_id)
    if customer is None:
        raise Invalid("Make this lead a customer first")
    customer, lead = await CU.get_editable(db, actor, customer.id)
    doc = await CU.get_document(db, customer, body.document_id)
    f.document_id = doc.id
    doc.status, doc.received_at = "received", L.now()
    doc.reject_reason = doc.reviewed_at = doc.reviewed_by_user_id = None
    await L.log(
        db,
        lead,
        "document_uploaded",
        f"{doc.name}: {f.original_name} (from an email)",
        actor,
        {"customer_id": str(customer.id), "document_id": str(doc.id), "file_id": str(f.id)},
    )
    await L.event(
        db,
        lead,
        "document.received",
        {"customer_id": str(customer.id), "document_id": str(doc.id), "name": doc.name},
    )


# ---------- saved replies ----------
class CannedIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=10000)
    is_shared: bool = False


class CannedOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    body: str
    is_shared: bool
    mine: bool = False


@router.get("/canned-replies", response_model=list[CannedOut])
async def list_canned(db: CrmDb, actor: Replier) -> list[CannedOut]:
    rows = (
        await db.scalars(
            select(CannedReply)
            .where(or_(CannedReply.is_shared.is_(True), CannedReply.user_id == actor.user.id))
            .order_by(CannedReply.name)
        )
    ).all()
    return [
        CannedOut.model_validate(r).model_copy(update={"mine": r.user_id == actor.user.id})
        for r in rows
    ]


def _may_share(actor: CurrentUser) -> bool:
    from app.modules.auth.deps import has_permission

    return has_permission(actor.permissions, "sequences.manage")


@router.post("/canned-replies", response_model=CannedOut, status_code=status.HTTP_201_CREATED)
async def create_canned(body: CannedIn, db: CrmDb, actor: Replier) -> CannedOut:
    if body.is_shared and not _may_share(actor):
        raise Forbidden("Only managers can share saved replies with everyone")
    r = CannedReply(
        id=uuid.uuid4(),
        tenant_id=actor.user.tenant_id,
        name=" ".join(body.name.split()),
        body=body.body,
        is_shared=body.is_shared,
        user_id=actor.user.id,
    )
    db.add(r)
    await db.flush()
    return CannedOut.model_validate(r).model_copy(update={"mine": True})


@router.delete("/canned-replies/{c_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_canned(c_id: uuid.UUID, db: CrmDb, actor: Replier) -> None:
    r = await db.get(CannedReply, c_id)
    if r is None or (r.user_id != actor.user.id and not (r.is_shared and _may_share(actor))):
        raise NotFound("Saved reply not found")
    await db.delete(r)


# ---------- colleagues to add or mention ----------
class Person(BaseModel):
    id: uuid.UUID
    name: str


@router.get("/inbox/people", response_model=list[Person])
async def inbox_people(db: CrmDb, actor: Replier) -> list[Person]:
    """Active team members' names, to add to a conversation or mention in a note."""
    rows = (
        await db.execute(
            select(User.id, User.name).where(User.status == "active").order_by(User.name)
        )
    ).all()
    return [Person(id=i, name=n) for i, n in rows]


# ---------- counts for the sidebar ----------
class InboxCounts(BaseModel):
    mine_unread: int
    waiting: int


@router.get("/inbox/counts", response_model=InboxCounts)
async def inbox_counts(db: CrmDb, actor: Replier) -> InboxCounts:
    rows = await inbox(db=db, actor=actor, view="mine", q=None, before=None, limit=100)
    return InboxCounts(
        mine_unread=sum(r.unread for r in rows), waiting=sum(r.waiting for r in rows)
    )


# ---------- test inbound (until real mail arrives at go-live) ----------
class TestInboundOut(BaseModel):
    stored: bool
    conversation_id: uuid.UUID | None = None


@router.post("/inbox/test-inbound", response_model=TestInboundOut)
async def test_inbound(
    request: Request, db: CrmDb, actor: Annotated[CurrentUser, require("settings.manage")]
) -> TestInboundOut:
    """Outside production only: deliver a raw email (.eml text) as if it had arrived, so the
    inbox can be tried end to end before the email provider is connected."""
    if get_settings().environment == "prod":
        raise NotFound("Not found")
    raw = await request.body()
    if not raw or len(raw) > 25 * 1024 * 1024:
        raise Invalid("Send the raw email (an .eml file's text)")
    msg = await IB.ingest(db, actor.user.tenant_id, raw)
    return TestInboundOut(
        stored=msg is not None, conversation_id=msg.conversation_id if msg else None
    )

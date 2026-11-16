"""Newsletters (finishing plan, batch 5b): write, count the audience, test, send or schedule,
cancel, and the results. Needs newsletters.manage (Admin and Sales Manager by default)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.core.errors import Conflict, Invalid, NotFound
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import Lead
from app.modules.engage.models import Mailbox, Message
from app.modules.newsletters import postmark as PM
from app.modules.newsletters import service as S
from app.modules.newsletters.models import Newsletter, NewsletterSend

router = APIRouter(prefix="/api/v1/newsletters", tags=["newsletters"], dependencies=CRM)
Manager = Annotated[CurrentUser, require("newsletters.manage")]


class Audience(BaseModel):
    view_id: uuid.UUID | None = Field(default=None, description="a saved view of leads")
    filter: dict = Field(default={}, description="lead filters (tag, stage_id, brand_id…)")
    customers_only: bool = False


class NewsletterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=300)
    preheader: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=50000)
    path: Literal["mailboxes", "postmark"] = "mailboxes"
    mailbox_id: uuid.UUID | None = None
    from_name: str | None = Field(default=None, max_length=120)
    from_email: EmailStr | None = None
    audience: Audience = Audience()


class NewsletterPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    preheader: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=50000)
    path: Literal["mailboxes", "postmark"] | None = None
    mailbox_id: uuid.UUID | None = None
    from_name: str | None = Field(default=None, max_length=120)
    from_email: EmailStr | None = None
    audience: Audience | None = None


class Report(BaseModel):
    recipients: int = 0
    queued: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    opened: int = 0
    clicked: int = 0
    unsubscribed: int = 0
    bounced: int = 0


class NewsletterOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    subject: str
    preheader: str | None
    body: str
    path: str
    mailbox_id: uuid.UUID | None
    from_name: str | None
    from_email: str | None
    audience: dict
    status: str
    send_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    report: Report = Report()


class CountOut(BaseModel):
    matching: int
    reachable: int  # with an email address, not opted out, not suppressed


class SendIn(BaseModel):
    send_at: datetime | None = Field(default=None, description="empty = now")


class RecipientOut(BaseModel):
    lead_id: uuid.UUID | None
    name: str | None
    email: str
    status: str
    reason: str | None
    sent_at: datetime | None
    opened: bool
    clicked: bool
    unsubscribed: bool
    bounced: bool


async def _get(db, nl_id: uuid.UUID) -> Newsletter:
    nl = await db.get(Newsletter, nl_id)
    if nl is None:
        raise NotFound("Newsletter not found")
    return nl


async def _out(db, nl: Newsletter) -> NewsletterOut:
    out = NewsletterOut.model_validate(nl)
    out.report = Report(**await S.report(db, nl))
    return out


async def _check(db, data: dict) -> None:
    keys = set(await L.lead_fields(db))
    if "subject" in data:
        S.check_content(data["subject"], "", keys)
    if "body" in data:
        S.check_content("", data["body"], keys)
    if data.get("mailbox_id") and await db.get(Mailbox, data["mailbox_id"]) is None:
        raise Invalid("Choose a connected inbox", code="mailbox_missing")


@router.get("", response_model=list[NewsletterOut])
async def list_newsletters(db: CrmDb, actor: Manager) -> list[NewsletterOut]:
    rows = (await db.scalars(select(Newsletter).order_by(Newsletter.created_at.desc()))).all()
    return [await _out(db, nl) for nl in rows]


@router.post("", response_model=NewsletterOut, status_code=status.HTTP_201_CREATED)
async def create(body: NewsletterIn, db: CrmDb, actor: Manager) -> NewsletterOut:
    data = body.model_dump(mode="json")
    await _check(db, {**data, "mailbox_id": body.mailbox_id})
    nl = Newsletter(
        id=uuid.uuid4(), tenant_id=actor.user.tenant_id, created_by_user_id=actor.user.id,
        **{**data, "mailbox_id": body.mailbox_id},
    )  # fmt: skip
    db.add(nl)
    await db.flush()
    await db.refresh(nl)
    return await _out(db, nl)


@router.post("/audience-count", response_model=CountOut)
async def audience_count(body: Audience, db: CrmDb, actor: Manager) -> CountOut:
    matching, reachable = await S.count(db, actor, body.model_dump(mode="json"))
    return CountOut(matching=matching, reachable=reachable)


@router.get("/{nl_id}", response_model=NewsletterOut)
async def get_newsletter(nl_id: uuid.UUID, db: CrmDb, actor: Manager) -> NewsletterOut:
    return await _out(db, await _get(db, nl_id))


@router.patch("/{nl_id}", response_model=NewsletterOut)
async def update(
    nl_id: uuid.UUID, body: NewsletterPatch, db: CrmDb, actor: Manager
) -> NewsletterOut:
    nl = await _get(db, nl_id)
    if nl.status != "draft":
        raise Conflict("Only a draft can be changed", code="not_draft")
    data = body.model_dump(mode="json", exclude_unset=True)
    if "mailbox_id" in data:
        data["mailbox_id"] = body.mailbox_id
    await _check(db, data)
    for k, v in data.items():
        setattr(nl, k, v)
    await db.flush()
    await db.refresh(nl)
    return await _out(db, nl)


@router.delete("/{nl_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(nl_id: uuid.UUID, db: CrmDb, actor: Manager) -> None:
    nl = await _get(db, nl_id)
    if nl.status != "draft":
        raise Conflict("Only a draft can be deleted; cancel it instead", code="not_draft")
    await db.delete(nl)


@router.post("/{nl_id}/test", status_code=status.HTTP_204_NO_CONTENT)
async def test_send(nl_id: uuid.UUID, db: CrmDb, actor: Manager) -> None:
    """A copy to you, filled with a sample lead's details."""
    await S.test_send(db, actor, await _get(db, nl_id))


@router.post("/{nl_id}/send", response_model=NewsletterOut)
async def send(nl_id: uuid.UUID, body: SendIn, db: CrmDb, actor: Manager) -> NewsletterOut:
    """Fixes the list now; sends now or at `send_at`."""
    nl = await _get(db, nl_id)
    if nl.status != "draft":
        raise Conflict("This newsletter was already sent or scheduled", code="not_draft")
    if nl.path == "postmark":
        if not PM.configured():
            raise Invalid(
                "Postmark isn't set up yet: send through your inboxes", code="postmark_missing"
            )
        if not nl.from_email:
            raise Invalid("Postmark needs a From address", code="from_missing")
    people = await S.fix_list(db, actor, nl)
    if people == 0:
        raise Invalid("Nobody in this audience can get emails", code="audience_empty")
    later = body.send_at is not None and body.send_at > S.now()
    nl.status = "scheduled" if later else "sending"
    nl.send_at = body.send_at if later else S.now()
    nl.started_at = None if later else S.now()
    await db.flush()
    action = "newsletter.scheduled" if later else "newsletter.sent"
    after = {"recipients": people, "send_at": nl.send_at.isoformat()}
    await audit(db, actor, action, "newsletter", nl.id, after=after)
    if not later:
        from app.workers.queue import enqueue

        await enqueue("newsletters_job", defer_by=1, job_id=f"newsletters:{nl.tenant_id}")
    await db.refresh(nl)
    return await _out(db, nl)


@router.post("/{nl_id}/cancel", response_model=NewsletterOut)
async def cancel(nl_id: uuid.UUID, db: CrmDb, actor: Manager) -> NewsletterOut:
    """Stops it: copies not sent yet are not sent."""
    nl = await _get(db, nl_id)
    if nl.status not in ("scheduled", "sending"):
        raise Conflict(
            "Only a scheduled or sending newsletter can be cancelled", code="not_sending"
        )
    queued = await db.scalars(
        select(NewsletterSend).where(
            NewsletterSend.newsletter_id == nl.id, NewsletterSend.status == "queued"
        )
    )
    for s in queued.all():
        s.status, s.reason = "skipped", "cancelled"
    nl.status, nl.finished_at = "cancelled", S.now()
    await db.flush()
    await audit(db, actor, "newsletter.cancelled", "newsletter", nl.id)
    await db.refresh(nl)
    return await _out(db, nl)


@router.get("/{nl_id}/recipients", response_model=list[RecipientOut])
async def recipients(
    nl_id: uuid.UUID,
    db: CrmDb,
    actor: Manager,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 200,
) -> list[RecipientOut]:
    nl = await _get(db, nl_id)
    q = (
        select(NewsletterSend, Lead.display_name, Message)
        .outerjoin(Lead, Lead.id == NewsletterSend.lead_id)
        .outerjoin(Message, Message.id == NewsletterSend.message_id)
        .where(NewsletterSend.newsletter_id == nl.id)
        .order_by(NewsletterSend.sent_at.desc().nulls_last(), NewsletterSend.email)
        .limit(min(max(limit, 1), 1000))
    )
    if status_:
        q = q.where(NewsletterSend.status == status_)
    rows = (await db.execute(q)).all()
    return [
        RecipientOut(
            lead_id=s.lead_id,
            name=name,
            email=s.email,
            status=s.status,
            reason=s.reason,
            sent_at=s.sent_at,
            opened=bool(m and m.opened_at),
            clicked=bool(m and m.clicked_at),
            unsubscribed=bool(m and m.unsubscribed_at),
            bounced=bool(m and m.bounced_at),
        )  # fmt: skip
        for s, name, m in rows
    ]

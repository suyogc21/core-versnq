"""Newsletters (finishing plan, batch 5b).

Who gets it: the leads of a saved view and/or a filter (tags, stages, brand…), optionally only
customers, as the person sending it may see them. Only people with an email address, who haven't
opted out of email, aren't on the suppression list and weren't erased (rule 8). The list is
fixed when it's sent or scheduled; each person is checked again just before their copy goes.

How it goes: the worker sends in batches.
- "mailboxes": the company's own inboxes, within their daily limits and gaps (the pool, or one
  chosen inbox), or the company mailbox within the company's daily email cap. Whatever doesn't
  fit today waits for tomorrow. Meant for small lists until Postmark is bought.
- "postmark": Postmark's broadcast stream, 500 at a time (postmark.py).

Every copy is a normal outgoing email message, so opens, clicks, the one-click unsubscribe,
bounces and the suppression list work exactly as for sequences. Each copy writes one line on
the lead's timeline.
"""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid, NotFound
from app.core.tenancy import tenant_session
from app.modules.auth.deps import CurrentUser
from app.modules.crm import lead_query as Q
from app.modules.crm import leads as L
from app.modules.crm.models import Customer, Lead, SavedView, Suppression
from app.modules.engage import engine as E
from app.modules.engage import pool as P
from app.modules.engage import render as R
from app.modules.engage import sender as S
from app.modules.engage.models import Mailbox, Message
from app.modules.newsletters import postmark as PM
from app.modules.newsletters.models import Newsletter, NewsletterSend
from app.modules.settings.models import TenantSettings
from app.platform.models import Tenant

TICK = 200  # copies per worker run through mailboxes (each inbox's own limits apply too)
DEFAULT_CAP = 200


def now() -> datetime:
    return datetime.now(UTC)


# ---------- who gets it ----------
async def _filter(db: AsyncSession, audience: dict) -> Q.LeadFilter:
    fields = dict(audience.get("filter") or {})
    if view_id := audience.get("view_id"):
        view = await db.get(SavedView, uuid.UUID(str(view_id)))
        if view is None or view.entity != "leads":
            raise Invalid("That saved view doesn't exist", code="view_missing")
        fields = {**(view.filters or {}), **fields}
    try:
        return Q.LeadFilter(**fields)
    except ValueError:
        raise Invalid("The audience filter isn't valid") from None


def _reachable() -> list:
    """Leads who may get a newsletter (rule 8)."""
    suppressed = exists().where(
        Suppression.channel == "email",
        Suppression.value_normalized == func.lower(Lead.primary_email),
    )
    return [
        Lead.primary_email.is_not(None),
        Lead.primary_email != "",
        Lead.erased_at.is_(None),
        func.coalesce(Lead.email_consent, "") != "opted_out",
        ~suppressed,
    ]


async def audience_where(db: AsyncSession, actor: CurrentUser, audience: dict) -> list:
    where = await Q.where_clauses(db, actor, await _filter(db, audience))
    if audience.get("customers_only"):
        where.append(Lead.id.in_(select(Customer.lead_id)))
    return where


async def count(db: AsyncSession, actor: CurrentUser, audience: dict) -> tuple[int, int]:
    """(leads matching, of whom can get it)."""
    where = await audience_where(db, actor, audience)
    matching = await db.scalar(select(func.count()).select_from(Lead).where(*where)) or 0
    reachable = (
        await db.scalar(select(func.count()).select_from(Lead).where(*where, *_reachable())) or 0
    )
    return matching, reachable


async def fix_list(db: AsyncSession, actor: CurrentUser, nl: Newsletter) -> int:
    """Fixes the list at send / schedule time: one queued copy per person who can get it."""
    where = await audience_where(db, actor, nl.audience or {})
    rows = select(
        func.gen_random_uuid(),
        literal(nl.tenant_id),
        literal(nl.id),
        Lead.id,
        func.lower(Lead.primary_email),
        literal("queued"),
    ).where(*where, *_reachable())
    cols = ["id", "tenant_id", "newsletter_id", "lead_id", "email", "status"]
    await db.execute(pg_insert(NewsletterSend).from_select(cols, rows).on_conflict_do_nothing())
    return (
        await db.scalar(
            select(func.count())
            .select_from(NewsletterSend)
            .where(NewsletterSend.newsletter_id == nl.id)
        )
        or 0
    )


def check_content(nl_subject: str, body: str, custom_keys: set[str]) -> None:
    R.check(nl_subject, custom_keys)
    R.check(body, custom_keys)


# ---------- building one copy ----------
def _with_preheader(html: str, preheader: str | None) -> str:
    if not preheader:
        return html
    import html as H

    hidden = (
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
        f"{H.escape(preheader)}</div>"
    )
    return hidden + html


async def _from(db: AsyncSession, nl: Newsletter, tenant: Tenant) -> tuple[str, str]:
    if nl.path == "postmark":
        if not nl.from_email:
            raise Invalid("Postmark needs a From address", code="from_missing")
        return nl.from_name or tenant.name, nl.from_email
    name, email = await S.sender_address(db, tenant.name)
    return nl.from_name or name, email


async def _sender_mailbox(db: AsyncSession, nl: Newsletter, lead: Lead, tz: str) -> tuple:
    """(inbox or None, may send now). Through mailboxes: the chosen inbox, else the pool, else
    the company mailbox within the company's daily cap."""
    if nl.mailbox_id:
        mb = await db.get(Mailbox, nl.mailbox_id)
        if mb is None or mb.status != "active":
            raise Invalid("The chosen inbox isn't connected any more", code="mailbox_missing")
        today = await P.sent_since(db, P.start_of_day(tz))
        return mb, P._ready(mb, today, L.now())
    if await P.has_pool(db):
        mb = await P.pick(db, lead, tz)
        return mb, mb is not None
    settings = await db.get(TenantSettings, lead.tenant_id)
    cap = int((settings.engage or {}).get("daily_cap") or DEFAULT_CAP)
    return None, await E._sent_today(db, tz) < cap


def _build(nl: Newsletter, values: dict, token: str, base: str, signature: str | None):
    subject = R.fill(nl.subject, values).strip() or nl.name
    body = R.fill(nl.body, values)
    if signature:
        body = f"{body}\n\n{signature}"
    unsubscribe = f"{base}/api/v1/u/{token}"
    built = R.build_email(
        body, track_base=f"{base}/api/v1/t", token=token, unsubscribe_url=unsubscribe
    )
    return subject, body, built, unsubscribe


async def _still_ok(db: AsyncSession, lead: Lead | None, email: str) -> str | None:
    """Why this person can't get their copy now (they opted out after the list was fixed…)."""
    if lead is None or lead.erased_at:
        return "removed"
    if lead.email_consent == "opted_out":
        return "opted_out"
    if await db.scalar(
        select(Suppression.id).where(
            Suppression.channel == "email", Suppression.value_normalized == email.lower()
        )
    ):
        return "suppressed"
    return None


def _message(
    nl: Newsletter,
    lead: Lead,
    send: NewsletterSend,
    subject: str,
    body: str,
    built,
    token: str,
    from_email: str,
    header_id: str,
    mb: Mailbox | None,
) -> Message:
    return Message(
        id=uuid.uuid4(), tenant_id=nl.tenant_id, lead_id=lead.id, channel="email",
        direction="out", to_address=send.email, from_address=from_email, subject=subject,
        body=body, links=built.links, token=token, status="queued", message_id_header=header_id,
        mailbox_id=mb.id if mb else None,
    )  # fmt: skip


async def _sent(db: AsyncSession, nl: Newsletter, lead: Lead, send: NewsletterSend, msg: Message,
                provider_id: str | None) -> None:  # fmt: skip
    msg.status, msg.sent_at, msg.provider_id = "sent", now(), provider_id
    send.status, send.sent_at, send.message_id = "sent", msg.sent_at, msg.id
    await L.log(
        db, lead, "email_sent", f"Newsletter sent: {msg.subject}", None,
        {"newsletter_id": str(nl.id), "newsletter": nl.name, "message_id": str(msg.id)},
    )  # fmt: skip


async def _queued(db: AsyncSession, nl: Newsletter, limit: int) -> list[NewsletterSend]:
    return list(
        (
            await db.scalars(
                select(NewsletterSend)
                .where(NewsletterSend.newsletter_id == nl.id, NewsletterSend.status == "queued")
                .order_by(NewsletterSend.created_at, NewsletterSend.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )


async def _run_mailboxes(db: AsyncSession, nl: Newsletter, tenant: Tenant, tz: str) -> int:
    base = E.workspace_url(tenant.slug)
    done = 0
    for send in await _queued(db, nl, TICK):
        lead = await db.get(Lead, send.lead_id) if send.lead_id else None
        if why := await _still_ok(db, lead, send.email):
            send.status, send.reason = "skipped", why
            continue
        mb, may = await _sender_mailbox(db, nl, lead, tz)
        if not may:
            break  # every inbox is at today's limit (or in its gap): the rest waits
        if mb is not None:
            from app.modules.engage import mailsync as MS

            owner_name = mb.from_name or nl.from_name or tenant.name
            from_name, from_email, box, signature = (
                owner_name,
                mb.email_address,
                MS.box(mb),
                mb.signature,
            )
            mb.last_sent_at = now()
        else:
            (from_name, from_email), box, signature = await _from(db, nl, tenant), None, None
        token = secrets.token_urlsafe(24)
        subject, body, built, unsubscribe = _build(
            nl, await E.values_for(db, lead, tenant.name), token, base, signature
        )
        header_id = S.new_message_id(from_email)
        msg = _message(nl, lead, send, subject, body, built, token, from_email, header_id, mb)
        db.add(msg)
        await db.flush()
        try:
            sent = await S.send(
                db, to=send.email, subject=subject, text=built.text,
                html=_with_preheader(built.html, nl.preheader), from_name=from_name,
                from_email=from_email, unsubscribe_url=unsubscribe, message_id=header_id, box=box,
            )  # fmt: skip
        except Invalid as err:
            msg.status, msg.error = "failed", str(err.detail)[:300]
            send.status, send.reason, send.message_id = "failed", msg.error, msg.id
            continue
        await _sent(db, nl, lead, send, msg, sent["Message-ID"])
        done += 1
    return done


async def _run_postmark(db: AsyncSession, nl: Newsletter, tenant: Tenant) -> int:
    base = E.workspace_url(tenant.slug)
    from_name, from_email = await _from(db, nl, tenant)
    batch: list[tuple[NewsletterSend, Lead, Message, PM.Outgoing]] = []
    for send in await _queued(db, nl, PM.BATCH):
        lead = await db.get(Lead, send.lead_id) if send.lead_id else None
        if why := await _still_ok(db, lead, send.email):
            send.status, send.reason = "skipped", why
            continue
        token = secrets.token_urlsafe(24)
        subject, body, built, unsubscribe = _build(
            nl, await E.values_for(db, lead, tenant.name), token, base, None
        )
        header_id = S.new_message_id(from_email)
        msg = _message(nl, lead, send, subject, body, built, token, from_email, header_id, None)
        db.add(msg)
        out = PM.Outgoing(
            to=send.email, subject=subject, html=_with_preheader(built.html, nl.preheader),
            text=built.text, from_name=from_name, from_email=from_email,
            unsubscribe_url=unsubscribe, message_id=header_id,
        )  # fmt: skip
        batch.append((send, lead, msg, out))
    if not batch:
        return 0
    await db.flush()
    try:
        results = await PM.send_batch([b[3] for b in batch])
    except Invalid:  # Postmark down or refused the batch: everything stays queued
        for _, _, msg, _ in batch:
            await db.delete(msg)
        raise
    done = 0
    for (send, lead, msg, _), res in zip(batch, results, strict=False):
        if res.ok:
            await _sent(db, nl, lead, send, msg, res.provider_id)
            done += 1
        else:
            msg.status, msg.error = "failed", (res.error or "Postmark refused it")[:300]
            send.status, send.reason, send.message_id = "failed", msg.error, msg.id
    return done


async def run_tenant(tenant_id: uuid.UUID) -> int:
    """Worker: scheduled newsletters whose time has come start; sending ones send a batch."""
    async with tenant_session(tenant_id) as db:
        due = (
            await db.scalars(
                select(Newsletter)
                .where(
                    (Newsletter.status == "sending")
                    | ((Newsletter.status == "scheduled") & (Newsletter.send_at <= now()))
                )
                .order_by(Newsletter.send_at)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not due:
            return 0
        tenant = await db.get(Tenant, tenant_id)
        settings = await db.get(TenantSettings, tenant_id)
        done = 0
        for nl in due:
            if nl.status == "scheduled":
                nl.status, nl.started_at = "sending", now()
            try:
                if nl.path == "postmark":
                    done += await _run_postmark(db, nl, tenant)
                else:
                    done += await _run_mailboxes(db, nl, tenant, settings.timezone)
            except Invalid:
                continue  # tried again on the next run
            await db.flush()
            left = await db.scalar(
                select(func.count())
                .select_from(NewsletterSend)
                .where(NewsletterSend.newsletter_id == nl.id, NewsletterSend.status == "queued")
            )
            if not left:
                nl.status, nl.finished_at = "sent", now()
        return done


async def test_send(db: AsyncSession, actor: CurrentUser, nl: Newsletter) -> None:
    """A copy to the person writing it, with a sample lead's values. Not tracked, not counted."""
    tenant = await db.get(Tenant, actor.user.tenant_id)
    where = await audience_where(db, actor, nl.audience or {})
    lead = await db.scalar(select(Lead).where(*where, *_reachable()).limit(1))
    values = await E.values_for(db, lead, tenant.name) if lead else {"company.name": tenant.name}
    subject = "[Test] " + (R.fill(nl.subject, values).strip() or nl.name)
    body = R.fill(nl.body, values)
    built = R.build_email(body, track_base=None, token="test", unsubscribe_url=None)
    html = _with_preheader(built.html, nl.preheader)
    if nl.path == "postmark":
        from_name, from_email = await _from(db, nl, tenant)
        out = PM.Outgoing(to=actor.user.email, subject=subject, html=html, text=built.text,
                          from_name=from_name, from_email=from_email,
                          unsubscribe_url=f"{E.workspace_url(tenant.slug)}/api/v1/u/test",
                          message_id=S.new_message_id(from_email))  # fmt: skip
        [res] = await PM.send_batch([out])
        if not res.ok:
            raise Invalid(f"Postmark refused the test: {res.error}", code="postmark_failed")
        return
    box = None
    from_name, from_email = await _from(db, nl, tenant)
    if nl.mailbox_id:
        from app.modules.engage import mailsync as MS

        mb = await db.get(Mailbox, nl.mailbox_id)
        if mb is None:
            raise NotFound("The chosen inbox isn't connected any more")
        box, from_email = MS.box(mb), mb.email_address
    await S.send(
        db,
        to=actor.user.email,
        subject=subject,
        text=built.text,
        html=html,
        from_name=from_name,
        from_email=from_email,
        unsubscribe_url=None,
        box=box,
    )


async def report(db: AsyncSession, nl: Newsletter) -> dict:
    rows = await db.execute(
        select(NewsletterSend.status, func.count())
        .where(NewsletterSend.newsletter_id == nl.id)
        .group_by(NewsletterSend.status)
    )
    by_status = dict(rows.all())
    m = (
        await db.execute(
            select(
                func.count(Message.opened_at),
                func.count(Message.clicked_at),
                func.count(Message.unsubscribed_at),
                func.count(Message.bounced_at),
            )
            .select_from(NewsletterSend)
            .join(Message, Message.id == NewsletterSend.message_id)
            .where(NewsletterSend.newsletter_id == nl.id, NewsletterSend.status == "sent")
        )
    ).one()
    return {
        "recipients": sum(by_status.values()),
        "queued": by_status.get("queued", 0),
        "sent": by_status.get("sent", 0),
        "failed": by_status.get("failed", 0),
        "skipped": by_status.get("skipped", 0),
        "opened": m[0],
        "clicked": m[1],
        "unsubscribed": m[2],
        "bounced": m[3],
    }

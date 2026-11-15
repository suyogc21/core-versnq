"""The mailbox pool (step O1, Decision log #44): a company's sending inboxes.

Which inbox sends next: the lead owner's own pool inbox first, then the least used one today,
never over an inbox's daily limit, never inside its minimum gap, never a paused or broken one.
Sends are counted from the messages themselves (mailbox_id), so the numbers are always exact.
An inbox whose recent sends bounce too often is paused and admins are told.
"""

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm import leads as L
from app.modules.crm.models import Lead
from app.modules.crm.notify import notify
from app.modules.engage.models import Mailbox, Message
from app.modules.roles.models import Role
from app.modules.users.models import User

# Auto-pause: more than 5% of the last 50 sends bounced (and at least 20 sends to judge by).
BOUNCE_RATE = 0.05
BOUNCE_WINDOW = 50
BOUNCE_MIN_SENDS = 20
WINDOW_DAYS = 7


def start_of_day(tz: str) -> datetime:
    zone = ZoneInfo(tz)
    return datetime.combine(datetime.now(zone).date(), time.min, zone)


async def has_pool(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(Mailbox.id).where(Mailbox.in_pool).limit(1)))


async def sent_since(db: AsyncSession, since: datetime) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(Message.mailbox_id, func.count())
        .where(
            Message.mailbox_id.isnot(None),
            Message.direction == "out",
            Message.sent_at >= since,
        )
        .group_by(Message.mailbox_id)
    )
    return dict(rows.all())


async def pick(db: AsyncSession, lead: Lead, tz: str) -> Mailbox | None:
    """The inbox to send this lead's next email from, or None when every inbox is at its limit
    or inside its gap (the step then waits; nothing is skipped)."""
    return await choose(db, tz, owner_user_id=lead.owner_user_id)


def _ready(mb: Mailbox, today: dict[uuid.UUID, int], now: datetime) -> bool:
    if today.get(mb.id, 0) >= mb.daily_limit:
        return False
    return mb.last_sent_at is None or now - mb.last_sent_at >= timedelta(minutes=mb.min_gap_minutes)


async def choose(
    db: AsyncSession,
    tz: str,
    *,
    owner_user_id: uuid.UUID | None = None,
    only: list[uuid.UUID] | None = None,
) -> Mailbox | None:
    """Owner's inbox first, then the least used today; `only` limits the choice (a campaign's
    chosen inboxes, step O2)."""
    q = select(Mailbox).where(Mailbox.in_pool, Mailbox.status == "active")
    if only:
        q = q.where(Mailbox.id.in_(only))
    inboxes = (await db.scalars(q)).all()
    if not inboxes:
        return None
    today = await sent_since(db, start_of_day(tz))
    now = L.now()

    owners = [mb for mb in inboxes if owner_user_id and mb.user_id == owner_user_id]
    for mb in sorted(owners, key=lambda m: today.get(m.id, 0)):
        if _ready(mb, today, now):
            return mb
    rest = [mb for mb in inboxes if mb not in owners]
    rest.sort(
        key=lambda m: (
            today.get(m.id, 0),
            m.last_sent_at or datetime.min.replace(tzinfo=now.tzinfo),
        )
    )
    return next((mb for mb in rest if _ready(mb, today, now)), None)


async def ready_now(db: AsyncSession, mb: Mailbox, tz: str) -> bool:
    """This inbox may send now: active, in the pool, under its limit, outside its gap."""
    if mb.status != "active" or not mb.in_pool:
        return False
    return _ready(mb, await sent_since(db, start_of_day(tz)), L.now())


async def check_health(db: AsyncSession, mb: Mailbox) -> bool:
    """Pause the inbox when too many of its recent sends bounced. Returns True if paused now."""
    if mb.status != "active" or not mb.in_pool:
        return False
    recent = (
        (
            await db.execute(
                select(Message.bounced_at)
                .where(
                    Message.mailbox_id == mb.id,
                    Message.direction == "out",
                    Message.sent_at.isnot(None),
                )
                .order_by(Message.sent_at.desc())
                .limit(BOUNCE_WINDOW)
            )
        )
        .scalars()
        .all()
    )
    if len(recent) < BOUNCE_MIN_SENDS:
        return False
    bounced = sum(1 for b in recent if b is not None)
    if bounced / len(recent) <= BOUNCE_RATE:
        return False
    mb.status = "paused"
    mb.paused_reason = f"{bounced} of its last {len(recent)} emails bounced"
    admins = (
        await db.scalars(
            select(User.id)
            .join(Role, Role.id == User.role_id)
            .where(Role.key.in_(("owner", "admin")), User.status == "active")
        )
    ).all()
    await notify(
        db,
        mb.tenant_id,
        list(admins),
        "inbox",
        f"Sending inbox {mb.email_address} paused: {mb.paused_reason}. "
        "Check the list, then resume it.",
        None,
    )
    return True


async def health(db: AsyncSession, tz: str) -> list[dict]:
    """Per pool inbox: sent today, sent / replies / bounces in the last 7 days."""
    inboxes = (
        await db.scalars(select(Mailbox).where(Mailbox.in_pool).order_by(Mailbox.email_address))
    ).all()
    today = await sent_since(db, start_of_day(tz))
    since = L.now() - timedelta(days=WINDOW_DAYS)
    week = await sent_since(db, since)
    bounces = dict(
        (
            await db.execute(
                select(Message.mailbox_id, func.count())
                .where(Message.mailbox_id.isnot(None), Message.bounced_at >= since)
                .group_by(Message.mailbox_id)
            )
        ).all()
    )
    replies = dict(
        (
            await db.execute(
                select(Message.mailbox_id, func.count())
                .where(
                    Message.mailbox_id.isnot(None),
                    Message.direction == "in",
                    Message.created_at >= since,
                )
                .group_by(Message.mailbox_id)
            )
        ).all()
    )
    return [
        {
            "mailbox_id": mb.id,
            "email_address": mb.email_address,
            "status": mb.status,
            "paused_reason": mb.paused_reason,
            "sent_today": today.get(mb.id, 0),
            "daily_limit": mb.daily_limit,
            "sent_7d": week.get(mb.id, 0),
            "replies_7d": replies.get(mb.id, 0),
            "bounces_7d": bounces.get(mb.id, 0),
            "last_sync_at": mb.last_sync_at,
            "last_error": mb.last_error,
        }
        for mb in inboxes
    ]

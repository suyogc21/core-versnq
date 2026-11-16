"""Phone notifications (calls plan, step C2). Every in-app notification (new lead for you, a
missed call, a task due...) is also sent to the phones and browsers where the person turned
notifications on, by a worker job every 10 seconds. Only recent ones (10 minutes): nothing old
is ever sent. A phone that no longer accepts them (the browser said 404/410) is forgotten."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.crm.models import Notification
from app.modules.push.models import PushSubscription

log = logging.getLogger("versnq.push")
WINDOW = timedelta(minutes=10)


def configured() -> bool:
    s = get_settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


async def deliver(sub: PushSubscription, payload: dict) -> bool | None:
    """True sent, False failed for now, None the phone is gone (forget it)."""
    from pywebpush import WebPushException, webpush_async

    s = get_settings()
    try:
        await webpush_async(
            {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload),
            vapid_private_key=s.vapid_private_key,
            vapid_claims={"sub": s.vapid_subject},
            ttl=3600,
            timeout=10,
        )
        return True
    except WebPushException as e:
        status = getattr(e.response, "status", None) or getattr(e.response, "status_code", None)
        if status in (404, 410):
            return None
        log.warning("push failed (%s)", status)
        return False
    except Exception:  # noqa: BLE001 - a phone's push service being down never breaks the job
        log.warning("push failed", exc_info=True)
        return False


async def send_pending(db: AsyncSession) -> int:
    """Send this company's new notifications to phones. Returns how many pushes went out."""
    if not configured():
        return 0
    now = datetime.now(UTC)
    pending = (
        await db.scalars(
            select(Notification)
            .where(Notification.pushed_at.is_(None), Notification.created_at > now - WINDOW)
            .order_by(Notification.created_at)
            .limit(200)
        )
    ).all()
    if not pending:
        return 0
    users = {n.user_id for n in pending}
    subs: dict[uuid.UUID, list[PushSubscription]] = {}
    for sub in (
        await db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(users)))
    ).all():
        subs.setdefault(sub.user_id, []).append(sub)
    sent, gone = 0, set()
    for n in pending:
        n.pushed_at = now
        url = f"/leads/{n.lead_id}" if n.lead_id else "/"
        for sub in subs.get(n.user_id, []):
            if sub.id in gone:
                continue
            ok = await deliver(sub, {"title": n.title, "url": url, "tag": str(n.id)})
            if ok is None:
                gone.add(sub.id)
            elif ok:
                sub.last_sent_at, sent = now, sent + 1
    if gone:
        await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
    return sent

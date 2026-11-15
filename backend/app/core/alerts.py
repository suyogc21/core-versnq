"""Error alerts (go-live G-2): an unexpected error in the API (a 500) or a failed worker job is
emailed to Versnq staff (ALERT_EMAIL) from the system mailbox. At most one email per kind of
error per hour; every error is counted, and the nightly job sends the day's count.

Never in an alert: passwords, tokens, message bodies, or the values of a database statement.
Only the error's type, the first line of its message (cut, with any SQL parameters removed),
where it happened (the code's file:line, the route or the job) and which company's address."""

import asyncio
import hashlib
import logging
import re
import traceback
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.mailer import Email, get_mailer

log = logging.getLogger("versnq.alerts")
ONCE_PER = 3600  # seconds: one email per kind of error per hour
_SECRETS = re.compile(r"(\[parameters:.*|\[SQL:.*|password\S*\s*[=:]\s*\S+|token\S*\s*[=:]\s*\S+)",
                      re.IGNORECASE | re.DOTALL)  # fmt: skip
_pending: set[asyncio.Task] = set()


def summary(exc: BaseException) -> tuple[str, str, str]:
    """(kind key, one-line description, where in our code) — nothing secret."""
    first = (str(exc).splitlines() or [""])[0]
    first = _SECRETS.sub("[removed]", first)[:200]
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if "site-packages" not in f.filename] or frames  # our code
    where = (
        f"{ours[-1].filename.split('/app/')[-1]}:{ours[-1].lineno} in {ours[-1].name}"
        if ours
        else "?"
    )
    kind = hashlib.sha256(f"{type(exc).__name__}|{where}".encode()).hexdigest()[:16]
    return kind, f"{type(exc).__name__}: {first}", where


def _day(at: datetime | None = None) -> str:
    return (at or datetime.now(UTC)).strftime("%Y%m%d")


async def report(exc: BaseException, *, context: str, company: str | None = None) -> bool:
    """Count the error and email staff unless this kind was emailed in the last hour. Returns
    True when an email was sent. Never raises."""
    try:
        from app.core.ratelimit import get_redis

        kind, what, where = summary(exc)
        r = get_redis()
        day = f"alerts:day:{_day()}"
        await r.incr(day)
        await r.expire(day, 3 * 86400)
        to = get_settings().alert_email
        if not to or not await r.set(f"alerts:sent:{kind}", "1", ex=ONCE_PER, nx=True):
            return False
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        await get_mailer().send(
            Email(
                to=to,
                subject=f"[Core alert] {type(exc).__name__} in {context}"[:200],
                body=(
                    f"{now}\n\nWhat: {what}\nWhere in the code: {where}\nDuring: {context}\n"
                    f"Company address: {company or '—'}\nServer: {get_settings().environment}\n\n"
                    "More of the same kind in the next hour are counted but not emailed. "
                    "Details are in the server log (docker compose logs backend worker)."
                ),
            )
        )
        return True
    except Exception:  # noqa: BLE001 - an alert must never break anything
        log.exception("could not send an error alert")
        return False


async def day_count(days_ago: int = 1) -> int:
    from app.core.ratelimit import get_redis

    at = datetime.now(UTC) - timedelta(days=days_ago)
    return int(await get_redis().get(f"alerts:day:{_day(at)}") or 0)


async def send_daily_count() -> int:
    """Nightly: how many errors yesterday (UTC), when there were any."""
    n = await day_count(1)
    to = get_settings().alert_email
    if n and to:
        await get_mailer().send(
            Email(
                to=to,
                subject=f"[Core] {n} error{'s' if n != 1 else ''} yesterday",
                body=f"Yesterday (UTC) Core had {n} unexpected error(s). Each kind was emailed "
                "once an hour at most. Details are in the server log.",
            )
        )
    return n


class WorkerAlerts(logging.Handler):
    """Attached to the worker's 'arq.worker' logger: a failed job is reported."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if not record.exc_info or record.exc_info[1] is None:
            return
        exc = record.exc_info[1]
        context = "a background job"
        if record.args and isinstance(record.args, tuple) and len(record.args) > 1:
            context = f"the job {record.args[1]}"[:120]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(report(exc, context=context))
        _pending.add(task)
        task.add_done_callback(_pending.discard)


def install_worker_alerts() -> None:
    logger = logging.getLogger("arq.worker")
    if not any(isinstance(h, WorkerAlerts) for h in logger.handlers):
        logger.addHandler(WorkerAlerts())

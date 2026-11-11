"""Queue a background job from a request. Best effort: every job queued this way has a
scheduled fallback in the worker, so a missing queue only delays the work."""

from app.core.config import get_settings


async def enqueue(name: str, *args, defer_by: int = 2, job_id: str | None = None) -> None:
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        # Same job id while one is waiting = one job, however many requests asked for it.
        job_id = job_id or f"{name}:{':'.join(args)}"
        await pool.enqueue_job(name, *args, _job_id=job_id, _defer_by=defer_by)
        await pool.aclose()
    except Exception:  # noqa: BLE001 — the scheduled fallback runs it later
        pass

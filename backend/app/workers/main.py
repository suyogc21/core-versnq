from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import notify_due_tasks_job, ping_job


class WorkerSettings:
    """arq worker entry point: `arq app.workers.main.WorkerSettings`."""

    functions = [ping_job, notify_due_tasks_job]
    cron_jobs = [cron(notify_due_tasks_job, second=0)]  # once a minute
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import (
    import_job,
    import_sweep_job,
    notify_due_tasks_job,
    ping_job,
    routing_checks_job,
)


class WorkerSettings:
    """arq worker entry point: `arq app.workers.main.WorkerSettings`."""

    functions = [ping_job, notify_due_tasks_job, routing_checks_job, import_job, import_sweep_job]
    cron_jobs = [  # once a minute each, spread out
        cron(notify_due_tasks_job, second=0),
        cron(routing_checks_job, second=20),
        cron(import_sweep_job, second=40),
    ]
    job_timeout = 1800  # a 50,000-row import
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

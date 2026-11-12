from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import (
    automation_job,
    import_job,
    import_sweep_job,
    money_mail_job,
    money_mail_sweep_job,
    nightly_job,
    no_response_job,
    notify_due_tasks_job,
    ping_job,
    rescore_job,
    routing_checks_job,
    webhook_job,
    webhooks_job,
)


class WorkerSettings:
    """arq worker entry point: `arq app.workers.main.WorkerSettings`."""

    functions = [
        ping_job,
        notify_due_tasks_job,
        routing_checks_job,
        import_job,
        import_sweep_job,
        automation_job,
        no_response_job,
        rescore_job,
        nightly_job,
        webhook_job,
        webhooks_job,
        money_mail_job,
        money_mail_sweep_job,
    ]
    cron_jobs = [  # once a minute each, spread out
        cron(notify_due_tasks_job, second=0),
        cron(routing_checks_job, second=20),
        cron(import_sweep_job, second=40),
        cron(no_response_job, second=50),
        cron(money_mail_sweep_job, second=30),
        cron(automation_job, second=set(range(2, 60, 5)), unique=True),  # every 5 seconds
        cron(webhooks_job, second=set(range(7, 60, 10)), unique=True),  # every 10 seconds
        cron(nightly_job, hour=21, minute=30, second=10),  # 03:00 in India
    ]
    max_tries = 3
    job_timeout = 1800  # a 50,000-row import
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

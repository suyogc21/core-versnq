from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import (
    automation_job,
    call_recordings_job,
    campaigns_job,
    data_export_job,
    data_export_sweep_job,
    import_job,
    import_sweep_job,
    mailboxes_job,
    money_mail_job,
    money_mail_sweep_job,
    nightly_job,
    no_response_job,
    notify_due_tasks_job,
    ping_job,
    push_job,
    rescore_job,
    routing_checks_job,
    sequences_job,
    webhook_job,
    webhooks_job,
    whatsapp_health_job,
)


async def _startup(ctx) -> None:
    from app.core.alerts import install_worker_alerts

    install_worker_alerts()  # a failed job emails staff (go-live G-2)


class WorkerSettings:
    """arq worker entry point: `arq app.workers.main.WorkerSettings`."""

    on_startup = _startup

    functions = [
        ping_job,
        data_export_job,
        data_export_sweep_job,
        notify_due_tasks_job,
        routing_checks_job,
        import_job,
        import_sweep_job,
        automation_job,
        no_response_job,
        rescore_job,
        nightly_job,
        webhook_job,
        call_recordings_job,
        push_job,
        webhooks_job,
        sequences_job,
        campaigns_job,
        mailboxes_job,
        whatsapp_health_job,
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
        cron(call_recordings_job, second=35, unique=True),  # every minute (C3)
        cron(data_export_sweep_job, second=55, unique=True),  # batch 1
        cron(push_job, second=set(range(4, 60, 10)), unique=True),  # every 10 seconds (C2)
        cron(sequences_job, second={15, 45}, unique=True),  # every 30 seconds
        cron(campaigns_job, second={0, 30}, unique=True),  # every 30 seconds
        cron(mailboxes_job, second=25, unique=True),
        cron(nightly_job, hour=21, minute=30, second=10),  # 03:00 in India
        cron(whatsapp_health_job, hour=2, minute=0, second=40),  # 07:30 in India
    ]
    max_tries = 3
    job_timeout = 1800  # a 50,000-row import
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

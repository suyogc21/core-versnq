async def ping_job(ctx: dict) -> str:
    """Smoke-test job: proves the queue → worker → result path works."""
    return "pong"


async def notify_due_tasks_job(ctx) -> int:
    """Every minute: emit task.due for tasks that just fell due."""
    from app.modules.crm.work import notify_due_tasks

    return await notify_due_tasks()


async def routing_checks_job(ctx) -> dict:
    """Every minute: response-time (SLA) deadlines and the leakage guard."""
    from app.modules.crm.routing import run_checks

    return await run_checks()


async def import_job(ctx, tenant_id: str, import_id: str) -> dict:
    """Run one CSV import (queued by the API; the minute sweep picks up any that were missed)."""
    from app.modules.crm.imports import run_import

    return await run_import(tenant_id, import_id)


async def import_sweep_job(ctx) -> int:
    from app.modules.crm.imports import run_queued_imports

    return await run_queued_imports()


async def automation_job(ctx) -> int:
    """Every 5 seconds: run automations for new events."""
    from app.modules.crm.automation import process_all

    return await process_all()


async def no_response_job(ctx) -> int:
    """Every minute: 'no response within X hours' automations."""
    from app.modules.crm.automation import no_response_all

    return await no_response_all()


async def rescore_job(ctx, tenant_id: str) -> int:
    """After scoring rules change: re-score one company's leads."""
    import uuid

    from app.modules.crm.scoring import rescore_tenant

    return await rescore_tenant(uuid.UUID(tenant_id))


async def nightly_job(ctx) -> dict:
    """Once a night: engagement windows move, today() formulas move, owners get a task for
    documents still missing, files that lost their record are removed from disk, and money:
    repeat invoices, payment reminders, and payment links whose webhook was missed; API and
    webhook logs older than 30 days move to the archive files."""
    from app.core.tenancy import tenant_session
    from app.modules.crm import customers
    from app.modules.crm.automation import _active_tenants
    from app.modules.crm.calc import recalc_tenant
    from app.modules.crm.scoring import rescore_tenant
    from app.modules.integrations.logs import archive_tenant
    from app.modules.money.worker import nightly_tenant

    rescored = recalced = reminded = removed = logs_archived = 0
    missing: dict[str, list[str]] = {}
    money: dict[str, dict] = {}
    for t in await _active_tenants():
        rescored += await rescore_tenant(t)
        recalced += await recalc_tenant(t)
        async with tenant_session(t) as db:
            reminded += await customers.remind_pending(db)
        async with tenant_session(t) as db:
            report = await customers.clean_files(db, t)
        removed += report["removed"]
        if report["missing"]:
            missing[str(t)] = report["missing"]
        if done := await nightly_tenant(t):
            money[str(t)] = done
        archived = await archive_tenant(t)
        logs_archived += archived["api"] + archived["webhooks"]
    from app.core.alerts import send_daily_count

    return {
        "errors_yesterday": await send_daily_count(),  # emailed to staff when any (G-2)
        "logs_archived": logs_archived,
        "money": money,
        "rescored": rescored,
        "recalculated": recalced,
        "document_reminders": reminded,
        "files_removed": removed,
        "files_missing": missing,
    }


async def webhook_job(ctx, tenant_id: str, automation_id: str, url: str, secret: str, body: str):
    """Deliver one automation webhook; 3 tries, 1 then 5 minutes apart."""
    from arq import Retry

    from app.modules.crm.automation import deliver

    try:
        return await deliver(url, secret, body)
    except Exception as e:  # noqa: BLE001
        tries = ctx.get("job_try", 1)
        if tries < 3:
            raise Retry(defer=60 if tries == 1 else 300) from e
        return f"failed after {tries} tries: {type(e).__name__}"


async def money_mail_job(ctx, tenant_id: str, message_id: str) -> str:
    """Send one invoice / receipt / reminder email; 3 tries, then it is marked failed."""
    import uuid

    from arq import Retry

    from app.core.errors import Invalid
    from app.modules.money.worker import MAX_TRIES, send_one

    tries = ctx.get("job_try", 1)
    try:
        return await send_one(uuid.UUID(tenant_id), uuid.UUID(message_id), tries >= MAX_TRIES)
    except Invalid:
        raise Retry(defer=60 * tries) from None


async def webhooks_job(ctx) -> dict:
    """Every 10 seconds: new events become webhook deliveries; due deliveries are sent."""
    from app.modules.crm.automation import _active_tenants
    from app.modules.integrations.webhooks import run_all

    return await run_all(await _active_tenants())


async def sequences_job(ctx) -> int:
    """Every 30 seconds: run the sequence steps that are due (step 9a)."""
    from app.modules.crm.automation import _active_tenants
    from app.modules.engage.engine import run_all

    return await run_all(await _active_tenants())


async def campaigns_job(ctx) -> int:
    """Every 30 seconds: send the campaign emails that are due (step O2), for companies with
    Outreach switched on."""
    from app.core.modules import is_enabled
    from app.core.tenancy import tenant_session
    from app.modules.crm.automation import _active_tenants
    from app.modules.outreach.engine import run_due

    total = 0
    for tenant_id in await _active_tenants():
        async with tenant_session(tenant_id) as db:
            on = await is_enabled(db, tenant_id, "outreach")
        if on:
            total += await run_due(tenant_id)
    return total


async def mailboxes_job(ctx) -> int:
    """Every minute: read connected inboxes not read for a couple of minutes (step 9b-3)."""
    from app.modules.crm.automation import _active_tenants
    from app.modules.engage.mailsync import run_all

    return await run_all(await _active_tenants())


async def whatsapp_health_job(ctx) -> int:
    """Daily: the official WhatsApp numbers' quality and limit (step 10b)."""
    from app.modules.crm.automation import _active_tenants
    from app.modules.engage.whatsapp import health_all

    return await health_all(await _active_tenants())


async def money_mail_sweep_job(ctx) -> int:
    from app.modules.crm.automation import _active_tenants
    from app.modules.money.worker import sweep

    return await sweep(await _active_tenants())

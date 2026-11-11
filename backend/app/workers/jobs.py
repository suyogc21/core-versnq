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
    """Once a night: engagement windows move, today() formulas move."""
    from app.modules.crm.automation import _active_tenants
    from app.modules.crm.calc import recalc_tenant
    from app.modules.crm.scoring import rescore_tenant

    rescored = recalced = 0
    for t in await _active_tenants():
        rescored += await rescore_tenant(t)
        recalced += await recalc_tenant(t)
    return {"rescored": rescored, "recalculated": recalced}


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

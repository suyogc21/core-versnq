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

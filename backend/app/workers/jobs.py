async def ping_job(ctx: dict) -> str:
    """Smoke-test job: proves the queue → worker → result path works."""
    return "pong"


async def notify_due_tasks_job(ctx) -> int:
    """Every minute: emit task.due for tasks that just fell due."""
    from app.modules.crm.work import notify_due_tasks

    return await notify_due_tasks()

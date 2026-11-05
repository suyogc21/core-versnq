async def ping_job(ctx: dict) -> str:
    """Smoke-test job: proves the queue → worker → result path works."""
    return "pong"

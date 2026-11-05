from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.jobs import ping_job


class WorkerSettings:
    """arq worker entry point: `arq app.workers.main.WorkerSettings`."""

    functions = [ping_job]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

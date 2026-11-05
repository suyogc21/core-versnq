from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import Worker

from app.workers.main import WorkerSettings

TEST_REDIS_DB = 15  # keep test jobs away from the dev queue on db 0


async def test_ping_job_runs_through_queue(settings):
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    redis_settings.database = TEST_REDIS_DB
    pool = await create_pool(redis_settings)
    await pool.flushdb()

    job = await pool.enqueue_job("ping_job")
    worker = Worker(functions=WorkerSettings.functions, redis_pool=pool, burst=True)
    await worker.main()

    assert await job.result(timeout=5) == "pong"

    # The test owns the pool, so close it directly (arq's Worker.close uses a
    # deprecated redis call).
    await pool.aclose()


def test_worker_settings_use_configured_redis(settings):
    assert WorkerSettings.redis_settings.port == RedisSettings.from_dsn(settings.redis_url).port

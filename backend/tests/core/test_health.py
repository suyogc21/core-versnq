import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.health import get_db_check, get_redis_url
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def test_app_uses_test_database_during_tests():
    s = get_settings()
    assert s.database_url == s.test_database_url


async def test_health_ok(client):
    r = await client.get("/health")

    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_health_db_down(client):
    async def failing_db_check() -> None:
        raise ConnectionError("db unreachable")

    app.dependency_overrides[get_db_check] = lambda: failing_db_check

    r = await client.get("/health")

    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "down", "redis": "ok"}


async def test_health_redis_down_answers_fast(client):
    app.dependency_overrides[get_redis_url] = lambda: "redis://localhost:6399/0"

    started = time.monotonic()
    r = await client.get("/health")
    elapsed = time.monotonic() - started

    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "ok", "redis": "down"}
    assert elapsed < 3

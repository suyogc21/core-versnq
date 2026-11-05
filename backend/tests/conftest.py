import os

import pytest
from alembic import command

from app.core.config import Settings, get_settings
from tests.support import alembic_config, assert_test_database

# Point the whole app at the test database before any app module creates an engine.
_settings = Settings()
assert_test_database(_settings.test_database_url)
assert_test_database(_settings.test_migration_database_url)
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = _settings.test_database_url
os.environ["MIGRATION_DATABASE_URL"] = _settings.test_migration_database_url
# Tests use their own Redis database so rate-limit counters never touch dev data.
TEST_REDIS_URL = _settings.redis_url.rsplit("/", 1)[0] + "/14"
os.environ["REDIS_URL"] = TEST_REDIS_URL
get_settings.cache_clear()

# Imported only now: these modules create the app's database engine, which must see the
# test settings above. Moving this import to the top would point tests at the dev database.
from tests.http_fixtures import client_for, mailer  # noqa: E402,F401  (shared fixtures)


@pytest.fixture(scope="session", autouse=True)
def app_engine_is_on_test_database():
    """Hard stop if the app's real engine points anywhere but a *_test database."""
    from app.core.db import engine

    if not (engine.url.database or "").endswith("_test"):
        pytest.exit(f"App engine points at '{engine.url.database}', not a _test database", 2)


@pytest.fixture(scope="session", autouse=True)
def fresh_schema(app_engine_is_on_test_database):
    """Rebuild the test schema from migrations once per test run."""
    cfg = alembic_config(_settings.test_migration_database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_rate_limits():
    """Every test starts with empty rate-limit counters."""
    import redis

    client = redis.Redis.from_url(TEST_REDIS_URL)
    client.flushdb()
    client.close()


@pytest.fixture
def settings() -> Settings:
    return get_settings()

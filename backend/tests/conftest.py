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
get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def fresh_schema():
    """Rebuild the test schema from migrations once per test run."""
    cfg = alembic_config(_settings.test_migration_database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
def settings() -> Settings:
    return get_settings()

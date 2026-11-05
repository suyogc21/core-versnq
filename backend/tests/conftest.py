import os

import pytest

from app.core.config import Settings, get_settings
from tests.support import assert_test_database

# Point the whole app at the test database before any app module creates an engine.
_settings = Settings()
assert_test_database(_settings.test_database_url)
assert_test_database(_settings.test_migration_database_url)
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = _settings.test_database_url
os.environ["MIGRATION_DATABASE_URL"] = _settings.test_migration_database_url
get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()

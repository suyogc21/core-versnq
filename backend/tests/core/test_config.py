import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.support import assert_test_database

ENV = {
    "ENVIRONMENT": "test",
    "DATABASE_URL": "postgresql+asyncpg://u:p@h:5433/versnq",
    "MIGRATION_DATABASE_URL": "postgresql+asyncpg://o:p@h:5433/versnq",
    "TEST_DATABASE_URL": "postgresql+asyncpg://u:p@h:5433/versnq_test",
    "TEST_MIGRATION_DATABASE_URL": "postgresql+asyncpg://o:p@h:5433/versnq_test",
    "REDIS_URL": "redis://h:6380/0",
}


def test_settings_read_from_env(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    s = Settings(_env_file=None)

    assert s.environment == "test"
    assert s.database_url == ENV["DATABASE_URL"]
    assert s.test_database_url == ENV["TEST_DATABASE_URL"]
    assert s.redis_url == ENV["REDIS_URL"]


def test_missing_database_url_names_the_variable(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DATABASE_URL")

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert "database_url" in str(exc.value)


def test_harness_refuses_non_test_database():
    with pytest.raises(RuntimeError, match="_test"):
        assert_test_database("postgresql+asyncpg://u:p@h:5433/versnq")


def test_harness_accepts_test_database():
    assert_test_database("postgresql+asyncpg://u:p@h:5433/versnq_test")

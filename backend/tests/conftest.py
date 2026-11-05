import pytest

from app.core.config import Settings, get_settings
from tests.support import assert_test_database


def pytest_sessionstart(session):
    assert_test_database(get_settings().test_database_url)


@pytest.fixture
def settings() -> Settings:
    return get_settings()

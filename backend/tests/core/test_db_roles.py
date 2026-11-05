"""The runtime role must never be able to bypass row-level security."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def app_conn(settings):
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


async def test_app_role_cannot_bypass_rls(app_conn):
    bypass = await app_conn.scalar(
        text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
    )
    assert bypass is False


async def test_app_role_is_not_superuser(app_conn):
    assert await app_conn.scalar(text("SELECT usesuper FROM pg_user WHERE usename = current_user")) is False


async def test_app_role_owns_no_tables(app_conn):
    owned = await app_conn.scalar(
        text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user")
    )
    assert owned == 0


async def test_migrations_and_app_use_different_roles(settings):
    from sqlalchemy.engine import make_url

    assert make_url(settings.database_url).username != make_url(settings.migration_database_url).username

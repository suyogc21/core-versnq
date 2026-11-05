"""Tenant context: set per transaction, survives commits, never leaks to the next user."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenancy import platform_session, tenant_session

CURRENT = text("SELECT app_current_tenant()")


@pytest.fixture
async def one_connection_sessionmaker(settings):
    """A pool with exactly one connection, so every session reuses it."""
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_tenant_session_sets_context():
    tenant_a = uuid.uuid4()

    async with tenant_session(tenant_a) as session:
        assert await session.scalar(CURRENT) == tenant_a


async def test_context_survives_commit_inside_session():
    tenant_a = uuid.uuid4()

    async with tenant_session(tenant_a) as session:
        await session.commit()
        assert await session.scalar(CURRENT) == tenant_a


async def test_platform_session_has_no_tenant():
    async with platform_session() as session:
        assert await session.scalar(CURRENT) is None


async def test_context_does_not_leak_to_next_session_on_same_connection(
    one_connection_sessionmaker,
):
    tenant_a = uuid.uuid4()

    async with tenant_session(tenant_a, sessionmaker=one_connection_sessionmaker) as session:
        assert await session.scalar(CURRENT) == tenant_a

    async with platform_session(sessionmaker=one_connection_sessionmaker) as session:
        assert await session.scalar(CURRENT) is None

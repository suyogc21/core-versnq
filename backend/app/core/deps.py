"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import platform_session


async def get_platform_db() -> AsyncIterator[AsyncSession]:
    """Session with no tenant context, for /platform routes."""
    async with platform_session() as session:
        yield session

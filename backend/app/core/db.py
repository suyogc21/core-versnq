from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


_s = get_settings()
engine: AsyncEngine = create_async_engine(
    _s.database_url,
    pool_pre_ping=True,
    pool_size=_s.db_pool_size,
    max_overflow=_s.db_max_overflow,
    pool_timeout=10,  # a request waits at most 10s for a free connection, then errors
    pool_recycle=1800,  # replace connections every 30 minutes
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with SessionLocal() as session:
        yield session

"""Tenant context for database sessions.

Every transaction opened by a tenant session first runs
`set_config('app.tenant_id', <id>, true)`. The setting is transaction-local, so it
disappears when the transaction ends and can never leak to the next request that
reuses the pooled connection. Re-applying it on every transaction begin means a
commit in the middle of a request keeps the same tenant.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.db import SessionLocal

_TENANT_KEY = "tenant_id"
_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    tenant_id = session.info.get(_TENANT_KEY)
    if tenant_id is not None:
        connection.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})


@asynccontextmanager
async def _session(
    tenant_id: UUID | None, sessionmaker: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        if tenant_id is not None:
            session.info[_TENANT_KEY] = tenant_id
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


def tenant_session(
    tenant_id: UUID, *, sessionmaker: async_sessionmaker[AsyncSession] = SessionLocal
):
    """Session locked to one tenant. Commits on success, rolls back on error."""
    return _session(tenant_id, sessionmaker)


def platform_session(*, sessionmaker: async_sessionmaker[AsyncSession] = SessionLocal):
    """Session with no tenant: tenant tables return zero rows."""
    return _session(None, sessionmaker)


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Switch an open platform transaction to one tenant (used only by tenant provisioning
    and staff support actions). Lasts until the transaction ends."""
    session.info[_TENANT_KEY] = tenant_id
    await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})

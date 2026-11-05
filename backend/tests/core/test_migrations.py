import asyncio

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.support import alembic_config


def _current_revision(url: str) -> str | None:
    async def read() -> str | None:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            rev = None
            if await conn.scalar(text("SELECT to_regclass('alembic_version')")):
                rev = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        await engine.dispose()
        return rev

    return asyncio.run(read())


def test_upgrade_downgrade_upgrade(settings):
    url = settings.migration_database_url
    cfg = alembic_config(url)
    head = ScriptDirectory.from_config(cfg).get_current_head()

    command.upgrade(cfg, "head")
    assert _current_revision(url) == head

    command.downgrade(cfg, "base")
    assert _current_revision(url) is None

    command.upgrade(cfg, "head")
    assert _current_revision(url) == head

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND = Path(__file__).resolve().parents[2]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


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
    cfg = _alembic_config(settings.test_database_url)

    command.upgrade(cfg, "head")
    assert _current_revision(settings.test_database_url) == "0001"

    command.downgrade(cfg, "base")
    assert _current_revision(settings.test_database_url) is None

    command.upgrade(cfg, "head")
    assert _current_revision(settings.test_database_url) == "0001"

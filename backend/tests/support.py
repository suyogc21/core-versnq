from pathlib import Path

from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]


def assert_test_database(url: str) -> None:
    """Refuse to touch any database whose name does not end in `_test`."""
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        raise RuntimeError(f"Tests must run on a database ending in '_test', got '{name}'")


def alembic_config(url: str) -> Config:
    """Alembic config pointed at an explicit database URL."""
    assert_test_database(url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["skip_logging"] = True
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg

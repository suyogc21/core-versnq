from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or ../.env)."""

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    environment: Literal["dev", "test", "prod"]
    database_url: str  # runtime role (versnq_app): cannot bypass RLS
    migration_database_url: str  # owner role (versnq_owner): migrations only
    test_database_url: str
    test_migration_database_url: str
    redis_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()

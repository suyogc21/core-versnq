from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    jwt_secret: str = Field(min_length=32)
    totp_encryption_key: str  # Fernet key: encrypts 2FA secrets at rest
    base_domain: str  # client workspaces live at <slug>.<base_domain>
    # Read the workspace from X-Forwarded-Host. Only when a trusted proxy (Next dev server,
    # nginx) always overwrites that header; otherwise clients could spoof it.
    trust_proxy_headers: bool = False
    # Dev/e2e only: save outgoing emails as files here instead of logging them. Ignored in prod.
    mail_outbox_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

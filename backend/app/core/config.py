from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or ../.env)."""

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    environment: Literal["dev", "test", "prod"]
    database_url: str  # runtime role (versnq_app): cannot bypass RLS
    migration_database_url: str  # owner role (versnq_owner): migrations only
    # Connections each app or worker process keeps open (pool) and may add at peaks (overflow).
    # Keep processes x (pool + overflow) under Postgres max_connections (default 100).
    db_pool_size: int = 10
    db_max_overflow: int = 10
    test_database_url: str
    test_migration_database_url: str
    redis_url: str
    jwt_secret: str = Field(min_length=32)
    totp_encryption_key: str  # Fernet key: encrypts 2FA secrets at rest
    # Fernet key for company secrets (gateway keys, mailbox passwords). Required in production.
    secrets_encryption_key: str | None = None
    base_domain: str  # client workspaces live at <slug>.<base_domain>
    # Read the workspace from X-Forwarded-Host. Only when a trusted proxy (Next dev server,
    # nginx) always overwrites that header; otherwise clients could spoof it.
    trust_proxy_headers: bool = False
    # Dev/e2e only: save outgoing emails as files here instead of logging them. Ignored in prod.
    mail_outbox_dir: str | None = None
    # Core's own emails (invites, password resets) go out through this mailbox (SMTP). Empty:
    # they are only written to the log. On the server: the same no-reply mailbox AMS uses.
    system_smtp_host: str | None = None
    system_smtp_port: int = 587
    system_smtp_security: Literal["ssl", "starttls"] = "starttls"
    system_smtp_username: str | None = None
    system_smtp_password: str | None = None
    system_email_from: str | None = None
    system_email_from_name: str = "Versnq"
    alert_email: str | None = None  # go-live G-2: unexpected errors are emailed here
    # C13: ACE's console address (one for every company); empty: no "Open ACE" anywhere
    ace_console_url: str | None = None
    # Phone notifications (web push, calls plan C2): the VAPID key pair; empty = push is off
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:support@versnq.in"
    # Calling with the company's own Twilio (C3): "test" never reaches Twilio (dev, tests)
    twilio_mode: Literal["test", "live"] = "test"
    # SMS (batch 5d): "test" never reaches MSG91 or Twilio (dev, tests); live on the server
    sms_mode: Literal["test", "live"] = "test"
    # Lead ads (batch 5d): "test" never calls Meta's Graph API; META_LEADS_APP_SECRET is
    # Versnq's own Meta app secret, used to check Meta's webhook signature when a company
    # hasn't entered its own app's secret.
    lead_ads_mode: Literal["test", "live"] = "test"
    meta_leads_app_secret: str | None = None
    # Outside production: connected inboxes (step 9b-3) are read from <dir>/<address>/<folder>/
    # <uid>.eml instead of a real IMAP server, so mailbox sync can be tried without one.
    mailbox_test_dir: str | None = None
    # Copy-in addresses (step 9b-2) are <company>-<token>@INBOUND_EMAIL_DOMAIN. They start
    # working when inbound mail for that domain reaches Core (Amazon SES, at go-live).
    inbound_email_domain: str = "copy.versnq.in"
    inbound_email_live: bool = False
    # Official WhatsApp number (step 10b): test (kept in Core, nothing sent to Meta) or meta
    # (Meta's Cloud API with the company's own keys).
    whatsapp_sender: Literal["test", "meta"] = "test"
    meta_graph_version: str = "v21.0"
    # sequence emails (step 9a): "test" keeps them in Core; "mailbox" sends through the
    # company's own mailbox; Amazon SES is added at go-live (Decision log #39)
    email_sender: Literal["test", "mailbox"] = "test"
    # Uploaded files (documents, later invoice PDFs) live here on our own server's disk
    # (Decision log #29). Back this folder up nightly with the database.
    files_dir: str = "var/files"
    # Dev demos only: invented demo accounts (emails ending in .demo or @demo.versnq.in) skip
    # the 2FA setup step. Real people always need 2FA. Refused in production.
    demo_skip_2fa: bool = False
    # The shared server only: lets `python -m app.platform.demo --server` add the invented demo
    # companies (Brightlane, Acme, Bluewave) next to real ones. 2FA stays on; no demo staff.
    allow_demo_data: bool = False

    @model_validator(mode="after")
    def _no_demo_switches_in_prod(self) -> "Settings":
        if self.environment == "prod" and self.demo_skip_2fa:
            raise ValueError("DEMO_SKIP_2FA must never be on in production")
        if self.environment == "prod" and not self.secrets_encryption_key:
            raise ValueError("SECRETS_ENCRYPTION_KEY is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def skips_2fa_for_demo(email: str) -> bool:
    """True only for invented demo accounts while DEMO_SKIP_2FA is on (never in production)."""
    settings = get_settings()
    if not settings.demo_skip_2fa or settings.environment == "prod":
        return False
    email = email.lower()
    return email.endswith(".demo") or email.endswith("@demo.versnq.in")

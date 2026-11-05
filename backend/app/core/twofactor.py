"""TOTP two-factor authentication. Secrets are encrypted at rest with TOTP_ENCRYPTION_KEY."""

import re

import pyotp
from cryptography.fernet import Fernet

from app.core.config import get_settings

ISSUER = "Versnq Core"
_CODE = re.compile(r"^\d{6}$")


def _fernet() -> Fernet:
    return Fernet(get_settings().totp_encryption_key.encode())


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(stored: str) -> str:
    return _fernet().decrypt(stored.encode()).decode()


def verify_code(secret: str, code: str) -> bool:
    """Accepts the current code and one step either side (clock drift)."""
    return bool(_CODE.match(code)) and pyotp.TOTP(secret).verify(code, valid_window=1)


def provisioning_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=ISSUER)

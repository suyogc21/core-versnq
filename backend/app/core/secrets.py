"""Encrypting company secrets at rest (gateway keys, mailbox passwords).

Uses SECRETS_ENCRYPTION_KEY (a Fernet key). Outside production it falls back to the 2FA key so
a developer's machine keeps working; production refuses to start without its own key.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    return Fernet((s.secrets_encryption_key or s.totp_encryption_key).encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(stored: str) -> str:
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except InvalidToken:
        raise ValueError("A stored secret could not be read; enter it again") from None


def hint(value: str) -> str:
    """What the screen may show of a secret: its last 4 characters."""
    return f"••••{value[-4:]}" if len(value) > 4 else "••••"

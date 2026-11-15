"""One-time backup codes for the authenticator app (go-live G-4). Ten per person, shown once,
stored as a keyed hash, each works once. Format: xxxx-xxxx (letters and digits, no look-alikes)."""

import hashlib
import hmac
import re
import secrets

from app.core.config import get_settings

COUNT = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i
_SHAPE = re.compile(r"^[a-z0-9]{4}-?[a-z0-9]{4}$")


def new_codes() -> list[str]:
    return [
        "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(2))
        for _ in range(COUNT)
    ]


def normalize(code: str) -> str:
    return re.sub(r"[\s-]", "", code.strip().lower())


def looks_like(code: str) -> bool:
    """A backup code, not the app's 6-digit code."""
    return bool(_SHAPE.match(code.strip().lower()))


def code_hash(code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"recovery|{normalize(code)}".encode(), hashlib.sha256).hexdigest()

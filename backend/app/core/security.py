"""Password hashing, access tokens and refresh tokens."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 30
_ALGORITHM = "HS256"
_hasher = PasswordHasher()

# "*_mfa" tokens only prove the password step; they open nothing but /2fa/verify.
TokenType = Literal["staff", "user", "staff_mfa", "user_mfa"]
MFA_CHALLENGE_MINUTES = 5


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    sub: uuid.UUID
    typ: TokenType
    tenant_id: uuid.UUID | None


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        return False


# Used when an account does not exist, so a failed login takes the same time either way.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def create_access_token(
    sub: uuid.UUID,
    typ: TokenType,
    tenant_id: uuid.UUID | None,
    *,
    now: datetime | None = None,
    minutes: int = ACCESS_TOKEN_MINUTES,
) -> str:
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(sub),
        "typ": typ,
        "tid": str(tenant_id) if tenant_id else None,
        "iat": issued,
        "exp": issued + timedelta(minutes=minutes),
    }
    return jwt.encode(claims, get_settings().jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, expected_typ: TokenType) -> TokenClaims:
    try:
        data = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "typ", "exp", "iat"]},
        )
        if data["typ"] != expected_typ:
            raise InvalidToken("wrong token type")
        tid = data.get("tid")
        return TokenClaims(
            sub=uuid.UUID(data["sub"]), typ=data["typ"], tenant_id=uuid.UUID(tid) if tid else None
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidToken(str(exc)) from exc


def hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Return (plain token for the cookie, sha256 hash for the database)."""
    plain = secrets.token_urlsafe(48)
    return plain, hash_token(plain)

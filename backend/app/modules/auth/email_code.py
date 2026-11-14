"""Email sign-in codes (Decision log #45). After the password, a person without an authenticator
app is emailed a 6-digit code, unless this browser passed a code in the last 30 days. Codes live
in Redis only (keyed by the sign-in challenge, stored as an HMAC); the remembered browser is a
signed cookie that a password change voids."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.core.mailer import Email, Mailer
from app.core.ratelimit import get_redis
from app.modules.users.models import User

CODE_MINUTES = 10
TRUST_DAYS = 30
DEVICE_COOKIE = "user_device"
_TYP = "user_device"


def _mac(*parts: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, "|".join(parts).encode(), hashlib.sha256).hexdigest()


def _key(challenge: str) -> str:
    return f"otp:{hashlib.sha256(challenge.encode()).hexdigest()}"


def can_receive(email: str) -> bool:
    """Invented demo addresses (*.demo, a reserved name) can't receive mail, so they get no code;
    they hold invented data only and still need the password."""
    return not email.lower().endswith(".demo")


async def send(challenge: str, user: User, company: str, mailer: Mailer) -> None:
    code = f"{secrets.randbelow(10**6):06d}"
    await get_redis().set(_key(challenge), _mac(challenge, code), ex=CODE_MINUTES * 60)
    await mailer.send(
        Email(
            to=user.email,
            # The code stays out of the subject: mailers log subjects.
            subject=f"Your {company} sign-in code",
            body=f"Hi {user.name},\n\nYour sign-in code is {code}. It works for "
            f"{CODE_MINUTES} minutes.\n\nIf you did not just sign in, change your password: "
            "someone may know it.\n",
        )
    )


async def check(challenge: str, code: str) -> bool:
    """True once per code: a correct code is used up."""
    stored = await get_redis().get(_key(challenge))
    if stored is None or not hmac.compare_digest(stored.decode(), _mac(challenge, code)):
        return False
    await get_redis().delete(_key(challenge))
    return True


def _password_mark(user: User) -> str:
    return _mac("pw", user.password_hash or "")[:16]


def device_token(user: User) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "tid": str(user.tenant_id),
        "typ": _TYP,
        "pw": _password_mark(user),
        "iat": now,
        "exp": now + timedelta(days=TRUST_DAYS),
    }
    return jwt.encode(claims, get_settings().jwt_secret, algorithm="HS256")


def trusted(token: str | None, user: User) -> bool:
    if not token:
        return False
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return (
        data.get("typ") == _TYP
        and data.get("sub") == str(user.id)
        and data.get("tid") == str(user.tenant_id)
        and hmac.compare_digest(str(data.get("pw", "")), _password_mark(user))
    )

"""API keys (milestone 4, Decision log #37).

A key is shown once, stored as a SHA-256 hash, and acts as its integration user: a user with
status 'integration' that cannot sign in and is never listed as a team member. The user's role
decides what the key may do, through the same endpoints and visibility rules people use.
Each key may make 100 requests a minute.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.core.ratelimit import hit
from app.modules.integrations.models import ApiKey
from app.modules.roles.models import Role
from app.modules.users.models import User

PREFIX = "vq_live_"
RATE_LIMIT = 100  # requests a minute per key
WINDOW = 60


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def is_api_key(token: str) -> bool:
    return token.startswith(PREFIX)


async def create(
    db: AsyncSession, tenant_id: uuid.UUID, name: str, role_id: uuid.UUID, by: uuid.UUID
) -> tuple[ApiKey, str]:
    role = await db.get(Role, role_id)
    if role is None:
        raise Invalid("Choose a role")
    if role.key == "owner":
        raise Invalid("A key cannot have the Owner role. Use Admin or a narrower role.")
    name = " ".join(name.split())
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email=f"key-{uuid.uuid4().hex[:16]}@integration.invalid",
        name=f"API · {name}"[:200],
        status="integration",
        role_id=role.id,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()  # the key points at this user
    secret = PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        prefix=secret[:14],
        key_hash=hash_key(secret),
        user_id=user.id,
        created_by_user_id=by,
    )
    db.add(key)
    await db.flush()
    return key, secret


async def authenticate(db: AsyncSession, token: str) -> tuple[ApiKey, User] | None:
    """The key and its user, or None when unknown or revoked. Raises 429 over the limit."""
    key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(token)))
    if key is None or key.revoked_at is not None:
        return None
    user = await db.get(User, key.user_id)
    if user is None or user.status != "integration":
        return None
    if not await hit(
        f"rl:api:{key.id}:{int(datetime.now(UTC).timestamp()) // WINDOW}", RATE_LIMIT, WINDOW
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"This key may make {RATE_LIMIT} requests a minute. Try again shortly.",
            headers={"Retry-After": str(WINDOW - int(datetime.now(UTC).timestamp()) % WINDOW)},
        )
    now = datetime.now(UTC)
    if key.last_used_at is None or (now - key.last_used_at).total_seconds() > 60:
        key.last_used_at = now  # at most once a minute, so busy keys don't write every call
    return key, user

"""C13, Sign in with Core for ACE's console (docs/plans/ace-c13-c14-plan.md, approved Nov 16).

A person with ace.use asks for a one-time code (POST /ace/console-code) and is sent to ACE's
console with it; that is also where ACE sends someone who starts at ACE (Core's page /ace/open
asks them to sign in first). ACE swaps the code for who the person is (POST /ace/console-login)
with the same company's key, whose role holds ace.console_login. The code lives in Redis only,
for 2 minutes, and works once. The answer holds no Core token: ACE can't act as the person.
"""

import hashlib
import json
import secrets
import time
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.errors import Forbidden, Invalid, NotFound
from app.core.ratelimit import get_redis
from app.modules.audit.models import record
from app.modules.auth.deps import (
    ActiveUser,
    TenantDb,
    WorkspaceDep,
    effective_permissions,
    has_permission,
)
from app.modules.roles.models import Role
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/ace", tags=["ace"])
CODE_SECONDS = 120
KEEP_SECONDS = 600  # an expired or used code is still told apart from a wrong one for this long
CALLBACK = "/sign-in/core"  # on ACE's console


def _key(code: str) -> str:
    return "ace:console:" + hashlib.sha256(code.encode()).hexdigest()


class ConsoleCodeOut(BaseModel):
    url: str  # ACE's console, with the code and the company's address
    expires_in: int


class ConsoleLoginIn(BaseModel):
    code: str = Field(min_length=10, max_length=100)


class ConsoleRole(BaseModel):
    key: str
    name: str


class ConsolePerson(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: ConsoleRole
    permissions: list[str]


class ConsoleCompany(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


class ConsoleLoginOut(BaseModel):
    user: ConsolePerson
    company: ConsoleCompany


def available(actor) -> bool:
    """Whether this person sees Open ACE."""
    return bool(
        get_settings().ace_console_url
        and actor.user.status == "active"
        and has_permission(actor.permissions, "ace.use")
    )


@router.post("/console-code", response_model=ConsoleCodeOut)
async def console_code(actor: ActiveUser, ws: WorkspaceDep) -> ConsoleCodeOut:
    """A one-time code for Open ACE (people only, with ace.use)."""
    base = get_settings().ace_console_url
    if not base:
        raise NotFound("ACE's console isn't set up", code="ace_not_configured")
    if not available(actor):
        raise Forbidden("permission_denied")
    code = secrets.token_urlsafe(24)
    value = {"tenant_id": str(ws.id), "user_id": str(actor.user.id),
             "exp": time.time() + CODE_SECONDS}  # fmt: skip
    await get_redis().set(_key(code), json.dumps(value), ex=KEEP_SECONDS)
    query = urlencode({"code": code, "company": ws.slug})
    return ConsoleCodeOut(url=f"{base.rstrip('/')}{CALLBACK}?{query}", expires_in=CODE_SECONDS)


@router.post("/console-login", response_model=ConsoleLoginOut)
async def console_login(
    body: ConsoleLoginIn, request: Request, actor: ActiveUser, ws: WorkspaceDep, db: TenantDb
) -> ConsoleLoginOut:
    """ACE's key swaps a code for who the person is. Refusals: code_invalid, code_expired,
    code_used, user_inactive, not_allowed."""
    if actor.user.status != "integration" or not has_permission(
        actor.permissions, "ace.console_login"
    ):
        raise Forbidden("Only ACE's key may do this", code="not_allowed")
    r = get_redis()
    raw = await r.get(_key(body.code))
    if raw is None:
        raise Invalid("Unknown code", code="code_invalid")
    found = json.loads(raw)
    if found["tenant_id"] != str(ws.id):
        raise Forbidden("This code is for another company", code="not_allowed")
    if time.time() > found["exp"]:
        raise Invalid("The code expired; open ACE again", code="code_expired")
    if not await r.set(_key(body.code) + ":used", "1", ex=KEEP_SECONDS, nx=True):
        raise Invalid("The code was already used", code="code_used")
    person = await db.get(User, uuid.UUID(found["user_id"]))
    if person is None or person.status != "active":
        raise Invalid("That person's account is not active", code="user_inactive")
    role = await db.get(Role, person.role_id)
    perms = await effective_permissions(db, role)
    if "ace.use" not in perms:
        raise Forbidden("That person may no longer open ACE", code="not_allowed")
    await record(
        db, tenant_id=ws.id, actor_id=person.id, action="ace.console_login",
        entity_type="user", entity_id=person.id, after={"via_key_user_id": str(actor.user.id)},
        ip=client_ip(request), actor_type="user",
    )  # fmt: skip
    return ConsoleLoginOut(
        user=ConsolePerson(
            id=person.id,
            name=person.name,
            email=person.email,
            role=ConsoleRole(key=role.key, name=role.name),
            permissions=sorted(perms),
        ),  # fmt: skip
        company=ConsoleCompany(id=ws.id, slug=ws.slug, name=ws.name),
    )

"""Find the client workspace from the web address: <slug>.<BASE_DOMAIN>."""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.tenancy import platform_session
from app.platform.models import Tenant
from app.platform.tenants.slugs import InvalidSlug, validate_slug


@dataclass(frozen=True)
class Workspace:
    id: uuid.UUID
    slug: str
    name: str


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")


def slug_from_host(host: str) -> str | None:
    host = host.split(":")[0].lower().rstrip(".")
    suffix = "." + get_settings().base_domain.lower()
    if not host.endswith(suffix):
        return None
    slug = host[: -len(suffix)]
    if not slug or "." in slug:
        return None
    try:
        return validate_slug(slug)
    except InvalidSlug:
        return None


def request_host(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-host")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.headers.get("host", "")


async def get_workspace(request: Request) -> Workspace:
    slug = slug_from_host(request_host(request))
    if slug is None:
        raise _not_found()
    async with platform_session() as s:
        tenant = await s.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise _not_found()
    if tenant.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This workspace is suspended")
    return Workspace(id=tenant.id, slug=tenant.slug, name=tenant.name)

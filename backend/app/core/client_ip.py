"""The visitor's own address, for rate limits and audit rows.

Behind our proxy (nginx in production, the Next.js server in development) every request
comes from the proxy, so its address would make all visitors share one limit. When
TRUST_PROXY_HEADERS is on, the proxy's view is used: the LAST X-Forwarded-For entry, which
our proxy appends. Earlier entries are whatever the visitor sent and are never trusted.
"""

from fastapi import Request

from app.core.config import get_settings


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last[:64]
    return request.client.host if request.client else "unknown"

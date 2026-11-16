"""Every route needs a login unless it is on this explicit list."""

from fastapi.routing import APIRoute

from app.main import app
from app.modules.auth.deps import current_user_any
from app.platform.staff.router import current_staff_any

PUBLIC = {
    ("GET", "/health"),
    ("POST", "/platform/auth/login"),
    ("POST", "/platform/auth/2fa/verify"),
    ("POST", "/platform/auth/refresh"),
    ("POST", "/platform/auth/logout"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/2fa/verify"),
    ("POST", "/api/v1/auth/2fa/resend"),  # needs the challenge from a correct password (#45)
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/invite/accept"),
    ("POST", "/api/v1/auth/password/forgot"),
    ("POST", "/api/v1/auth/password/reset"),
    # Web forms post leads here; protected by the per-form secret key + rate limits (#22).
    ("POST", "/api/v1/capture/{key}"),
    ("OPTIONS", "/api/v1/capture/{key}"),
    # Hosted forms (Nov 16): the page's questions, and sending it; only hosted, switched-on
    # forms answer; protected by rate limits and the spam trap.
    ("GET", "/api/v1/forms/{public_id}"),
    # Calls with the company's own Twilio (C3): only requests with Twilio's signature (made
    # with the company's own auth token) are answered; anything else is a 404.
    ("POST", "/api/v1/twilio/voice"),
    ("POST", "/api/v1/twilio/connect"),
    ("POST", "/api/v1/twilio/dial-done"),
    ("POST", "/api/v1/twilio/hangup"),
    ("POST", "/api/v1/twilio/recording"),
    ("POST", "/api/v1/forms/{public_id}"),
    # Landing pages (batch 5a): a published page, and counting a visit to it (once per
    # address per page every 30 minutes, rate-limited); unpublished pages are a 404.
    ("GET", "/api/v1/pages/{slug}"),
    ("POST", "/api/v1/pages/{slug}/visit"),
    # Payment gateways tell Core a link was paid; only a valid signature is accepted (#34).
    ("POST", "/api/v1/webhooks/{gateway_name}/{account_id}"),
    # Inside every sequence email (#39): open pixel, tracked links (only to links that were in
    # that email), unsubscribe page and its button / one-click unsubscribe. Random tokens.
    ("GET", "/api/v1/t/o/{token}.gif"),
    ("GET", "/api/v1/t/c/{token}/{index}"),
    ("GET", "/api/v1/u/{token}"),
    ("POST", "/api/v1/u/{token}"),
    # The WhatsApp extension trades a one-time code (made in My account) for its token (#41).
    # Rate-limited per address and per company.
    ("POST", "/api/v1/extension/connect"),
    # Meta's WhatsApp webhook (#41): the GET answers Meta's one-time check with the company's
    # verify token; the POST is refused unless signed with the company's app secret.
    ("GET", "/api/v1/whatsapp/webhook"),
    ("POST", "/api/v1/whatsapp/webhook"),
    # Lead ads (batch 5d): Meta's one-time check needs one of the company's verify tokens;
    # Meta's lead notices need the app secret's signature; Google's leads need the
    # company's own webhook key. Anything else is refused.
    ("GET", "/api/v1/lead-ads/facebook/webhook"),
    ("POST", "/api/v1/lead-ads/facebook/webhook"),
    ("POST", "/api/v1/lead-ads/google/webhook"),
    # SMS (batch 5d): delivery reports and replies; the random token in the address is the
    # company's own, and Twilio's requests must also carry Twilio's signature.
    ("POST", "/api/v1/sms/{token}/status"),
    ("POST", "/api/v1/sms/{token}/inbound"),
}


def _calls(dependant) -> set:
    found = {dependant.call}
    for sub in dependant.dependencies:
        found |= _calls(sub)
    return found


def _api_routes(routes):
    """Flatten included routers (FastAPI >=0.16x wraps them in _IncludedRouter)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def _routes():
    for route in _api_routes(app.routes):
        for method in route.methods:
            yield method, route.path, _calls(route.dependant)


def test_walk_sees_every_route_in_the_api_spec():
    """Guards this test itself: if the walk misses routes, the checks below prove nothing."""
    walked = {(m, p) for m, p, _ in _routes()}
    spec = {
        (method.upper(), path) for path, ops in app.openapi()["paths"].items() for method in ops
    }
    assert walked == spec


def test_no_unlisted_public_route():
    unprotected = {
        (m, p)
        for m, p, calls in _routes()
        if current_user_any not in calls and current_staff_any not in calls
    }
    assert unprotected == PUBLIC


def test_staff_and_user_guards_never_mix():
    for method, path, calls in _routes():
        if path.startswith("/api/v1"):
            assert current_staff_any not in calls, (method, path)
        if path.startswith("/platform"):
            assert current_user_any not in calls, (method, path)

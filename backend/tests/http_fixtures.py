"""HTTP test fixtures shared by every test package (loaded from tests/conftest.py)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.mailer import Email, get_mailer
from app.main import app


class RecordingMailer:
    def __init__(self):
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)


@pytest.fixture
def mailer():
    m = RecordingMailer()
    app.dependency_overrides[get_mailer] = lambda: m
    yield m
    app.dependency_overrides.pop(get_mailer, None)


@pytest.fixture
def client_for(settings):
    """client_for(slug) -> AsyncClient talking to <slug>.<BASE_DOMAIN>."""
    clients = []

    def make(slug: str, host: str | None = None) -> AsyncClient:
        c = AsyncClient(
            transport=ASGITransport(app=app),
            base_url=f"http://{host or f'{slug}.{settings.base_domain}'}",
        )
        clients.append(c)
        return c

    yield make


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"user_refresh={token}"}


async def sign_in(c: AsyncClient, email: str, password: str):
    """Password sign-in that also enters the emailed code when one is asked for (Decision #45).
    Returns the final response (the password step's, when it fails or needs no code)."""
    previous = app.dependency_overrides.get(get_mailer)
    box = RecordingMailer()
    app.dependency_overrides[get_mailer] = lambda: box
    try:
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": password})
        if r.status_code != 200 or r.json().get("two_factor_method") != "email":
            return r
        code = box.sent[-1].body.split("code is ")[1][:6]
        return await c.post(
            "/api/v1/auth/2fa/verify",
            json={"challenge_token": r.json()["challenge_token"], "code": code},
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_mailer, None)
        else:
            app.dependency_overrides[get_mailer] = previous

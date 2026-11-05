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

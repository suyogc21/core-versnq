"""Go-live G-2: an unexpected error emails staff once an hour per kind, with nothing secret in
it; a failed worker job too; the nightly count; no address set → nothing is sent."""

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import alerts as A
from app.core import errors
from app.core.config import get_settings
from tests.http_fixtures import RecordingMailer


@pytest.fixture
def alert_to(monkeypatch):
    monkeypatch.setattr(get_settings(), "alert_email", "staff@versnq.example")


@pytest.fixture
def mailer(monkeypatch):
    box = RecordingMailer()
    monkeypatch.setattr(A, "get_mailer", lambda: box)
    return box


def _client(host: str) -> AsyncClient:
    """Like a browser: a server error comes back as a 500 instead of being raised in the test."""
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url=f"http://{host}"
    )


def _boom():
    raise ValueError(
        "insert failed [SQL: INSERT INTO users VALUES ($1)] [parameters: ('secret@x.com',)]"
    )


app = FastAPI()  # a small app with Core's error handling, so the real app's routes stay as they are
errors.install(app)


@app.get("/__test_boom")
async def _route():
    _boom()


async def test_a_500_emails_staff_once_an_hour_without_secrets(mailer, alert_to):
    c = _client("anything.core.example")
    first = await c.get("/__test_boom")
    second = await c.get("/__test_boom")

    assert first.status_code == 500 and first.json()["code"] == "server_error"
    assert "secret" not in first.text and "INSERT" not in first.text
    assert second.status_code == 500
    assert len(mailer.sent) == 1
    mail = mailer.sent[0]
    assert mail.to == "staff@versnq.example" and "ValueError" in mail.subject
    assert "GET /__test_boom" in mail.body and "anything.core.example" in mail.body
    assert "secret@x.com" not in mail.body and "[SQL" not in mail.body
    assert "test_alerts.py" in mail.body  # where in the code
    assert await A.day_count(0) == 2  # both counted


async def test_no_address_means_no_email(mailer, monkeypatch):
    monkeypatch.setattr(get_settings(), "alert_email", None)
    assert (await _client("x.core.example").get("/__test_boom")).status_code == 500
    assert mailer.sent == []


async def test_a_failed_worker_job_is_reported(mailer, alert_to):
    A.install_worker_alerts()
    logger = logging.getLogger("arq.worker")
    try:
        try:
            raise RuntimeError("mailbox server said no")
        except RuntimeError:
            logger.exception("%6.2fs ! %s failed, %s: %s", 0.1, "abc:sequences_job", "x", "y")
        for t in list(A._pending):
            await t
    finally:
        logger.handlers = [h for h in logger.handlers if not isinstance(h, A.WorkerAlerts)]
    assert len(mailer.sent) == 1 and "the job abc:sequences_job" in mailer.sent[0].subject


async def test_the_nightly_count(mailer, alert_to):
    from app.core.ratelimit import get_redis

    await get_redis().set(f"alerts:day:{A._day(A.datetime.now(A.UTC) - A.timedelta(days=1))}", 3)
    assert await A.send_daily_count() == 3
    assert mailer.sent[-1].subject == "[Core] 3 errors yesterday"

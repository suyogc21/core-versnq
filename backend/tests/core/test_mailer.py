import json

from app.core.config import get_settings
from app.core.mailer import ConsoleMailer, Email, FileMailer, get_mailer


def test_console_mailer_is_the_default(monkeypatch):
    monkeypatch.delenv("MAIL_OUTBOX_DIR", raising=False)
    get_settings.cache_clear()
    try:
        assert isinstance(get_mailer(), ConsoleMailer)
    finally:
        get_settings.cache_clear()


async def test_outbox_dir_saves_each_email_as_a_json_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_OUTBOX_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        mailer = get_mailer()
        assert isinstance(mailer, FileMailer)
        await mailer.send(Email(to="a@x.demo", subject="First", body="one"))
        await mailer.send(Email(to="b@x.demo", subject="Second", body="two"))
    finally:
        get_settings.cache_clear()
    files = sorted(tmp_path.glob("*.json"))
    assert [json.loads(f.read_text()) for f in files] == [
        {"to": "a@x.demo", "subject": "First", "body": "one"},
        {"to": "b@x.demo", "subject": "Second", "body": "two"},
    ]


def test_outbox_is_refused_in_production(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_OUTBOX_DIR", str(tmp_path))
    monkeypatch.setenv("ENVIRONMENT", "prod")
    get_settings.cache_clear()
    try:
        assert isinstance(get_mailer(), ConsoleMailer)
    finally:
        get_settings.cache_clear()

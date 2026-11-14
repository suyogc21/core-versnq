import json

from app.core import mailer as M
from app.core.config import get_settings
from app.core.mailer import ConsoleMailer, Email, FileMailer, get_mailer
from app.modules.money import mailbox as smtp


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
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "x" * 44)
    get_settings.cache_clear()
    try:
        assert isinstance(get_mailer(), ConsoleMailer)
    finally:
        get_settings.cache_clear()


async def test_system_mailbox_sends_and_a_failure_never_breaks_the_caller(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mail_outbox_dir", None)
    assert isinstance(M.get_mailer(), M.ConsoleMailer)  # nothing set: the log only
    monkeypatch.setattr(s, "system_smtp_host", "smtp.zoho.in")
    monkeypatch.setattr(s, "system_smtp_port", 465)
    monkeypatch.setattr(s, "system_smtp_security", "ssl")
    monkeypatch.setattr(s, "system_smtp_username", "no-reply@versnq.in")
    monkeypatch.setattr(s, "system_smtp_password", "secret")
    monkeypatch.setattr(s, "system_email_from", "no-reply@versnq.in")
    sent = []
    monkeypatch.setattr(smtp, "_send_now", lambda box, msg: sent.append((box, msg)))
    mailer = M.get_mailer()
    assert isinstance(mailer, M.SmtpMailer)
    await mailer.send(M.Email("asha@client.example", "You're invited", "Open https://x/invite"))
    box, msg = sent[0]
    assert (box.host, box.port, box.security) == ("smtp.zoho.in", 465, "ssl")
    assert msg["To"] == "asha@client.example" and "no-reply@versnq.in" in msg["From"]
    assert "invite" in msg.get_content()

    def refuse(box, msg):
        raise OSError("connection refused")

    monkeypatch.setattr(smtp, "_send_now", refuse)
    await mailer.send(M.Email("asha@client.example", "Reset", "x"))  # logged, not raised

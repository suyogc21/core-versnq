"""Where sequence emails go (step 9a, Decision log #39).

EMAIL_SENDER=test (default): nothing leaves the server; the email is kept (and written as an
.eml file when MAIL_OUTBOX_DIR is set), so everything else can be built and tested now.
EMAIL_SENDER=mailbox: the company's own mailbox (the one invoices use, step 6). Amazon SES from
each company's own domain plugs in here at go-live.
"""

import uuid
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Invalid
from app.modules.money import mailbox
from app.modules.money.messages import box as box_of
from app.modules.money.models import MailAccount


async def sender_address(db: AsyncSession, company_name: str) -> tuple[str, str]:
    """(from name, from email) shown on emails."""
    account = await db.scalar(select(MailAccount).where(MailAccount.is_active.is_(True)))
    if account:
        return account.from_name, account.from_email
    return company_name, "no-reply@example.invalid"


async def send(
    db: AsyncSession,
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    from_name: str,
    from_email: str,
    unsubscribe_url: str,
    reply_to: str | None = None,
) -> str:
    """Sends one email. Returns the provider's message id. Raises Invalid on failure."""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1] or None)
    if reply_to:
        msg["Reply-To"] = reply_to
    # one-click unsubscribe (Gmail / Yahoo bulk-sender rules, RFC 8058)
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    mode = get_settings().email_sender
    if mode == "test":
        folder = mailbox._outbox()
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"seq-{uuid.uuid4().hex}.eml").write_bytes(msg.as_bytes())
        return f"test-{uuid.uuid4().hex}"
    account = await db.scalar(select(MailAccount).where(MailAccount.is_active.is_(True)))
    if account is None:
        raise Invalid("Connect the company mailbox in Settings → Money first")
    await mailbox.send(box_of(account), msg)
    return msg["Message-ID"]

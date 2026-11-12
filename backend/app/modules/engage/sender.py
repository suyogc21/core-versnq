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


def new_message_id(from_email: str) -> str:
    return make_msgid(domain=from_email.split("@")[-1] or None)


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
    unsubscribe_url: str | None,
    reply_to: str | None = None,
    message_id: str | None = None,
    cc: list[str] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    box: mailbox.Box | None = None,
) -> EmailMessage:
    """Sends one email and returns it (its Message-ID is the provider's id). Raises Invalid on
    failure. Sequence emails carry a one-click unsubscribe; one-to-one replies (step 9b) don't,
    but carry the thread headers so the answer lands in the same conversation. With `box` (the
    user's own connected mailbox, step 9b-3) it goes out through that mailbox."""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Message-ID"] = message_id or new_message_id(from_email)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " if references else "") + in_reply_to
    if reply_to:
        msg["Reply-To"] = reply_to
    if unsubscribe_url:  # one-click unsubscribe (Gmail / Yahoo bulk-sender rules, RFC 8058)
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if box is not None:  # saved to MAIL_OUTBOX_DIR instead outside production, when set
        await mailbox.send(box, msg)
        return msg
    mode = get_settings().email_sender
    if mode == "test":
        folder = mailbox._outbox()
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"seq-{uuid.uuid4().hex}.eml").write_bytes(msg.as_bytes())
        return msg
    account = await db.scalar(select(MailAccount).where(MailAccount.is_active.is_(True)))
    if account is None:
        raise Invalid("Connect the company mailbox in Settings → Money first")
    await mailbox.send(box_of(account), msg)
    return msg

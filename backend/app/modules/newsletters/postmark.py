"""Postmark's broadcast message stream, for newsletters (batch 5b; Postmark chosen Nov 16).

POSTMARK_MODE=test (default): nothing leaves the server; every email is kept here (tests read
it) and gets a made-up id. POSTMARK_MODE=live: Postmark's "send a batch of emails" endpoint with
the server's API token.

From Postmark's public API documentation, NOT yet checked against a live account (Suyog buys it
later):
- POST https://api.postmarkapp.com/email/batch, header X-Postmark-Server-Token, JSON array of up
  to 500 messages: From, To, Subject, HtmlBody, TextBody, MessageStream, Headers [{Name, Value}],
  TrackOpens, TrackLinks.
- The answer is one object per message, in order: {ErrorCode: 0 on success, Message, MessageID}.
- Broadcast streams need the From address (or its domain) verified in Postmark.
- Postmark can add its own unsubscribe link to broadcast streams. We send our own (the same link
  as every Core email, so the suppression list stays in Core), so in Postmark the stream's
  unsubscribe handling should be set to "none"/self-managed. Check this when the account exists.
- We track opens and clicks ourselves, so TrackOpens/TrackLinks are false.
"""

import uuid
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.errors import Invalid

URL = "https://api.postmarkapp.com/email/batch"
BATCH = 500


@dataclass
class Outgoing:
    to: str
    subject: str
    html: str
    text: str
    from_name: str
    from_email: str
    unsubscribe_url: str
    message_id: str  # our Message-ID header


@dataclass
class Result:
    ok: bool
    provider_id: str | None
    error: str | None


SENT: list[dict] = []  # test mode: what would have been sent (tests read this)


def configured() -> bool:
    s = get_settings()
    return s.postmark_mode == "test" or bool(s.postmark_server_token)


def _payload(m: Outgoing, stream: str) -> dict:
    return {
        "From": f'"{m.from_name.replace(chr(34), "")}" <{m.from_email}>',
        "To": m.to,
        "Subject": m.subject,
        "HtmlBody": m.html,
        "TextBody": m.text,
        "MessageStream": stream,
        "TrackOpens": False,
        "TrackLinks": "None",
        "Headers": [
            {"Name": "Message-ID", "Value": m.message_id},
            {"Name": "List-Unsubscribe", "Value": f"<{m.unsubscribe_url}>"},
            {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"},
        ],
    }


async def send_batch(messages: list[Outgoing]) -> list[Result]:
    """Sends up to 500 emails; one result per email, in order. Raises Invalid when Postmark
    can't be reached or refuses the whole batch (the emails stay queued and are tried again)."""
    s = get_settings()
    stream = s.postmark_broadcast_stream
    payload = [_payload(m, stream) for m in messages[:BATCH]]
    if s.postmark_mode == "test":
        SENT.extend(payload)
        return [Result(True, f"pm-test-{uuid.uuid4()}", None) for _ in payload]
    if not s.postmark_server_token:
        raise Invalid("Postmark isn't set up on this server", code="postmark_missing")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
            r = await http.post(
                URL,
                json=payload,
                headers={
                    "X-Postmark-Server-Token": s.postmark_server_token,
                    "Accept": "application/json",
                },
            )
    except httpx.HTTPError as e:
        raise Invalid(
            f"Could not reach Postmark ({type(e).__name__})", code="postmark_failed"
        ) from None
    if r.status_code != 200:
        detail = r.json().get("Message") if r.content else r.status_code
        raise Invalid(f"Postmark said: {detail}", code="postmark_failed")
    out = []
    for item in r.json():
        ok = item.get("ErrorCode") == 0
        out.append(
            Result(ok, item.get("MessageID") if ok else None, None if ok else item.get("Message"))
        )
    return out

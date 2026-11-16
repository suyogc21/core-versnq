"""Calling with the company's own Twilio account (calls plan, step C3).

Click-to-call: Twilio rings the rep's own phone first; when the rep answers, it connects the
lead (so no browser microphone is needed). Incoming: a call to one of the company's Twilio
numbers rings the lead's owner, then the company's main number; unanswered, the caller can leave
a voicemail and the owner gets a call-back task. Every call ends in the one call pipeline
(service.report), with the recording fetched by the worker. Every request from Twilio is checked
with its signature (the company's own auth token). TWILIO_MODE=test never reaches Twilio.
"""

import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode, urlparse
from xml.sax.saxutils import escape, quoteattr

import httpx
from fastapi import Request

from app.core import secrets as SEC
from app.core.config import get_settings
from app.core.errors import Invalid
from app.core.ratelimit import get_redis
from app.modules.calls.models import CallingAccount

API = "https://api.twilio.com/2010-04-01"
CTX_SECONDS = 6 * 3600  # a call's context lives this long in Redis


# ---------- talking to Twilio ----------
class TwilioClient:
    def __init__(self, acct: CallingAccount):
        self.sid = acct.account_sid
        self.auth = (acct.account_sid, SEC.decrypt(acct.auth_token_enc))

    async def _call(self, method: str, path: str, **kw) -> dict:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            try:
                r = await http.request(method, f"{API}/{path}", auth=self.auth, **kw)
            except httpx.HTTPError as e:
                raise Invalid(f"Could not reach Twilio ({type(e).__name__})",
                              code="twilio_failed") from None  # fmt: skip
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            raise Invalid(
                f"Twilio said: {data.get('message') or r.status_code}", code="twilio_failed"
            )
        return data

    async def verify(self) -> None:
        await self._call("GET", f"Accounts/{self.sid}.json")

    async def create_call(self, *, to: str, from_: str, url: str) -> str:
        form = {"To": to, "From": from_, "Url": url, "Method": "POST"}
        data = await self._call("POST", f"Accounts/{self.sid}/Calls.json", data=form)
        return data["sid"]

    async def recording(self, url: str) -> bytes | None:
        """Only Twilio's own recording links of this account are fetched (never any other URL)."""
        u = urlparse(url)
        if (
            u.scheme != "https"
            or u.hostname != "api.twilio.com"
            or f"/Accounts/{self.sid}/" not in u.path
        ):
            return None
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
            r = await http.get(url.removesuffix(".mp3") + ".mp3", auth=self.auth)
        return r.content if r.status_code == 200 else None


class TestTwilio:
    """TWILIO_MODE=test: nothing reaches Twilio."""

    def __init__(self, acct: CallingAccount):
        self.acct = acct

    async def verify(self) -> None:
        if SEC.decrypt(self.acct.auth_token_enc) == "wrong-token":
            raise Invalid("Twilio said: Authenticate", code="twilio_failed")

    async def create_call(self, *, to: str, from_: str, url: str) -> str:
        return "CA" + secrets.token_hex(16)

    async def recording(self, url: str) -> bytes | None:
        return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 2000


def client(acct: CallingAccount):  # patched in tests
    return TestTwilio(acct) if get_settings().twilio_mode == "test" else TwilioClient(acct)


# ---------- requests from Twilio ----------
def external_url(request: Request) -> str:
    """The address Twilio called, exactly as Twilio signed it (behind our HTTPS proxy)."""
    proto = request.url.scheme
    if get_settings().trust_proxy_headers:
        proto = request.headers.get("x-forwarded-proto", proto)
    host = request.headers.get("host", request.url.netloc)
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{proto}://{host}{request.url.path}{query}"


def origin(request: Request) -> str:
    url = urlparse(external_url(request))
    return f"{url.scheme}://{url.netloc}"


def signature_ok(
    acct: CallingAccount, url: str, params: dict[str, str], header: str | None
) -> bool:
    """Twilio's signature: HMAC-SHA1 of the URL plus every POST field (sorted, name+value)."""
    if not header:
        return False
    payload = url + "".join(k + params[k] for k in sorted(params))
    key = SEC.decrypt(acct.auth_token_enc).encode()
    want = base64.b64encode(hmac.new(key, payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(want, header)


# ---------- a call's context (who, which lead) between Twilio's requests ----------
async def new_context(data: dict) -> str:
    token = secrets.token_urlsafe(18)
    await get_redis().set(f"twilio:ctx:{token}", json.dumps(data), ex=CTX_SECONDS)
    return token


async def context(token: str | None) -> dict | None:
    if not token:
        return None
    raw = await get_redis().get(f"twilio:ctx:{token}")
    return json.loads(raw) if raw else None


async def save_context(token: str, data: dict) -> None:
    await get_redis().set(f"twilio:ctx:{token}", json.dumps(data), ex=CTX_SECONDS)


# ---------- what Twilio does next (TwiML) ----------
def twiml(*parts: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>"


def link(base: str, path: str, **query: str) -> str:
    return f"{base}/api/v1/twilio/{path}?{urlencode(query)}"


def dial(
    base: str, token: str, number: str, caller_id: str, record: bool, timeout: int = 25
) -> str:
    rec = (
        f' record="record-from-answer" recordingStatusCallbackEvent="completed"'
        f" recordingStatusCallback={quoteattr(link(base, 'recording', ctx=token))}"
        if record
        else ""
    )
    return (
        f'<Dial callerId={quoteattr(caller_id)} timeout="{timeout}"'
        f" action={quoteattr(link(base, 'dial-done', ctx=token))}{rec}>"
        f"<Number>{escape(number)}</Number></Dial>"
    )


def voicemail(base: str, token: str) -> str:
    return (
        "<Say>Sorry, no one could take your call. Please leave a message after the tone.</Say>"
        f'<Record maxLength="120" playBeep="true" recordingStatusCallbackEvent="completed"'
        f" action={quoteattr(link(base, 'hangup', ctx=token))}"  # never back to the same step
        f" recordingStatusCallback={quoteattr(link(base, 'recording', ctx=token))}/>"
    )

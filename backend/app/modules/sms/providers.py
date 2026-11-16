"""SMS providers behind one switch (finishing plan, batch 5d).

- **MSG91** (India): every SMS to an Indian number must use a DLT-registered template (TRAI's
  rules), so MSG91 sends by its own template id with our variables in order (VAR1, VAR2…).
- **Twilio** (elsewhere): free text from the company's Twilio number.
- **TestSms**: nothing leaves Core (tests, development, and SMS_MODE=test).

Provider API details below are written from the providers' public docs as remembered, NOT
checked against a live account. Each is marked "UNVERIFIED" where it matters; check them with
the first real account before calling SMS done.
"""

import base64
import hashlib
import hmac
import secrets

import httpx

from app.core import secrets as SEC
from app.core.config import get_settings
from app.core.errors import Invalid
from app.modules.sms.models import SmsAccount

TWILIO_API = "https://api.twilio.com/2010-04-01"
# UNVERIFIED: MSG91's "Flow" send API (v5): POST JSON with header `authkey`, body
# {"template_id", "short_url": "0", "recipients": [{"mobiles": "91…", "VAR1": "…"}]};
# success answers {"type": "success", "message": "<request id>"}.
MSG91_FLOW = "https://control.msg91.com/api/v5/flow/"


class Sent:
    def __init__(self, provider_id: str | None, error: str | None = None):
        self.provider_id = provider_id
        self.error = error


class TwilioSms:
    def __init__(self, acct: SmsAccount):
        self.acct = acct
        self.auth = (acct.account_sid or "", SEC.decrypt(acct.auth_enc) if acct.auth_enc else "")

    async def verify(self) -> None:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            try:
                r = await http.get(
                    f"{TWILIO_API}/Accounts/{self.acct.account_sid}.json", auth=self.auth
                )
            except httpx.HTTPError as e:
                raise Invalid(
                    f"Could not reach Twilio ({type(e).__name__})", code="sms_failed"
                ) from None
        if r.status_code >= 400:
            raise Invalid("Twilio refused these details", code="sms_failed")

    async def send(
        self,
        *,
        to: str,
        body: str,
        variables: list[str],
        provider_template_id: str | None,
        status_url: str,
    ) -> Sent:
        form = {"To": to, "From": self.acct.sender, "Body": body, "StatusCallback": status_url}
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            try:
                r = await http.post(
                    f"{TWILIO_API}/Accounts/{self.acct.account_sid}/Messages.json",
                    data=form,
                    auth=self.auth,
                )
            except httpx.HTTPError as e:
                return Sent(None, f"Could not reach Twilio ({type(e).__name__})")
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            return Sent(None, f"Twilio said: {data.get('message') or r.status_code}"[:300])
        return Sent(data.get("sid"))


class Msg91Sms:
    def __init__(self, acct: SmsAccount):
        self.acct = acct
        self.key = SEC.decrypt(acct.auth_enc) if acct.auth_enc else ""

    async def verify(self) -> None:
        if len(self.key) < 10:
            raise Invalid("That doesn't look like an MSG91 auth key", code="sms_failed")
        # UNVERIFIED: no MSG91 "check this key" endpoint is used; the first send proves it.

    async def send(
        self,
        *,
        to: str,
        body: str,
        variables: list[str],
        provider_template_id: str | None,
        status_url: str,
    ) -> Sent:
        if not provider_template_id:
            return Sent(None, "MSG91 needs the template's MSG91 id (DLT rules in India)")
        recipient = {"mobiles": to.lstrip("+")}
        for i, value in enumerate(variables, start=1):
            recipient[f"VAR{i}"] = value  # UNVERIFIED: variable naming in MSG91 flows
        payload = {"template_id": provider_template_id, "short_url": "0", "recipients": [recipient]}
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            try:
                r = await http.post(MSG91_FLOW, json=payload, headers={"authkey": self.key})
            except httpx.HTTPError as e:
                return Sent(None, f"Could not reach MSG91 ({type(e).__name__})")
        data = r.json() if r.content else {}
        if r.status_code >= 400 or data.get("type") != "success":
            return Sent(None, f"MSG91 said: {data.get('message') or r.status_code}"[:300])
        return Sent(str(data.get("message") or "") or None)


class TestSms:
    """SMS_MODE=test or the "test" provider: nothing leaves Core."""

    def __init__(self, acct: SmsAccount):
        self.acct = acct

    async def verify(self) -> None:
        if self.acct.auth_enc and SEC.decrypt(self.acct.auth_enc) == "wrong-key":
            raise Invalid("The provider refused these details", code="sms_failed")

    async def send(
        self,
        *,
        to: str,
        body: str,
        variables: list[str],
        provider_template_id: str | None,
        status_url: str,
    ) -> Sent:
        if to.endswith("0000"):  # a number the fake treats as unreachable
            return Sent(None, "The provider couldn't deliver to this number")
        return Sent("TEST-" + secrets.token_hex(8))


def client(acct: SmsAccount):  # patched in tests
    if acct.provider == "test" or get_settings().sms_mode == "test":
        return TestSms(acct)
    return TwilioSms(acct) if acct.provider == "twilio" else Msg91Sms(acct)


def twilio_signature_ok(
    acct: SmsAccount, url: str, params: dict[str, str], header: str | None
) -> bool:
    """Twilio's signature: HMAC-SHA1 of the URL plus every POST field (sorted, name+value)."""
    if not header or not acct.auth_enc:
        return False
    payload = url + "".join(k + params[k] for k in sorted(params))
    key = SEC.decrypt(acct.auth_enc).encode()
    want = base64.b64encode(hmac.new(key, payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(want, header)

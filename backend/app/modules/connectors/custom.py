"""Custom CRM: works with any CRM. The company gives Core three addresses of its own (or of a
Zapier / Make flow); Core POSTs JSON signed like its webhooks:
`X-Versnq-Signature: sha256=HMAC(secret, "<X-Versnq-Timestamp>.<body>")`.

- lookup:   {"phone": "+91…"}                         → {"lead_id": "…" or null}
- create:   {"phone", "name", "email", "owner_email"} → {"lead_id": "…"}
- activity: {"lead_id", "type": "call" | "whatsapp" | "call_note", …} → any 2xx
            ({"activity_id": "…"} optional); a call_note has the call's summary, next step and a
            private recording link
"""

import json
import time

from app.modules.connectors import base as B
from app.modules.crm.automation import check_url, sign


class CustomCrm:
    def __init__(self, config: dict, secret: str):
        self.urls = {k: config.get(f"{k}_url") or "" for k in ("lookup", "create", "activity")}
        self.secret = secret

    async def _post(self, which: str, data: dict) -> dict:
        url = self.urls[which]
        if not url:
            raise B.CrmError(f"No {which} address set", retry=False)
        try:
            check_url(url)
        except Exception as e:  # noqa: BLE001 — Invalid: a private or plain-http address
            raise B.CrmError(str(getattr(e, "detail", e)), retry=False) from None
        body = json.dumps(data, default=str)
        ts = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Versnq-Core-CRM/1",
            "X-Versnq-Timestamp": str(ts),
            "X-Versnq-Signature": f"sha256={sign(self.secret, ts, body)}",
        }
        r = await B.send("POST", url, content=body, headers=headers)
        try:
            out = r.json() if r.content else {}
        except ValueError:
            raise B.CrmError("The CRM's answer wasn't JSON", retry=False) from None
        return out if isinstance(out, dict) else {}

    async def find_by_phone(self, phone: str) -> str | None:
        found = (await self._post("lookup", {"phone": phone})).get("lead_id")
        return str(found)[:100] if found else None

    async def create_lead(self, lead: B.NewLead) -> str:
        made = (await self._post("create", {
            "phone": lead.phone, "name": lead.name, "email": lead.email,
            "owner_email": lead.owner_email,
        })).get("lead_id")  # fmt: skip
        if not made:
            raise B.CrmError("The CRM didn't return the new lead's id", retry=False)
        return str(made)[:100]

    async def log_call(self, lead_id: str, call: B.CallInfo) -> str | None:
        out = await self._post("activity", {
            "lead_id": lead_id, "type": "call", "call_id": str(call.call_id),
            "direction": call.direction, "status": call.status, "number": call.number,
            "started_at": call.started_at.isoformat(), "duration_seconds": call.seconds,
            "rep_email": call.rep_email,
        })  # fmt: skip
        return str(out["activity_id"])[:100] if out.get("activity_id") else None

    async def log_message(self, lead_id: str, msg: B.MessageInfo) -> str | None:
        out = await self._post("activity", {
            "lead_id": lead_id, "type": "whatsapp", "message_id": str(msg.message_id),
            "direction": msg.direction, "text": msg.text, "at": msg.at.isoformat(),
            "rep_email": msg.rep_email,
        })  # fmt: skip
        return str(out["activity_id"])[:100] if out.get("activity_id") else None

    async def log_note(self, lead_id: str, note: B.CallNote) -> str | None:
        out = await self._post("activity", {
            "lead_id": lead_id, "type": "call_note", "call_id": str(note.call_id),
            "at": note.at.isoformat(), "summary": note.summary, "next_step": note.next_step,
            "recording_url": note.recording_url,
        })  # fmt: skip
        return str(out["activity_id"])[:100] if out.get("activity_id") else None

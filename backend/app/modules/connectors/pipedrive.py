"""Pipedrive, from developers.pipedrive.com and pipedrive.readme.io (read Nov 17). The admin
pastes the company's Pipedrive address ({company}.pipedrive.com) and an API token (Personal
preferences → API), sent in the `x-api-token` header.

- find:   GET /api/v2/persons/search?term=…&fields=phone (the number without its country code,
          so "+91 98765 43210" and "98765 43210" stored in Pipedrive both match)
- create: POST /api/v2/persons {name, phones: [{value, primary, label}], emails, owner_id}
- calls:  POST /api/v1/callLogs (outcome connected / no_answer / busy, to and from numbers,
          start and end time in UTC "YYYY-MM-DD HH:MM:SS", duration in seconds, person_id,
          user_id, subject); Pipedrive's own call-log API, so calls show as calls
- notes (call notes, WhatsApp): POST /api/v1/notes {content, person_id}
- users:  GET /api/v1/users/find?term=<email>&search_by_email=1

To confirm on a real account: the search result's shape (data.items[].item.id is read, with a
fallback), and whether a call log for another rep needs an admin's token (the docs say a user
without account-settings access can't log calls for others).
"""

import re
from datetime import UTC, timedelta

from app.modules.connectors import base as B
from app.modules.connectors.hubspot import national

WHEN = "%Y-%m-%d %H:%M:%S"
OUTCOME = {"answered": "connected", "busy": "busy"}  # everything else: no_answer
DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class Pipedrive:
    def __init__(self, domain: str, token: str, config: dict):
        if not DOMAIN.match(domain or ""):
            raise B.CrmError("Unknown Pipedrive company address", retry=False)
        self.base = f"https://{domain}.pipedrive.com/api"
        self.headers = {"x-api-token": token}
        self.config = dict(config)
        self._users: dict[str, int | None] = {}

    async def _call(self, method: str, path: str, **kw) -> dict:
        r = await B.send(method, f"{self.base}{path}", headers=self.headers, **kw)
        try:
            out = r.json() if r.content else {}
        except ValueError:
            raise B.CrmError("Pipedrive's answer wasn't JSON", retry=False) from None
        return out if isinstance(out, dict) else {}

    @staticmethod
    def _id(out: dict) -> str:
        made = (out.get("data") or {}).get("id") if isinstance(out.get("data"), dict) else None
        if not made:
            raise B.CrmError("Pipedrive didn't return an id", retry=False)
        return str(made)

    async def user_id(self, email: str | None) -> int | None:
        if not email:
            return None
        if email not in self._users:
            out = await self._call("GET", "/v1/users/find",
                                   params={"term": email, "search_by_email": 1})  # fmt: skip
            found = [
                u for u in out.get("data") or [] if str(u.get("email", "")).lower() == email.lower()
            ]
            self._users[email] = int(found[0]["id"]) if found else None
        return self._users[email]

    async def find_by_phone(self, phone: str) -> str | None:
        params = {"term": national(phone), "fields": "phone", "limit": 1}
        out = await self._call("GET", "/v2/persons/search", params=params)
        items = (out.get("data") or {}).get("items") or []
        if not items:
            return None
        first = items[0].get("item") or items[0]
        return str(first["id"]) if first.get("id") else None

    async def create_lead(self, lead: B.NewLead) -> str:
        phones = [{"value": lead.phone, "primary": True, "label": "mobile"}]
        body: dict = {"name": lead.name or lead.phone, "phones": phones}
        if lead.email:
            body["emails"] = [{"value": lead.email, "primary": True, "label": "work"}]
        owner = await self.user_id(lead.owner_email)
        if owner:
            body["owner_id"] = owner
        return self._id(await self._call("POST", "/v2/persons", json=body))

    async def log_call(self, lead_id: str, call: B.CallInfo) -> str | None:
        incoming = call.direction == "in"
        rep = call.rep_phone or ""
        end = call.started_at + timedelta(seconds=call.seconds)
        body = {
            "outcome": OUTCOME.get(call.status, "no_answer"),
            "from_phone_number": call.number if incoming else rep,
            "to_phone_number": (rep if incoming else call.number) or call.number,
            "start_time": call.started_at.astimezone(UTC).strftime(WHEN),
            "end_time": end.astimezone(UTC).strftime(WHEN),
            "duration": str(call.seconds),
            "person_id": int(lead_id),
            "subject": f"{'Incoming' if incoming else 'Outgoing'} call (Versnq)",
        }
        user = await self.user_id(call.rep_email)
        if user:
            body["user_id"] = user
        return self._id(
            await self._call("POST", "/v1/callLogs", json={k: v for k, v in body.items() if v})
        )

    async def _note(self, lead_id: str, html: str) -> str | None:
        body = {"content": html[:90000], "person_id": int(lead_id)}
        return self._id(await self._call("POST", "/v1/notes", json=body))

    async def log_message(self, lead_id: str, msg: B.MessageInfo) -> str | None:
        way = "from the person" if msg.direction == "in" else "to the person"
        return await self._note(lead_id, f"<b>WhatsApp {way}</b><br>{_html(msg.text)}")

    async def log_note(self, lead_id: str, note: B.CallNote) -> str | None:
        lines = "<br>".join(_html(x) for x in note.text().split("\n"))
        return await self._note(lead_id, f"<b>Call notes (Versnq)</b><br>{lines}")


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

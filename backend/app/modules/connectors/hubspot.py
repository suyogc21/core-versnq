"""HubSpot, from developers.hubspot.com (read Nov 17). The customer's admin makes a Service Key
(Development → Keys → Service keys; legacy private-app tokens still work where they exist) and
pastes it into Core; it is sent as `Authorization: Bearer …`.

- find:  POST /crm/objects/2026-09/contacts/search on phone / mobilephone; HubSpot compares the
         area code + local number only, so the number goes without its country code
- create: POST /crm/v3/objects/contacts {properties: firstname, lastname, phone, email,
         hubspot_owner_id}
- calls: POST /crm/v3/objects/calls (hs_timestamp, hs_call_direction INBOUND / OUTBOUND,
         hs_call_duration in ms, hs_call_status, from / to numbers, owner), linked to the contact
         with association type 194 (call → contact)
- notes (call notes, WhatsApp messages): POST /crm/v3/objects/notes (hs_timestamp,
         hs_note_body), association type 202 (note → contact)
- owners: GET /crm/v3/owners, matched by email (HubSpot has no email filter)

Not confirmed in the docs: the exact scope names for calls and notes; the setup screen asks the
admin to tick Contacts (read, write), Owners (read), Calls and Notes.
"""

from datetime import UTC, datetime

import phonenumbers

from app.modules.connectors import base as B

API = "https://api.hubapi.com"
STATUS = {"answered": "COMPLETED", "missed": "NO_ANSWER", "no_answer": "NO_ANSWER",
          "busy": "BUSY", "failed": "FAILED"}  # fmt: skip


def _ms(at: datetime) -> int:
    return int(at.astimezone(UTC).timestamp() * 1000)


def national(phone: str) -> str:
    """+919876543210 → 9876543210 (what HubSpot's phone search compares)."""
    try:
        return str(phonenumbers.parse(phone).national_number)
    except phonenumbers.NumberParseException:
        return phone.lstrip("+")


class HubSpot:
    def __init__(self, token: str, config: dict):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.config = dict(config)
        self._owners: dict[str, str] | None = None

    async def _call(self, method: str, path: str, **kw) -> dict:
        r = await B.send(method, f"{API}{path}", headers=self.headers, **kw)
        try:
            out = r.json() if r.content else {}
        except ValueError:
            raise B.CrmError("HubSpot's answer wasn't JSON", retry=False) from None
        return out if isinstance(out, dict) else {}

    async def owner_id(self, email: str | None) -> str | None:
        if not email:
            return None
        if self._owners is None:
            self._owners, after = {}, None
            for _ in range(20):  # 100 per page; plenty for one company
                params = {"limit": 100, **({"after": after} if after else {})}
                page = await self._call("GET", "/crm/v3/owners", params=params)
                for o in page.get("results") or []:
                    if o.get("email") and o.get("id"):
                        self._owners[o["email"].lower()] = str(o["id"])
                after = ((page.get("paging") or {}).get("next") or {}).get("after")
                if not after:
                    break
        return self._owners.get(email.lower())

    async def find_by_phone(self, phone: str) -> str | None:
        number = national(phone)
        body = {
            "filterGroups": [
                {"filters": [{"propertyName": p, "operator": "EQ", "value": number}]}
                for p in ("phone", "mobilephone")
            ],
            "properties": ["firstname", "lastname"],
            "limit": 1,
        }
        out = await self._call("POST", "/crm/objects/2026-09/contacts/search", json=body)
        found = out.get("results") or []
        return str(found[0]["id"]) if found and found[0].get("id") else None

    async def create_lead(self, lead: B.NewLead) -> str:
        first, _, last = (lead.name or "").partition(" ")
        owner = await self.owner_id(lead.owner_email)
        props = {"firstname": first or lead.phone, "lastname": last, "phone": lead.phone,
                 "email": lead.email, "hubspot_owner_id": owner}  # fmt: skip
        body = {"properties": {k: v for k, v in props.items() if v}}
        out = await self._call("POST", "/crm/v3/objects/contacts", json=body)
        if not out.get("id"):
            raise B.CrmError("HubSpot didn't return the new contact's id", retry=False)
        return str(out["id"])

    @staticmethod
    def _link(contact_id: str, type_id: int) -> list:
        return [{"to": {"id": contact_id},
                 "types": [{"associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": type_id}]}]  # fmt: skip

    async def log_call(self, lead_id: str, call: B.CallInfo) -> str | None:
        incoming = call.direction == "in"
        rep = call.rep_phone or ""
        props = {
            "hs_timestamp": _ms(call.started_at),
            "hs_call_title": "Incoming call" if incoming else "Outgoing call",
            "hs_call_body": "Logged by Versnq Core",
            "hs_call_direction": "INBOUND" if incoming else "OUTBOUND",
            "hs_call_duration": call.seconds * 1000,
            "hs_call_status": STATUS.get(call.status, "COMPLETED"),
            "hs_call_from_number": call.number if incoming else rep,
            "hs_call_to_number": rep if incoming else call.number,
            "hubspot_owner_id": await self.owner_id(call.rep_email),
        }
        out = await self._call("POST", "/crm/v3/objects/calls", json={
            "properties": {k: v for k, v in props.items() if v not in (None, "")},
            "associations": self._link(lead_id, 194),
        })  # fmt: skip
        return str(out["id"]) if out.get("id") else None

    async def _note(self, contact_id: str, at: datetime, text: str, owner: str | None):
        props = {"hs_timestamp": _ms(at), "hs_note_body": text[:65000]}
        if owner:
            props["hubspot_owner_id"] = owner
        out = await self._call("POST", "/crm/v3/objects/notes",
                               json={"properties": props,
                                     "associations": self._link(contact_id, 202)})  # fmt: skip
        return str(out["id"]) if out.get("id") else None

    async def log_message(self, lead_id: str, msg: B.MessageInfo) -> str | None:
        way = "from the contact" if msg.direction == "in" else "to the contact"
        return await self._note(lead_id, msg.at, f"WhatsApp {way}: {msg.text}",
                                await self.owner_id(msg.rep_email))  # fmt: skip

    async def log_note(self, lead_id: str, note: B.CallNote) -> str | None:
        return await self._note(lead_id, note.at, f"Call notes (Versnq)\n{note.text()}", None)

"""Zoho CRM (API v7), from zoho.com/crm/developer/docs (read Nov 17).

Connecting: the admin makes a Self Client in Zoho's API console (api-console.zoho.com), generates
a one-time code with the scopes below, and pastes the client id, client secret and code into
Core with their Zoho region. Core swaps the code for a refresh token (POST
{accounts}/oauth/v2/token, grant_type=authorization_code) and keeps it encrypted; access tokens
(1 hour) come from the refresh token (grant_type=refresh_token, in the query string) and are
reused until they expire (Zoho allows 10 new ones per 10 minutes).
Scopes: ZohoCRM.modules.leads.ALL, ZohoCRM.modules.contacts.ALL, ZohoCRM.modules.calls.CREATE,
ZohoCRM.modules.notes.CREATE, ZohoCRM.users.READ, ZohoSearch.securesearch.READ.

- find:   GET /crm/v7/{Leads|Contacts}/search?phone=… (204: nothing)
- create: POST /crm/v7/Leads {"data": [{Last_Name (required), First_Name, Phone, Email, Owner}]}
- calls:  POST /crm/v7/Calls (Subject, Call_Type Inbound / Outbound / Missed, Call_Start_Time
          ISO with offset, Call_Duration "HH:mm" as documented); a Contact via Who_Id, a Lead via
          What_Id + $se_module "Leads"
- notes:  POST /crm/v7/Notes {"data": [{Parent_Id: {module: {api_name}, id}, Note_Content}]}
- users:  GET /crm/v7/users?type=ActiveUsers, matched by email

To confirm on a real Zoho account: linking a call to a Lead (the docs only show Contacts), and
the call length format (documented as "HH:mm"; the exact seconds also go in the description).
"""

import time
from datetime import UTC

from app.modules.connectors import base as B

REGIONS = {
    "accounts.zoho.in": "India",
    "accounts.zoho.com": "United States",
    "accounts.zoho.eu": "Europe",
    "accounts.zoho.com.au": "Australia",
    "accounts.zoho.jp": "Japan",
    "accounts.zohocloud.ca": "Canada",
    "accounts.zoho.sa": "Saudi Arabia",
    "accounts.zoho.com.cn": "China",
}
# Access tokens kept between sends in this worker: {connection key: (token, api_domain, until)}
_TOKENS: dict[str, tuple[str, str, float]] = {}


async def exchange_code(accounts: str, client_id: str, client_secret: str, code: str) -> dict:
    """Once, when connecting: the one-time code → a refresh token and the API domain."""
    if accounts not in REGIONS:
        raise B.CrmError("Choose your Zoho region", retry=False)
    r = await B.send("POST", f"https://{accounts}/oauth/v2/token", data={
        "grant_type": "authorization_code", "client_id": client_id,
        "client_secret": client_secret, "code": code,
    })  # fmt: skip
    out = r.json() if r.content else {}
    if not out.get("refresh_token"):
        why = out.get("error") or "no refresh token"
        raise B.CrmError(f"Zoho didn't accept the code ({why}); make a new one", retry=False)
    return {"refresh_token": out["refresh_token"], "api_domain": out.get("api_domain")}


class Zoho:
    def __init__(self, keys: dict, config: dict):
        self.keys = keys
        self.config = dict(config)
        self._key = f"{keys.get('client_id')}:{keys.get('refresh_token', '')[-8:]}"
        self._users: dict[str, str] | None = None

    async def _token(self, fresh: bool = False) -> tuple[str, str]:
        cached = _TOKENS.get(self._key)
        if cached and not fresh and cached[2] > time.time() + 60:
            return cached[0], cached[1]
        accounts = self.keys.get("accounts", "")
        if accounts not in REGIONS:
            raise B.CrmError("Unknown Zoho region", retry=False)
        r = await B.send("POST", f"https://{accounts}/oauth/v2/token", params={
            "grant_type": "refresh_token", "refresh_token": self.keys.get("refresh_token"),
            "client_id": self.keys.get("client_id"),
            "client_secret": self.keys.get("client_secret"),
        })  # fmt: skip
        out = r.json() if r.content else {}
        if not out.get("access_token"):
            raise B.CrmError(f"Zoho refused the keys ({out.get('error', 'no token')})", retry=False)
        domain = out.get("api_domain") or self.keys.get("api_domain") or "https://www.zohoapis.com"
        _TOKENS[self._key] = (
            out["access_token"],
            domain,
            time.time() + int(out.get("expires_in", 3600)),
        )
        return out["access_token"], domain

    async def _call(self, method: str, path: str, **kw) -> dict:
        for attempt in (1, 2):
            token, domain = await self._token(fresh=attempt == 2)
            try:
                auth = {"Authorization": f"Zoho-oauthtoken {token}"}
                r = await B.send(method, f"{domain}{path}", headers=auth, **kw)
            except B.CrmError as e:
                if attempt == 1 and "refused the keys (401)" in str(e):
                    continue  # the access token expired early: one new one, once
                raise
            if r.status_code == 204 or not r.content:
                return {}
            try:
                out = r.json()
            except ValueError:
                raise B.CrmError("Zoho's answer wasn't JSON", retry=False) from None
            return out if isinstance(out, dict) else {}
        return {}

    @staticmethod
    def _made_id(out: dict) -> str:
        row = (out.get("data") or [{}])[0]
        if row.get("status") != "success" or not (row.get("details") or {}).get("id"):
            raise B.CrmError(f"Zoho said no: {row.get('code') or row.get('message')}", retry=False)
        return str(row["details"]["id"])

    async def user_id(self, email: str | None) -> str | None:
        if not email:
            return None
        if self._users is None:
            out = await self._call("GET", "/crm/v7/users", params={"type": "ActiveUsers"})
            users = [u for u in out.get("users") or [] if u.get("email") and u.get("id")]
            self._users = {str(u["email"]).lower(): str(u["id"]) for u in users}
        return self._users.get(email.lower())

    async def find_by_phone(self, phone: str) -> str | None:
        """Leads first, then Contacts; the id is kept as "Leads:<id>" / "Contacts:<id>"."""
        for module in ("Leads", "Contacts"):
            out = await self._call("GET", f"/crm/v7/{module}/search", params={"phone": phone})
            rows = out.get("data") or []
            if rows and rows[0].get("id"):
                return f"{module}:{rows[0]['id']}"
        return None

    async def create_lead(self, lead: B.NewLead) -> str:
        first, _, last = (lead.name or "").partition(" ")
        row = {"Last_Name": last or first or lead.phone, "First_Name": first if last else None,
               "Phone": lead.phone, "Email": lead.email, "Lead_Source": "Versnq Core"}  # fmt: skip
        owner = await self.user_id(lead.owner_email)
        if owner:
            row["Owner"] = {"id": owner}
        out = await self._call("POST", "/crm/v7/Leads",
                               json={"data": [{k: v for k, v in row.items() if v}]})  # fmt: skip
        return f"Leads:{self._made_id(out)}"

    @staticmethod
    def _split(lead_id: str) -> tuple[str, str]:
        module, _, rid = lead_id.partition(":")
        return (module, rid) if rid else ("Leads", module)

    async def log_call(self, lead_id: str, call: B.CallInfo) -> str | None:
        module, rid = self._split(lead_id)
        incoming = call.direction == "in"
        kind = "Missed" if incoming and call.status != "answered" else (
            "Inbound" if incoming else "Outbound")  # fmt: skip
        h, m = divmod(round(call.seconds / 60), 60)
        row = {
            "Subject": f"{'Incoming' if incoming else 'Outgoing'} call (Versnq)",
            "Call_Type": kind,
            "Call_Start_Time": call.started_at.astimezone(UTC).isoformat(timespec="seconds"),
            "Call_Duration": f"{h:02d}:{m:02d}",
            "Description": f"{call.seconds} seconds · {call.status} · logged by Versnq Core",
        }
        if module == "Contacts":
            row["Who_Id"] = {"id": rid}
        else:
            row["What_Id"], row["$se_module"] = {"id": rid}, module
        owner = await self.user_id(call.rep_email)
        if owner:
            row["Owner"] = {"id": owner}
        return self._made_id(await self._call("POST", "/crm/v7/Calls", json={"data": [row]}))

    async def _note(self, lead_id: str, text: str) -> str | None:
        module, rid = self._split(lead_id)
        row = {
            "Parent_Id": {"module": {"api_name": module}, "id": rid},
            "Note_Content": text[:30000],
        }
        return self._made_id(await self._call("POST", "/crm/v7/Notes", json={"data": [row]}))

    async def log_message(self, lead_id: str, msg: B.MessageInfo) -> str | None:
        way = "from the lead" if msg.direction == "in" else "to the lead"
        return await self._note(
            lead_id, f"WhatsApp {way} ({msg.at:%d %b %Y %H:%M} UTC): {msg.text}"
        )

    async def log_note(self, lead_id: str, note: B.CallNote) -> str | None:
        return await self._note(
            lead_id, f"Call notes (Versnq), {note.at:%d %b %Y %H:%M} UTC\n{note.text()}"
        )

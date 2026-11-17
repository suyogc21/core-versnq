"""LeadSquared, from apidocs.leadsquared.com (read Nov 16). Keys go in the x-LSQ-AccessKey /
x-LSQ-SecretKey headers; the host depends on the account's region.

- find:    GET  /v2/LeadManagement.svc/RetrieveLeadByPhoneNumber?phone=<digits only>
           (searches Phone and Mobile; the most recently active lead first) → [{"ProspectID"}]
- create:  POST /v2/LeadManagement.svc/Lead.Create [{"Attribute", "Value"}] → Message.Id
- calls:   POST /v2/Telephony.svc/LogCall (their call-log API for telephony connectors)
- WhatsApp: POST /v2/ProspectActivity.svc/Create with the company's activity code
           (made once with ProspectActivity.svc/CreateType, or typed in by the admin)
- call notes: the same activity API with a "Call notes (Versnq)" type (summary, next step,
           recording link), made the first time it's needed
- users:   GET  /v2/UserManagement.svc/User/Retrieve/ByEmailAddress → [{"UserId"}]
- all users (lead pull, Nov 17): GET /v2/UserManagement.svc/Users.Get
           → [{"ID", "EmailAddress", "StatusCode": 0 active / 1 inactive}]
- leads changed in a window (lead pull): POST /v2/LeadManagement.svc/Leads.RecentlyModified
           {Parameter: {FromDate, ToDate} (UTC "YYYY-MM-DD HH:MM:SS"), Columns.Include_CSV,
           Paging {PageIndex from 1, PageSize}, Sorting} → {RecordCount, Leads: [{LeadPropertyList:
           [{Attribute, Value}]}]}; at most 5000 per call. Filtering by owner isn't documented,
           so Core reads every changed lead and keeps those of its own reps.

Not in the docs, so to confirm on a real account: the recording link's field, whether the
activity date is UTC, and whether CreateType's Message.Id is the activity code.
"""

from datetime import UTC, timedelta

from app.modules.connectors import base as B

HOSTS = {
    "api.leadsquared.com": "Singapore",
    "api-us11.leadsquared.com": "United States",
    "api-in21.leadsquared.com": "India (Mumbai)",
    "api-in22.leadsquared.com": "India (Hyderabad)",
    "api-me61.leadsquared.com": "Middle East",
    "api-ir31.leadsquared.com": "Ireland",
    "api-ca12.leadsquared.com": "Canada",
}
WHEN = "%Y-%m-%d %H:%M:%S"
COLUMNS = "ProspectID,FirstName,LastName,EmailAddress,Phone,Mobile,OwnerId"


class LeadSquared:
    def __init__(self, host: str, keys: dict, config: dict):
        if host not in HOSTS:
            raise B.CrmError("Unknown LeadSquared region", retry=False)
        self.base = f"https://{host}/v2"
        self.headers = {"x-LSQ-AccessKey": keys.get("access_key", ""),
                        "x-LSQ-SecretKey": keys.get("secret_key", "")}  # fmt: skip
        self.config = dict(config)
        self.made_notes_event: int | None = None  # set when log_note made the activity type
        self._users: dict[str, str | None] = {}

    async def _call(self, method: str, path: str, **kw):
        r = await B.send(method, f"{self.base}/{path}", headers=self.headers, **kw)
        try:
            return r.json()
        except ValueError:
            raise B.CrmError("LeadSquared's answer wasn't JSON", retry=False) from None

    @staticmethod
    def _id(out) -> str:
        made = (out or {}).get("Message", {}).get("Id") if isinstance(out, dict) else None
        if not made:
            raise B.CrmError("LeadSquared didn't return an id", retry=False)
        return str(made)[:100]

    async def find_by_phone(self, phone: str) -> str | None:
        out = await self._call("GET", "LeadManagement.svc/RetrieveLeadByPhoneNumber",
                               params={"phone": phone.lstrip("+")})  # fmt: skip
        return str(out[0]["ProspectID"]) if isinstance(out, list) and out else None

    async def user_id(self, email: str | None) -> str | None:
        if not email:
            return None
        if email not in self._users:
            out = await self._call("GET", "UserManagement.svc/User/Retrieve/ByEmailAddress",
                                   params={"emailAddress": email})  # fmt: skip
            self._users[email] = str(out[0]["UserId"]) if isinstance(out, list) and out else None
        return self._users[email]

    async def create_lead(self, lead: B.NewLead) -> str:
        first, _, last = (lead.name or "").partition(" ")
        fields = {"FirstName": first, "LastName": last, "Phone": lead.phone,
                  "EmailAddress": lead.email, "Source": "Versnq Core"}  # fmt: skip
        owner = await self.user_id(lead.owner_email)
        if owner:
            fields["OwnerId"] = owner
        body = [{"Attribute": k, "Value": v} for k, v in fields.items() if v]
        return self._id(await self._call("POST", "LeadManagement.svc/Lead.Create", json=body))

    async def log_call(self, lead_id: str, call: B.CallInfo) -> str | None:
        """Incoming: from the lead to the rep; outgoing: from the rep to the lead."""
        rep = call.rep_phone or ""
        incoming = call.direction == "in"
        end = call.started_at + timedelta(seconds=call.seconds)
        body = {
            "SourceNumber": call.number if incoming else rep,
            "DestinationNumber": rep if incoming else call.number,
            "CallerSource": "Versnq Core",
            "LeadId": lead_id,
            "Direction": "Inbound" if incoming else "Outbound",
            "Status": "Answered" if call.status == "answered" else "Missed",
            "StartTime": call.started_at.astimezone(UTC).strftime(WHEN),
            "EndTime": end.astimezone(UTC).strftime(WHEN),
            "CallDuration": call.seconds,
            "CallSessionId": str(call.call_id),
        }
        user = await self.user_id(call.rep_email)
        if user:
            body["UserId"] = user
        return self._id(await self._call("POST", "Telephony.svc/LogCall", json=body))

    async def log_message(self, lead_id: str, msg: B.MessageInfo) -> str | None:
        code = self.config.get("activity_event")
        if not code:
            raise B.CrmError("Set the WhatsApp activity code in Settings → Connected CRM",
                             retry=False)  # fmt: skip
        way = "from the lead" if msg.direction == "in" else "to the lead"
        body = {
            "RelatedProspectId": lead_id,
            "ActivityEvent": int(code),
            "ActivityNote": f"WhatsApp {way}: {msg.text}"[:2000],
            "ActivityDateTime": msg.at.astimezone(UTC).strftime(WHEN),
        }
        return self._id(await self._call("POST", "ProspectActivity.svc/Create", json=body))

    async def make_activity_type(
        self, name: str = "WhatsApp (Versnq)", about: str = "WhatsApp messages from Versnq Core"
    ) -> str:
        """Once: an activity type in their LeadSquared; its code is kept in the connection."""
        out = await self._call("POST", "ProspectActivity.svc/CreateType",
                               json={"ActivityEventName": name, "Description": about})  # fmt: skip
        return self._id(out)

    async def log_note(self, lead_id: str, note: B.CallNote) -> str | None:
        code = self.config.get("notes_event")
        if not code:  # the first note: make the type, the sync keeps its code
            code = await self.make_activity_type(
                "Call notes (Versnq)", "Call summaries and recordings from Versnq Core"
            )
            self.config["notes_event"] = int(code)
            self.made_notes_event = int(code)
        body = {
            "RelatedProspectId": lead_id,
            "ActivityEvent": int(code),
            "ActivityNote": note.text()[:2000],
            "ActivityDateTime": note.at.astimezone(UTC).strftime(WHEN),
        }
        return self._id(await self._call("POST", "ProspectActivity.svc/Create", json=body))

    async def users(self) -> list[dict]:
        """Every user: {"id", "email", "active"} (lead pull: owners matched by email)."""
        out = await self._call("GET", "UserManagement.svc/Users.Get")
        if not isinstance(out, list):
            raise B.CrmError("LeadSquared's user list wasn't a list", retry=False)
        return [
            {
                "id": str(u.get("ID") or ""),
                "email": (u.get("EmailAddress") or "").strip().lower(),
                "active": u.get("StatusCode") in (0, "0"),
            }
            for u in out
            if u.get("ID")
        ]

    async def changed_leads(self, since, until, page: int, size: int) -> list[dict]:
        """Leads changed between two UTC times, one page (from 1): {Attribute: Value} each."""
        body = {
            "Parameter": {
                "FromDate": since.astimezone(UTC).strftime(WHEN),
                "ToDate": until.astimezone(UTC).strftime(WHEN),
            },
            "Columns": {"Include_CSV": COLUMNS},
            "Paging": {"PageIndex": page, "PageSize": size},
            "Sorting": {"ColumnName": "ProspectAutoId", "Direction": "0"},
        }
        out = await self._call("POST", "LeadManagement.svc/Leads.RecentlyModified", json=body)
        leads = out.get("Leads") if isinstance(out, dict) else None
        if not isinstance(leads, list):
            raise B.CrmError("LeadSquared's lead list wasn't readable", retry=False)
        return [
            {p.get("Attribute"): p.get("Value") for p in (x.get("LeadPropertyList") or [])}
            for x in leads
        ]

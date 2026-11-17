# Any CRM: connectors and the "Calls + WhatsApp" plan

**Status:** plan, waiting for Suyog's approval (Nov 16). Nothing built yet.
**Why (Suyog, Nov 16):** "Anything can be connected with anything." Companies that keep their own CRM
(LeadSquared first) buy Core's call tracking, recordings and WhatsApp without switching. Core's own CRM
stays the main product. AI summaries need ACE.

## How it works
1. A call (phone app or Twilio) or a WhatsApp message arrives in Core as today.
2. Core finds the lead in **Core** as today. If the company has connected a CRM, Core also asks that CRM
   "who is this number?" and remembers the answer (the CRM's lead id) on Core's lead.
3. Core sends the call (direction, duration, status, rep, a link to the recording) or the WhatsApp message
   to the CRM as an activity on that lead. It retries in the background if the CRM is down or busy.
4. Unknown number: the phone still asks the rep (never silently). "New lead" creates it **in the
   connected CRM** (and Core keeps a linked copy); "Personal" never leaves the phone.

All CRMs sit behind one small interface, so LeadSquared is never written into the call pipeline:
`find_by_phone`, `create_lead`, `log_call`, `log_message`, `find_user_by_email`.

## Which CRMs (Suyog, Nov 16: "any CRM")
- **Custom CRM (works with any CRM):** the company gives Core three addresses of its own: find a lead by
  phone, create a lead, log an activity. Core calls them with a signed JSON body (same signing as Core's
  webhooks) and reads back the lead id. Works with any CRM that has an API, or via Zapier / Make.
- **Native, one at a time, each checked against its own docs first:** LeadSquared (docs checked, below),
  then HubSpot, Zoho CRM, Salesforce, Pipedrive, Freshsales.
- New leads on the "Calls + WhatsApp" plan go to the connected CRM, plus a hidden linked copy in Core
  (Suyog, Nov 16).

## LeadSquared (checked against apidocs.leadsquared.com, Nov 16)
- Keys: access key + secret key, sent as headers `x-LSQ-AccessKey` / `x-LSQ-SecretKey`. Host by region
  (Mumbai `api-in21`, Hyderabad `api-in22`, Middle East `api-me61`, US `api-us11`, Singapore `api`, …);
  the admin copies both from Settings → API and Webhooks.
- Find by phone: `GET LeadManagement.svc/RetrieveLeadByPhoneNumber` (digits only, e.g. 919876543210;
  searches Phone and Mobile; most recently active lead if several).
- Create: `POST LeadManagement.svc/Lead.Create` (Attribute/Value list) → new lead id in `Message.Id`.
- Calls: `POST Telephony.svc/LogCall` (their documented call-log API for telephony connectors: source and
  destination numbers, start/end in UTC, seconds, Answered/Missed, Inbound/Outbound, lead id, user id).
- WhatsApp messages: `POST ProspectActivity.svc/Create` with a custom activity type "WhatsApp (Versnq)"
  that Core creates once (`ProspectActivity.svc/CreateType`).
- Rep → their user: `UserManagement.svc/User/Retrieve/ByEmailAddress` (same email in both).
- Limits: about 25 calls per 5 seconds and a daily cap by plan; Core sends one at a time per company and
  waits when told "too many".
- **To confirm on a real LeadSquared account** (the docs don't say): which field takes the recording link,
  the activity date's time zone, whether `CreateType` returns the activity code. Until then the recording
  link also goes in the call's note.
- Later: LeadSquared's own webhooks (lead created/updated) to keep names and owners fresh in Core.

## The "Calls + WhatsApp" plan (about ₹599 per user)
- A company setting "Core CRM screens": off for this plan. Off hides leads, deals, customers, money,
  sequences and reports; the menu keeps My Day (calls to return), Calls, Inbox (WhatsApp), Settings.
- Core still keeps a thin lead record behind the scenes (number, name, the CRM's id) because calls,
  recordings and WhatsApp chats need something to hang on; people just don't manage leads in Core.
- AI call summaries only when the company also has ACE.
- Prices and plan limits are set later (pricing comes later); this only builds the switch.

## Database (needs approval): migration 0047
- `crm_connections`: one per company: provider (`leadsquared` now), API host, keys (encrypted like
  WhatsApp keys), on/off, settings (create leads in the CRM, activity code for WhatsApp), last error.
- `crm_syncs`: one per thing sent (call or message): the CRM's lead id and activity id, status
  (waiting, sent, failed), tries, next try, last error. A repeat is never sent twice.
- `leads.external_ids` (JSON, e.g. `{"leadsquared": "<id>"}`).
- `tenant_settings`: `crm_screens` on/off (default on).

## Screens
- Settings → Connected CRM: pick LeadSquared, region, paste keys, "Test connection" (looks up a number),
  what to send (calls, WhatsApp), create leads there or not, a list of recent sends with failures.
- Lead page: "Open in LeadSquared" link when linked.

## Tests
- A fake LeadSquared in the tests (no real account needed): a call reaches it once, with the right numbers
  and direction; busy (429) is retried later; keys never appear in logs or answers; another company's
  connection is invisible; screens off hides the CRM pages and the backend refuses their data.
- A live try needs a LeadSquared account (yours or the contact you spoke to): 🟡 until then.

## Order
1. Connector interface + LeadSquared + calls (the main ask).
2. WhatsApp messages to LeadSquared.
3. The "Calls + WhatsApp" switch.
4. Next CRMs on the same interface: HubSpot, Zoho (each checked against its own docs first).

## Added Nov 17 (Suyog: "build both")
- **Call notes to the CRM:** with ACE, when the summary is ready, one activity goes to the lead:
  summary, next step and the recording's private link. Without ACE, each call that gets a
  recording sends its link. LeadSquared: a "Call notes (Versnq)" activity type, made once.
  Custom CRM: an activity of type `call_note`.
- **Recording link:** `/api/v1/calls/{id}/recording/shared?until=…&sig=…`, signed by Core, no
  login; it stops working when the recording is removed (keep_days). A wrong or old link is a
  404. Migration 0048 lets crm_syncs hold `recording` and `summary` sends.

## HubSpot (built Nov 17; checked against developers.hubspot.com)
- **Key:** HubSpot stopped new private-app tokens (Sept / Oct 2026); the admin makes a **Service
  Key** (Development → Keys → Service keys), sent as `Authorization: Bearer`. Old private-app
  tokens still work.
- **Find:** `POST /crm/objects/2026-09/contacts/search` on phone / mobilephone, number without
  the country code (HubSpot compares area code + local number).
- **Calls:** `POST /crm/v3/objects/calls` (direction, duration in ms, status COMPLETED /
  NO_ANSWER / BUSY / FAILED, numbers, owner), linked to the contact with type 194.
- **Call notes and WhatsApp:** `POST /crm/v3/objects/notes`, linked with type 202.
- **Owner:** `GET /crm/v3/owners`, matched by the rep's email.
- **To confirm on a real account:** the exact scope names for calls and notes (not in the scopes
  table we read).

## Zoho CRM (built Nov 17; checked against zoho.com/crm/developer/docs, API v7)
- **Connect:** the admin makes a Self Client (api-console.zoho.com), generates a one-time code
  with the scopes listed on the settings page, and pastes client id, secret and code with the
  region. Core swaps the code for a refresh token (kept encrypted); access tokens (1 hour) are
  reused until they expire (Zoho allows 10 new ones per 10 minutes); a 401 gets one new token.
- **Find:** `GET /crm/v7/{Leads|Contacts}/search?phone=` (204 = none), Leads first; the id is
  kept as `Leads:<id>` or `Contacts:<id>`. **Create:** a Lead (Last_Name required).
- **Calls:** `POST /crm/v7/Calls` (Inbound / Outbound / Missed, start time, duration "HH:mm",
  exact seconds in the description); a Contact via Who_Id, a Lead via What_Id + $se_module.
- **Call notes and WhatsApp:** `POST /crm/v7/Notes` with Parent_Id {module, id}.
- **To confirm on a real Zoho account:** linking a call to a Lead (docs only show Contacts), the
  duration format. v8 exists with the same fields; we use v7 (fully documented).

## Decision (Nov 17, Suyog: "do we really need Pipedrive and all?")
No more native connectors until a paying customer on that CRM asks. LeadSquared, HubSpot and
Zoho cover the first market; "Another CRM" (any API, or Zapier / Make) covers the rest.
Pipedrive is half-built on the branch `parked/pipedrive-connector` (not merged, not tested);
Freshsales waits on a confirmed phone lookup in its API; Salesforce on a customer.

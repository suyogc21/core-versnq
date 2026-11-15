# Versnq ACE ↔ Versnq Core — integration brief

Written 2026-11-12, updated 2026-11-13 with Suyog's direction for ACE (§10–§12) and the Core changes ACE asked for (message events, who caused an event, local webhooks; Decision #43), from the Core codebase as it stands (after step 10b). For whoever builds ACE: a developer, or an AI session given this file. Everything marked **Built** exists and is tested in Core. Everything marked **Planned** or **To decide** does not exist yet. Don't present planned items as available.

---

## 1. The one rule

> **Core runs and records everything. ACE thinks and replies.**

- **Versnq Core** is the multi-tenant CRM (leads → deals → customers → invoices → payments, plus the inbox, sequences, email and WhatsApp). It works fully without ACE.
- **Versnq ACE** is a **separate product**, sold separately (setup + retainer + AI usage at cost). It plugs into Core and makes it smarter.
- **Core never depends on ACE.** ACE talks to Core **only** through Core's public REST API and Core's signed webhooks, the same doors any other system uses. No shared database, and no ACE code inside Core.
- Each company (tenant) connects ACE to **its own** Core workspace. ACE must keep every company's data apart, as Core does.

---

## 2. What Core already is (built, tested)

| Area | What exists |
|---|---|
| Companies and people | One workspace per company at `<slug>.<base domain>`. Roles: Owner, Admin, Sales Manager, Sales User, Finance, plus custom roles. Visibility: a sales user sees only their leads, a manager sees their team. Enforced in the database (row-level security) and the API. |
| Leads | Capture from forms, CSV, quick-add, API, the copy-in address and WhatsApp. Duplicate check on phone/email. Routing rules and owners. Stages, sources, tags, custom fields, scoring (hot/warm/cold bands). A timeline of every activity. |
| Lead `intent` | `hot` / `warm` / `cold` / `not_interested`, set through the API. Built for ACE. |
| Deals, customers, key accounts | Pipelines with stages, products, won/lost. A customer record with a document checklist. Key-account planning. |
| Money | Invoices, instalments, payments, Razorpay/Stripe links, balances, reminders. Amounts are integers in minor units with a currency code. |
| Email | Sequences (email, wait, task, check steps), templates with variables, open/click tracking, unsubscribe, bounces. **Shared inbox**: conversations per lead, colleagues, internal notes, private threads, saved replies. A user's own mailbox synced over IMAP/SMTP. Copy-in addresses. |
| WhatsApp, company number | Meta Cloud API (test sender until Meta verification). Templates sent for Meta approval. The 24-hour window enforced. STOP opt-out. Delivered/read receipts. Unknown number → lead. A small autoresponder (welcome/away). WhatsApp steps in sequences. Payment reminders. |
| WhatsApp, reps' own numbers | The Versnq Chrome extension on WhatsApp Web logs chats with known leads into Core. **Read-only: it never sends.** |
| Integrations | API keys (`vq_live_…`) acting as an integration user with a role. Signed outbound webhooks with retries. API and webhook logs. Event catalogue (§6). |
| Page layouts and field access | Per-role field access: edit, view only or hidden. API output respects it. |

Full feature history: `docs/plans/build-plan.md` and the spec's Decision log (`docs/specs/Versnq Core — Product & Feature Spec (v0).md`). Decisions that concern ACE: **#3, #4, #5, #37, #41**.

---

## 3. What ACE does (from the spec)

| # | Part | What it means | Where people see it |
|---|---|---|---|
| A1 | **Lead summary and intent** | One verdict per lead (Hot, Warm, Cold, Not interested) read across calls, chats and emails, plus a short summary and a suggested next step. | On the lead in Core |
| A2 | **AI replies in the inbox** | Drafts a reply for a rep to approve, or replies by itself where allowed. Multilingual. Uses the company's own knowledge base. | Core's inbox |
| A3 | **Hand-over to a human** | On negative sentiment, a complaint, price negotiation, or when the customer asks for a person: stops replying, assigns the conversation to a person, leaves an internal note. | Core's inbox |
| A4 | **Call intelligence** | A call is matched to the lead and analysed (verdict, objections, commitments, next step). Action items become tasks. **Recorder-agnostic** (Suyog, Nov 13): ACE is not tied to Fireflies or any one tool. A recording or transcript can come from any source (§12). | Lead timeline, tasks |
| A5 | **Outbound campaigns** | **ACE's own audience database** (Decision #4). Campaigns on email and WhatsApp (LinkedIn later). On a real positive reply, ACE creates the lead in Core (`origin: outbound_ace`, intent hot/warm), or appends the conversation to the existing lead. Core never stores the audience. | ACE console; leads in Core |
| A6 | **Red flags and campaign analytics** | Angry customer, deal at risk. Replies, positive responses, leads created, conversions. | Core (flags); ACE console (analytics) |

### Boundaries ACE must respect

- **WhatsApp auto-replies only on the company's official number** (Meta Cloud API), never on a rep's own WhatsApp (Decision #41). The extension is read-only by design.
- **WhatsApp rules:** free text only inside 24 hours of the person's last message; otherwise an approved template. Marketing templates only to people who opted in. STOP means stop. **Core enforces all of this**: if ACE asks Core to send something the rules forbid, Core refuses with a plain reason (HTTP 422).
- **Meta's AI policy** (reported in force from 15 Jan 2026): general-purpose AI chatbots are not allowed on the WhatsApp Business Platform. ACE must answer **only about the company's own business**, from its knowledge base, and hand over otherwise. Verify the current policy text with Meta before launch.
- **Email rules:** honour unsubscribes and suppression (Core enforces them on sends it makes).
- **Visibility:** ACE sees exactly what its API key's role allows, nothing more. Hidden fields come back blank.
- **Money is exact:** never round or float amounts. Read them as integer minor units plus currency.

---

## 4. How ACE connects to Core

```
            ┌───────────────── one company (tenant) ─────────────────┐
            │                                                         │
  Customer ─┼─► Core (acme.versnq.in)                                 │
  email /   │     inbox · leads · sequences · WhatsApp · money        │
  WhatsApp  │        │  signed webhooks (events)        ▲ REST API    │
            │        ▼                                  │ (API key)   │
            │     ACE service ── reads context, decides, writes back ─┘
            │        │
            │        ├─ ACE's own store: knowledge base, audiences,
            │        │  campaigns, AI logs, per-company settings
            │        └─ AI model (to decide: Claude via Anthropic API)
            └─────────────────────────────────────────────────────────┘
```

**Per company, ACE stores three things:**
1. **The Core workspace URL** (`https://<slug>.<base domain>`).
2. **A Core API key** for an integration user.
3. **The webhook signing secret** for the endpoint Core calls.

### Connecting a company (works today with built pieces)

1. In Core, an admin creates a role for ACE (Settings → Roles), for example "ACE", with the permissions it needs (see §5).
2. **Settings → Developers → API keys** → New key, role "ACE". The key (`vq_live_…`) is shown once.
3. **Settings → Developers → Webhooks** → New webhook, URL = ACE's receiver for this company, events = those in §6. Copy the signing secret.
4. In ACE's console, enter the workspace URL, the API key and the webhook secret. ACE checks the connection by calling `GET /api/v1/leads?limit=1`.
5. ACE pulls the company's setup (stages, sources, custom fields, users, WhatsApp templates) so it speaks the company's language.

**Planned:** a one-click "Connect ACE" in Core that does steps 1–3 in one go. It doesn't exist yet.

---

## 5. Authentication and limits (built)

| Item | Detail |
|---|---|
| Header | `Authorization: Bearer vq_live_…` on every call, against the company's own workspace host |
| Who ACE acts as | An **integration user** (not a person). Activities and sent messages show that user's name, e.g. "ACE". |
| What ACE may do | Exactly what the key's role allows. Suggested **"ACE" role** (a custom role, made in Settings → Roles): `leads.create`, `leads.edit`, `leads.assign` (tasks ACE creates go to the integration user unless assigned), `users.read` (needed for `GET /users`), `inbox.reply`, `inbox.take_over` (hand-over), `customers.read`, `invoices.read` (to quote balances), `deals.edit` (only if ACE moves deals), `sequences.manage` (only if ACE enrols leads). |
| Lead scope | The role's scope **must be "all leads"**. With a narrower scope, `POST /leads/upsert` finds an existing lead the key can't see, returns `lead_id: null`, and silently drops the `intent` and `conversation` sent with it. |
| Never Admin | Don't give the ACE key the Admin role: Admin also sees **private** conversations, which ACE must not read. |
| Rate limit | **300 requests a minute per key** (raised from 100 on Nov 13 for ACE; HTTP 429 with `Retry-After`). A first pass over 5,000 leads at about 7 calls each takes about 2 hours: spread it, cache, and refresh only on webhooks. Bulk read endpoints are planned, not built. |
| Logs | Every API call and webhook delivery is logged in Core (Settings → Developers → Logs), kept 30 days live, then archived for 12 months. |
| Errors | 401 bad key · 403 role lacks permission · 404 not visible or not found · 409 conflict · 422 a rule refused · 429 too fast. Every refusal body is `{"detail": "<sentence for people>", "code": "<stable name for programs>"}`. **Branch on `code`, never on the sentence.** |
| Contract | The full API is `docs/api/openapi.json` (OpenAPI 3), regenerated with every change. |

### Refusal codes (built, Nov 13)

Codes never change once published; new ones may be added. Unknown code → treat by HTTP status.

| `code` | Meaning | What ACE should do |
|---|---|---|
| `whatsapp_window_closed` | More than 24 h since the person's last message | Send an approved template instead, or wait for them to write |
| `whatsapp_needs_opt_in` | Marketing template to someone without WhatsApp opt-in | Use a utility template, or don't send |
| `whatsapp_opted_out` | They opted out (STOP) | Never retry; stop WhatsApp for this person |
| `whatsapp_template_not_approved` | The template isn't approved by Meta (yet) | Pick an approved one |
| `whatsapp_not_connected` | The company has no official number connected | Fall back to email or a task for a person |
| `whatsapp_reply_in_app` | The chat is a rep's own WhatsApp (extension), not the company number | Don't reply; a person answers on WhatsApp |
| `whatsapp_not_company_number` | Templates asked for on a rep's WhatsApp chat | Same as above |
| `whatsapp_send_failed` | Meta refused or couldn't be reached | Retry later with backoff |
| `no_phone` / `no_email` | The lead has no number / address | Skip or create a task |
| `email_opted_out` | Unsubscribed; only answering them is allowed | Don't start a new email |
| `email_suppressed` | Bounced or complained before | Never email this address |
| `invalid_cc` | A CC address is not valid | Fix the CC list |
| `email_send_failed`, `mailbox_auth_failed`, `mailbox_unreachable`, `mailbox_needs_reconnect` | The company's or user's mailbox failed | Retry later; tell an admin |
| `message_empty` | Nothing to send | Fix the request |
| `duplicate` | That person already exists (on create) | Use `POST /leads/upsert` instead |
| `validation_error` | The request body or a parameter is wrong (`detail` lists the fields) | Fix the request; don't retry |
| `not_found`, `forbidden`, `conflict`, `invalid` | General cases | By HTTP status |

---

## 6. Webhooks: Core → ACE (built)

Each delivery is a `POST` with a JSON body:

```json
{ "id": "<event uuid>", "type": "lead.intent_changed", "occurred_at": "2026-11-12T10:30:00+00:00", "data": { "...": "ids of what changed, plus small details" } }
```

**Headers:** `X-Versnq-Event`, `X-Versnq-Delivery`, `X-Versnq-Timestamp`, and `X-Versnq-Signature: sha256=<hex>`, where the hex is `HMAC_SHA256(secret, "<timestamp>.<raw body>")`.

```python
import hashlib, hmac, time

def verify(secret: str, headers: dict, raw: bytes) -> bool:
    ts = headers["X-Versnq-Timestamp"]
    if abs(time.time() - int(ts)) > 300:          # refuse replays older than 5 minutes
        return False
    want = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={want}", headers["X-Versnq-Signature"])
```

- **Retries:** after 1 min, 5 min, 30 min, 2 h, 6 h, 12 h, 24 h (8 tries). An endpoint failing for 3 days is switched off. Answer **2xx fast** and do the work in a queue.
- **Idempotency:** the same event may arrive twice. Ignore an `id` you have already handled.
- **Data:** events carry ids and small details. **Fetch the rest through the API**; never trust a webhook as the full record.
- **Who caused it (built, Nov 13):** every delivery's `data` also has `actor_user_id` and `actor_type`: `user` (a person, incl. through the extension), `integration` (an API key; `actor_user_id` is the key's integration user), `automation` or `system` (Core itself, e.g. Meta's or a mailbox's incoming message). **ACE skips events whose `actor_user_id` is its own integration user**, so it doesn't react to its own writes.
- **Trying it locally (built, Nov 13):** on a developer's machine (`ENVIRONMENT=dev`) a webhook may point at `http://localhost:…`, `127.0.0.1` or `host.docker.internal`, so ACE receives webhooks without a tunnel. Test and production refuse these; there it must be public `https`.

### Events useful to ACE (Core's catalogue)

| Event | ACE uses it to… |
|---|---|
| `lead.created`, `lead.updated`, `lead.assigned`, `lead.stage_changed`, `lead.merged` | keep its view of leads fresh; re-point data on merge |
| `lead.intent_changed` | know when intent changed (ACE is usually the producer) |
| `activity.logged` | see notes and calls people log (not every system activity) |
| `message.received`, `message.sent` | **the main trigger**: a message arrived or went out; refresh that lead's summary and intent |
| `sequence.enrolled`, `sequence.replied` | know a sequence got a reply |
| `deal.created`, `deal.stage_changed`, `deal.won`, `deal.lost` | deal-at-risk flags, summaries |
| `customer.created`, `payment.due`, `payment.received`, `payment.overdue` | money context for replies and flags |
| `task.created`, `task.due` | follow-up awareness |
| `call.recorded`, `call.analyzed` | **ACE is the producer** (Decision #5). Core defines them, but **there is no endpoint yet for ACE to emit them: Planned (C6)**, built when ACE's call step is |

### Message events (built, Nov 13; Decision #43)

`message.received` fires for every email or WhatsApp message that arrives; `message.sent` for every one that goes out. They are owned by the `inbox` module (none while it is switched off).

```json
{ "conversation_id": "…", "lead_id": "…", "message_id": "…",
  "channel": "email | whatsapp | whatsapp_extension", "direction": "in | out",
  "official": true, "actor_user_id": null, "actor_type": "system" }
```

| Fires | Source |
|---|---|
| `message.received` | inbound email (shared inbox, connected mailboxes, copy-in addresses), the company WhatsApp number (also for a STOP), a rep's chat logged by the extension |
| `message.sent` | a reply or email from Core, an email the user sent from their own mail app (Sent folder or copy-in), the company number (incl. sequence steps and automatic replies), a rep's own message logged by the extension |

- `official`: `true` the company number, `false` a rep's own WhatsApp (extension), `null` email.
- **Not fired** for older emails pulled in when a mailbox is first connected (that would flood ACE), and never twice for the same message (an email or WhatsApp seen again is skipped).
- Then fetch `GET /api/v1/conversations/{id}` (see the read warning in §7).

---

## 7. Core endpoints ACE uses (built)

All under `https://<slug>.<base domain>`. See `docs/api/openapi.json` for exact request and response shapes.

### Read context (what ACE "knows")
| Need | Endpoint |
|---|---|
| A lead's profile | `GET /api/v1/leads/{id}` (stage, owner, intent, score, consents, custom fields) |
| Find / list leads | `GET /api/v1/leads?q=&limit=` |
| The full timeline | `GET /api/v1/leads/{id}/activities` (calls, notes, emails, WhatsApp, stage changes, payments) |
| Conversations of a lead | `GET /api/v1/leads/{id}/conversations` → `GET /api/v1/conversations/{id}` (every message, direction, status, CC, attachments, internal notes; for WhatsApp, `window_ends_at`) |
| The inbox | `GET /api/v1/inbox?view=all|waiting|unassigned` |
| Deals | `GET /api/v1/deals?lead_id=…`, `GET /api/v1/deals/{id}` |
| Customer and money | `GET /api/v1/leads/{id}/customer`, `GET /api/v1/customers/{id}/money` (balances per currency) |
| Sequences the lead is in | `GET /api/v1/leads/{id}/sequences` |
| Company setup | `GET /api/v1/settings`, `/lead-stages`, `/lead-sources`, `/custom-fields`, `/pipelines`, `/users`, `/canned-replies`, `/whatsapp/templates` |

### Watch out (side effects)

- **`POST /leads/{id}/activities` is for people logging work, not for ACE summaries.** It marks the open follow-up task done, counts as contact (`last_contacted_at`, "contacted" status) for every type except `note`, and handles the next follow-up: without `next_follow_up_at` it **clears** the lead's follow-up date, and if the company requires follow-ups it is refused. Write summaries through `POST /leads/{id}/conversation` (`summary`) until the AI summary field is built (C3).
- **`GET /conversations/{id}` marks the conversation read** for the caller. For the ACE key that only affects its own integration user, not people, but don't expect it to be "unread" for ACE afterwards.
- **`POST /conversations/{id}/whatsapp-template` takes only `template_id`**: no variables of your own. The template's `{{lead.…}}` / `{{owner.…}}` fields are filled from the lead (custom values: Planned, C11).
- **`POST /sequences/{id}/enrol` takes `{"lead_ids": [...]}`**, a list.
- **`GET /leads/{id}/customer` answers `null` (not 403)** when the role lacks `customers.read` or the lead isn't a customer: don't read `null` as "not a customer" unless the role has the permission.

### Write back
| Action | Endpoint | Notes |
|---|---|---|
| Create or find a lead | `POST /api/v1/leads/upsert` | phones/emails, name, `source`, `origin: "outbound_ace"`, optional `intent` and `conversation` in the same call. Normal duplicate rules and routing apply. |
| Log a conversation that happened outside Core (e.g. an ACE campaign) | `POST /api/v1/leads/{id}/conversation` | channel, messages (`sender: lead|us`), `summary`, `external_id` for safe retries |
| Set intent | `PUT /api/v1/leads/{id}/intent` | `hot|warm|cold|not_interested` plus `reason`. Writes a timeline entry and emits `lead.intent_changed`. |
| Reply in a conversation | `POST /api/v1/conversations/{id}/reply` | email, or WhatsApp free text inside the 24 h window (Core refuses outside it) |
| Send a WhatsApp template | `POST /api/v1/conversations/{id}/whatsapp-template` or `POST /api/v1/leads/{id}/whatsapp` | approved templates only; marketing needs opt-in |
| Email a lead | `POST /api/v1/leads/{id}/emails` | |
| Hand over to a human | `PUT /api/v1/conversations/{id}/assignee` plus `POST /api/v1/conversations/{id}/notes` (internal note, with mentions) | needs `inbox.take_over` |
| Create a follow-up task | `POST /api/v1/tasks` | |
| Note on a deal | `POST /api/v1/deals/{id}/notes` | |
| Put a lead in a sequence | `POST /api/v1/sequences/{id}/enrol` | body `{"lead_ids": [...]}` |

---

## 8. Where ACE's "knowledge" comes from

| Source | Lives in | How ACE gets it |
|---|---|---|
| The lead: who they are, stage, owner, history, consents | Core | API (§7), refreshed on webhooks |
| What was said: emails, WhatsApp (company number and reps' chats via the extension), logged calls and notes | Core | Timeline and conversations API |
| Deals, customer status, balances due | Core | API, if the ACE role allows |
| The company's vocabulary: stages, sources, custom fields, industry labels, templates | Core | Setup endpoints |
| **The company's knowledge base**: products, pricing, FAQs, policies, tone, languages | **ACE** | Uploaded and edited in ACE's console. Core doesn't store it. |
| **Outbound audiences and campaigns** | **ACE** | ACE's own database (Decision #4) |
| Call recordings and transcripts (any recorder: a dropped file, a pasted transcript, later a connector; Decision #42) | **ACE** | ACE's call engine. Results written to Core as activities and tasks; `call.recorded` / `call.analyzed` once Core's call-ingest endpoint exists (Planned, C6). |

**Privacy:** client data is the client's. It is never sold or shared, and never used to train models. ACE should keep only what it needs, per company, and delete it when a company disconnects.

---

## 9. Does ACE have its own frontend?

**Yes, a small console of its own**, and most people never need it. The split:

| Who | Where | What |
|---|---|---|
| Sales reps, managers | **Inside Core** | The lead's intent and AI summary, ACE's draft replies to approve, red flags, hand-overs, and ACE's messages in the inbox. Reps work in one place. |
| Admins, Versnq staff | **ACE console** | Connect a Core workspace; knowledge base (upload documents, FAQs, pricing); behaviour (auto-reply or drafts only, tone, languages, hand-over triggers, working hours); campaigns and audiences; recordings and transcripts in (any recorder); a review log of every AI reply; usage and cost per company |

**Login:** ACE's own accounts at first. **Planned:** sign in with the Core account (single sign-on), not built.

### Core screens ACE needs (Planned in Core, not built)

| Planned in Core | Why |
|---|---|
| **Draft replies** in the inbox: ACE proposes, a rep edits/approves/discards | A2 "drafts" mode. Today ACE can only send directly. |
| **AI summary and next step** shown on the lead | A1. Today only `intent` has a home; a summary can only go in as a timeline entry. |
| **Red-flag** marker on leads/conversations, with a manager filter | A6 |
| "Sent by ACE" shown on automated messages, and a per-conversation **"ACE off"** switch | Transparency, and so a rep can stop ACE on one chat |
| One-click **Connect ACE** in Core settings | Easier than §4 steps 1–3 |
| Higher API rate limit for the ACE key, if needed | §5 |

---

## 10. To decide before planning ACE

| # | Question | Recommendation |
|---|---|---|
| D1 | Where ACE lives | A **separate project/service** with its own repo, database and deploy. It talks to Core only via API and webhooks. |
| D2 | Which AI model | **Claude** (Anthropic API). New dependency; usage billed to clients at cost. Needs approval. |
| D3 | Reference material | **Decided (Nov 13):** the "Versnq Desk" n8n agent is **not** part of ACE. ACE is not tied to Fireflies. The older Fireflies engine may still be shared as reference for the analysis prompts only. |
| D4 | Outbound sending | A Smartlead connector, or ACE's own sender. Still open. |
| D5 | Build order | ① A1 summary + intent → ② A2 drafts a rep approves → ③ auto-replies with hand-over (company WhatsApp number and email) → ④ A4 call intelligence → ⑤ A5 outbound campaigns → ⑥ A6 analytics |
| D6 | ACE's tech stack | Match Core where sensible (Python/FastAPI, Postgres, a queue worker; Next.js for the console). Decide with D1. **No n8n inside ACE** (§12). |
| D7 | Speech-to-text for dropped audio recordings | Needed only for A4 when someone uploads audio, not a transcript. The AI model reads text; turning audio into text needs a transcription service (for example Deepgram, AssemblyAI or OpenAI Whisper). New dependency and cost; needs approval. |

---

## 11. Trying it before go-live

- **Dev Core:** the demo company **Brightlane** at `brightlane.localhost:3000` (B2B HR software, Indian rupees) has leads, deals, customers, invoices, an email inbox and a test WhatsApp number. Demo logins are in `DEMO_CREDENTIALS.md` (kept out of git).
- **Test senders:** email and WhatsApp in dev are saved, not sent. `POST /api/v1/inbox/test-inbound` delivers a raw email as if it arrived. `POST /api/v1/whatsapp/test-webhook` delivers a Meta webhook body as if Meta sent it. Both exist outside production only.
- **Webhooks:** point a Core webhook at ACE's local receiver. `POST /api/v1/integrations/webhooks/{id}/test` sends a signed test delivery.


---

## 12. How ACE works (the design direction, Nov 13)

### The loop, for every company

```
1. Something happens      Core webhook (message arrived, lead changed, payment overdue…),
                          a recording/transcript dropped in, or a campaign reply
2. Gather context         Core API: lead, timeline, conversation, deals, balance
                          + ACE's knowledge base for this company (retrieved, not all of it)
3. Decide                 the AI model reads context + company rules → one structured answer:
                          intent, summary, reply text, hand over?, red flag?, tasks
4. Check the guardrails   in code, not in the prompt: company mode (drafts only / auto),
                          working hours, hand-over triggers, "ACE off" on this chat,
                          only the company number on WhatsApp, cost cap per company
5. Act through Core       set intent · log summary · send or draft the reply · hand over
                          (assign a person + internal note) · create tasks
                          Core still enforces its own rules (24 h window, opt-outs…)
6. Record                 every AI decision and its inputs in ACE's review log
                          (what it saw, what it did, cost), visible in the ACE console
```

**People stay in charge.** Every company starts in **drafts only**: ACE suggests and a rep approves. Automatic replies are switched on per company, per channel, by an admin. ACE hands over on anger, complaints, price negotiation, or a request for a person, and stops replying on that chat.

### Calls: recorder-agnostic (A4)

ACE accepts a call from **any** source and never depends on one vendor:
1. **Drop a recording** (audio file) in the ACE console or on the lead. ACE turns it into text with a transcription service (D7), then analyses it.
2. **Paste or upload a transcript** (text from any tool). ACE analyses it directly; no transcription needed.
3. **Connectors** (later, one by one, only when a customer asks): meeting tools that can send a transcript by webhook or API, for example Fireflies, Fathom, Otter, tl;dv, Zoom or Google Meet recordings. Each connector only feeds step 2.

The result goes to Core: a timeline entry with the summary, verdict, objections and next step; tasks for action items; intent if it changed; and the `call.analyzed` event.

Note: Wispr Flow, as far as we know, is a voice-dictation tool, not a call recorder. Text dictated with it reaches ACE like any typed transcript. Check before promising it as a connector.

### Why no n8n

- ACE must keep companies' data apart, keep secrets safe, be tested and be versioned. Workflows in n8n spread secrets and logic outside the codebase and are hard to test and to keep tenant-safe.
- Everything n8n would do here (receive webhooks, call APIs, call the AI) is a small amount of code in ACE's own service, with tests.
- **Customers may still use n8n themselves:** Core already has API keys and signed webhooks, so any company can wire its own n8n or Zapier to Core. That is the customer's choice, not part of ACE.

### Starting ACE in a new session

Give the new session this file and this prompt:

> You are building **Versnq ACE**, a separate product that plugs into **Versnq Core** (a multi-tenant CRM). Read `ACE-and-Core.md` fully first. It describes what Core already has, how ACE connects (API key + signed webhooks only, never Core's database), the rules ACE must respect, and the decisions made so far. ACE lives in its own project (D1). Do not change Core from the ACE project; list any Core changes ACE needs, and they are made in Core separately. Before writing code, propose ACE's plan for step ① (lead summary + intent): its data model, endpoints, console screens, how it receives Core webhooks and calls the Core API, AI prompts and guardrails, cost tracking, tests, and open questions. Wait for approval. Only built and tested features are described as available; everything else is "planned". Ask before adding any dependency. Client data is never sold, shared, or used to train models.

The Core-side additions ACE needs (§9, "Core screens ACE needs") are built **in the Core project**, when ACE reaches the step that needs them.

---

## 13. Outreach and ACE: how they work together (Nov 14, Decision #44)

**This section overrides older text in this file where they differ** (Decision #4 "campaigns in ACE's own database" and D4 "outbound sender" are replaced). Core's plan: `docs/plans/outreach-plan.md`.

### The split

| Core does (the hands) | ACE does (the brain) |
|---|---|
| Connects any number of inboxes per company (pool), sends campaigns and sequences rotating across them, limits, spacing, tracking, unsubscribe, suppression | Reads each reply and decides its **intent** from the company's own categories |
| Holds cold **contacts** (apart from leads) and **campaigns** | Writes a short **summary** and the **reasons** for the intent |
| Holds the company's **reply categories** and **rules** ("if Interested: make it a lead, assign, draft a reply…") and **runs** the rules | **Drafts** the answer from the company's knowledge base, in the same thread |
| Stores **drafts**; approve / edit / reject in Core's inbox; sends the approved one from the same inbox | Runs the **Slack app**: posts each draft with Approve / Edit / Reject and calls Core when someone clicks |
| Emits events; keeps the full trail on the contact / lead | Keeps its own knowledge base, prompts, usage and cost per company |

**ACE must not build:** its own email sender, its own contact or audience database, its own campaign scheduler, or n8n workflows. Those are Core's (or the customer's own n8n on Core's webhooks).

### The loop for one reply

1. A reply arrives in any pool inbox. Core stores it and emits `message.received` (built). For campaign replies the payload also carries `contact_id`, `campaign_id`, `mailbox_id` and `auto_submitted`; `lead_id` is null for a cold contact (**built**, O2).
2. ACE fetches the message and the thread (`GET /conversations/{id}`), and the company's categories (`GET /reply-categories`, **built** O3: key, name, description written by the company, which ACE uses in its prompt). Campaign threads come back from `GET /conversations/{id}` with `lead: null`, `contact` and `campaign` (incl. `description`, `step_sent`); API keys never mark a thread read.
3. ACE sends its verdict: `PUT /messages/{id}/classification` with `{category, confidence, summary, reasons, language, prompt_version}` (**built** O3; a person's sorting wins: `classified_by_person`). Core records it, emits `reply.classified`, and **runs the company's rules** for that category: e.g. convert the contact to a lead (owner by the rule, intent hot/warm), stop the campaign for them, create a task, notify.
4. If a rule says "draft a reply", Core emits `draft.requested`. ACE writes the draft: `POST /conversations/{id}/drafts` with `{request_id, reply_to_message_id, body, reasons, language}` (**built** O3; same `request_id` → same draft). Core emits `draft.created`.
5. Approval, in either place:
   - **Core inbox:** a person approves, edits or rejects.
   - **Slack (ACE):** ACE posts the draft; a click calls `POST /drafts/{id}/approve` (optionally with the edited body) or `/reject`, on behalf of the Slack user mapped to a Core user (mapping by email in ACE's console).
   Core sends the approved draft from the same inbox in the same thread and emits `draft.approved` / `message.sent`.
6. **Every company starts in drafts-only mode** (#42). Auto-send without approval can later be allowed per category by the company (e.g. "Out of office": no reply; "Unsubscribe": Core stops everything, no AI needed).

**O3 is built (Nov 15).** Everything in Core's "O3: the contract with ACE" (`docs/plans/outreach-plan.md`) exists: categories and rules (`GET /reply-categories`), `PUT /messages/{id}/classification`, `POST /conversations/{id}/drafts`, `GET /drafts/{id}`, `POST /drafts/{id}/approve | reject` with `on_behalf_of_user_id` (needs `drafts.approve_for_users` on ACE's role; Core checks that person's own rights: `user_cannot_approve`, `user_inactive`; `via` = `slack`), the events `reply.classified`, `draft.requested`, `draft.created`, `draft.approved`, `draft.rejected`, `draft.superseded`, `reply_categories.changed`, `contact.converted`. **ACE's role** (all leads) needs: `inbox.reply`, `outreach.reply`, `leads.create`, `leads.edit`, `drafts.approve_for_users` (an admin grants it to that role; it is never given to people by default, not even the Owner). Auto-send stays off (ACE step ④).

### Rules for ACE

- Ignore events whose `actor_user_id` is ACE's own integration user (built, C2).
- Never send directly; always through a Core draft or a Core endpoint, so Core's rules (window, opt-out, suppression, limits) always apply.
- Low confidence: classify as the company's "Needs a human" category; never guess.
- Branch on refusal `code`s (§5), not on sentences.

### Message for the ACE session (paste this)

> Core and ACE now split the work this way (Decision #44, `ACE-and-Core.md` §13, and Core's `docs/plans/outreach-plan.md`). **Core** owns inboxes, cold contacts, campaigns, sending, rotation, tracking, reply categories, rules and drafts storage. **ACE** owns intent classification against the company's own categories, summaries, drafted replies from the knowledge base, and a Slack app for approving drafts. ACE does **not** build a sender, a contact/audience database, a campaign scheduler or n8n flows; drop those from the ACE plan (Decision #4 and D4 are replaced). Please (1) update `docs/plans/ace-plan.md` to this split, (2) list the Core endpoints and events ACE needs from §13 with the exact fields you want, and anything missing, and (3) propose how the Slack app maps Slack users to Core users and handles Approve / Edit / Reject. Mark everything Core hasn't built yet as Planned (O1–O5). Wait for approval before code.

# Versnq ACE ↔ Versnq Core — integration brief

Written 2026-11-12 from the Core codebase as it stands (Core commit after step 10b). For whoever builds ACE: a developer, or an AI session given this file. Everything marked **Built** exists and is tested in Core. Everything marked **Planned** or **To decide** does not exist yet. Don't present planned items as available.

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
| A4 | **Call intelligence** | Fireflies-recorded calls matched to the lead and analysed (verdict, objections, commitments, next step). Action items become tasks. **A Versnq engine for this already exists**; its reference folder is still to be shared (Decision #3). | Lead timeline, tasks |
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
| What ACE may do | Exactly what the key's role allows. Suggested role permissions: `leads.create`, `leads.edit`, `deals.edit` (if ACE moves deals), `customers.read`, `invoices.read` (to quote balances), `inbox.reply`, `inbox.take_over` (for hand-over), `sequences.manage` (only if ACE enrols leads). To see every lead, the role must not be limited to "own leads". |
| Rate limit | **100 requests a minute per key** (HTTP 429 with `Retry-After`). Batch and cache. If ACE needs more, raise it in Core deliberately (planned, not built). |
| Logs | Every API call and webhook delivery is logged in Core (Settings → Developers → Logs), kept 30 days live, then archived for 12 months. |
| Errors | 401 bad key · 403 role lacks permission · 404 not visible or not found · 409 duplicate · 422 a rule refused (the message says why) · 429 too fast |
| Contract | The full API is `docs/api/openapi.json` (OpenAPI 3), regenerated with every change. |

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

### Events useful to ACE (Core's catalogue)

| Event | ACE uses it to… |
|---|---|
| `lead.created`, `lead.updated`, `lead.assigned`, `lead.stage_changed`, `lead.merged` | keep its view of leads fresh; re-point data on merge |
| `lead.intent_changed` | know when intent changed (ACE is usually the producer) |
| `activity.logged` | see notes and calls people log (not every system activity) |
| `sequence.enrolled`, `sequence.replied` | know a sequence got a reply |
| `deal.created`, `deal.stage_changed`, `deal.won`, `deal.lost` | deal-at-risk flags, summaries |
| `customer.created`, `payment.due`, `payment.received`, `payment.overdue` | money context for replies and flags |
| `task.created`, `task.due` | follow-up awareness |
| `call.recorded`, `call.analyzed` | **ACE is the producer** (Decision #5). Core defines them; ACE emits them through the API when call intelligence is built |

### Gap: incoming messages raise no event yet (Planned, needed for A2)

When an email or WhatsApp message **arrives** in Core's inbox, Core stores it, stops sequences and notifies people, but **does not emit an event**. Only `sequence.replied` fires, and only for people in a sequence. ACE's inbox replies need this. **Planned Core addition:** `message.received` and `message.sent`, with conversation id, lead id, channel and message id. Until then, ACE could poll `GET /api/v1/inbox`, but that's not recommended.

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
| Put a lead in a sequence | `POST /api/v1/sequences/{id}/enrol` | |

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
| Call recordings and transcripts (Fireflies) | **ACE** (Fireflies) | ACE's call engine. Results written to Core as activities, tasks and `call.analyzed`. |

**Privacy:** client data is the client's. It is never sold or shared, and never used to train models. ACE should keep only what it needs, per company, and delete it when a company disconnects.

---

## 9. Does ACE have its own frontend?

**Yes, a small console of its own**, and most people never need it. The split:

| Who | Where | What |
|---|---|---|
| Sales reps, managers | **Inside Core** | The lead's intent and AI summary, ACE's draft replies to approve, red flags, hand-overs, and ACE's messages in the inbox. Reps work in one place. |
| Admins, Versnq staff | **ACE console** | Connect a Core workspace; knowledge base (upload documents, FAQs, pricing); behaviour (auto-reply or drafts only, tone, languages, hand-over triggers, working hours); campaigns and audiences; Fireflies connection; a review log of every AI reply; usage and cost per company |

**Login:** ACE's own accounts at first. **Planned:** sign in with the Core account (single sign-on), not built.

### Core screens ACE needs (Planned in Core, not built)

| Planned in Core | Why |
|---|---|
| `message.received` / `message.sent` events | ACE learns a reply arrived (A2). See §6 gap. |
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
| D3 | Reference material | Share the **Fireflies call-intelligence engine** folder (Decision #3). Decide whether the "Versnq Desk" n8n WhatsApp agent is a starting point or stays separate. |
| D4 | Outbound sending | A Smartlead connector, or ACE's own sender. Still open. |
| D5 | Build order | ① A1 summary + intent → ② A2 drafts a rep approves → ③ auto-replies with hand-over (company WhatsApp number and email) → ④ A4 call intelligence → ⑤ A5 outbound campaigns → ⑥ A6 analytics |
| D6 | ACE's tech stack | Match Core where sensible (Python/FastAPI, Postgres, a queue worker; Next.js for the console). Decide with D1. |

---

## 11. Trying it before go-live

- **Dev Core:** the demo company **Brightlane** at `brightlane.localhost:3000` (B2B HR software, Indian rupees) has leads, deals, customers, invoices, an email inbox and a test WhatsApp number. Demo logins are in `DEMO_CREDENTIALS.md` (kept out of git).
- **Test senders:** email and WhatsApp in dev are saved, not sent. `POST /api/v1/inbox/test-inbound` delivers a raw email as if it arrived. `POST /api/v1/whatsapp/test-webhook` delivers a Meta webhook body as if Meta sent it. Both exist outside production only.
- **Webhooks:** point a Core webhook at ACE's local receiver. `POST /api/v1/integrations/webhooks/{id}/test` sends a signed test delivery.

# Versnq Core — Product & Feature Spec (v0)

Nov 5, 2026 · @Richa&Suyog

## Final decisions

| Decision | Locked call |
| --- | --- |
| Product family | **Versnq Core** (CRM) + **Versnq ACE** (agentic conversation engine), under the Versnq house brand alongside Versnq AMS |
| What Core is | A lead-centric, multi-tenant CRM sold as monthly SaaS. Leads, sequences, inbox, invoices and payments all live inside it |
| Sequences | **Inside Core.** Email and WhatsApp sequences are built, run and logged in Core. Every touch lands on the lead's timeline |
| Where ACE fits | ACE is the AI brain that plugs into Core's inbox and sequences to reply agentically. Sold separately: setup + retainer + API usage at cost |
| The simple rule | **Core runs and records everything. ACE thinks and replies.** Core works fully without ACE; ACE makes it smarter |
| LinkedIn | Inside Core as logging + assisted tasks (safe). Automated sending is a later, opt-in add-on with ban risk disclosed |
| Roles | Owner, Admin, Sales Manager, Sales User, Finance |
| Payments | In Core v1: invoices, installments, balances, reminders. It is the client's actual journey and the gap rivals leave |
| Parked | LMS onboarding (needs LMS triggers), blog generation |

## Packaging: one generic tree, configured per industry

Core is one generic tree that every business runs on, from first contact to final payment. Money is part of that tree, not an add-on. Industries differ only in labels, fields and stages, never in code. Build it generic; sell it vertical.

**The tree (same for everyone):** Lead → Follow-up → Deal → Customer → Invoice / installment plan → Payment → Balance → Reminders → Money dashboard

| Industry | A "lead" is called | The deal is | Money looks like |
| --- | --- | --- | --- |
| EdTech | Student | Course enrolment | Course fee, installments, balance due |
| FinTech distribution | Applicant / client | Loan, policy or investment | Fees, commissions, premiums due |
| SaaS company | Prospect / account | Subscription plan | Recurring invoices, renewals |
| Real estate | Buyer | Unit booking | Booking amount, milestone payments |
| Agency / services | Client | Project or retainer | Project invoices, monthly retainer |

| Layer | What it is | Who gets it | How it's charged |
| --- | --- | --- | --- |
| **Versnq Core** | The whole tree: leads, routing, timeline, tasks, pipelines, sequences, inbox, invoices, installments, recurring billing, payments, balances, reminders, money dashboard, roles, API & webhooks | Every tenant | Monthly subscription |
| **Industry setup** | Labels (Student, Buyer, Client), preset fields, stages, templates and dashboards for that niche | Chosen at onboarding | Included, or a one-time setup fee |
| **Versnq ACE** | AI replies in the inbox, AI scoring, summaries | Attached when wanted | Setup + retainer + API usage at cost |
| **Later add-ons** | LinkedIn automation, telephony, LMS connector | On request | Add-on price |

**Build rules this implies:**

- Every module sits behind a per-tenant feature flag. A switched-off module hides its menus, screens and events.
- Industry packs are configuration, not code: seed data for custom fields, pipeline stages, templates and dashboards. Adding a new niche should never need a deploy.
- Customer tweaks go through settings and custom fields first. Code changes for one customer are the last resort.
- Core must never depend on a module. Modules depend on Core and talk through its events.

## How everything revolves around Core

One loop, one place:

1. **Capture** — lead arrives from a site form, ad, WhatsApp, CSV or API
2. **Assign** — auto-routed to a salesperson by rules
3. **Engage** — enrolled into an email + WhatsApp sequence; LinkedIn steps appear as tasks
4. **Converse** — replies land in Core's unified inbox; the rep answers, or ACE answers if enabled
5. **Convert** — lead becomes customer; registration and document collection triggered
6. **Bill** — invoice or installment plan created; payment link sent
7. **Collect** — payments tracked, balances shown, reminders automated
8. **Analyse** — every step above is an activity, so every step is reportable

Two tiers of automation inside Core:

- **Rule-based (Core, every plan):** scheduled template messages, delays, conditions, stop-on-reply
- **Agentic (ACE add-on):** AI reads the conversation and replies in context, multilingual, then logs back to Core

## Feature catalogue

v1 = ship for the first client. Later = roadmap once v1 is stable.

### 1. Lead capture & distribution

| Feature | Detail | Phase |
| --- | --- | --- |
| Web form / webhook capture | Endpoint per source; React sites post leads directly | v1 |
| Ad lead forms | Meta and Google lead-form connectors | Later |
| CSV import | Field mapping, duplicate check on import | v1 |
| Manual add | Quick-add from web and mobile | v1 |
| Inbound WhatsApp as lead | First message from an unknown number creates a lead | v1 |
| De-duplication | Match on phone and email; merge tool | v1 |
| Source attribution | Source, campaign, UTM captured on every lead | v1 |
| Auto-assignment | Round-robin, rule-based (source, course, language, region) | v1 |
| Leakage guard | Untouched in X hours → alert manager or reassign | v1 |
| Consent capture | WhatsApp and email opt-in stored with timestamp | v1 |

### 2. Lead management

| Feature | Detail | Phase |
| --- | --- | --- |
| 360° lead view | Profile, timeline, deals, invoices, documents in one screen | v1 |
| Activity timeline | Every email, WhatsApp, call, note, stage change, payment | v1 |
| Stages & statuses | Configurable lifecycle per tenant | v1 |
| Custom fields | Per-tenant fields; grouped field sets (e.g. KYC) | v1 |
| Tags, lists, smart views | Saved filters per user and team | v1 |
| Lead scoring | Rule-based points (activity, source, engagement) | v1 |
| AI scoring & red flags | Sentiment and intent from conversations | ACE add-on |
| Bulk actions | Assign, tag, enroll, update in bulk | v1 |

### 3. Tasks & activities

| Feature | Detail | Phase |
| --- | --- | --- |
| Tasks & follow-ups | Due dates, owners, reminders | v1 |
| Follow-up SLAs | Auto-task when a lead hits a stage; escalation if missed | v1 |
| Call logging | Outcome, notes, next action | v1 |
| Call intelligence (Fireflies) | Summary-ready webhook → pull transcript, summary and action items → match lead by participant email (else unmatched queue, one-click link) → ACE verdict, objections, commitments, next step → timeline entry + tasks with due dates; rep can override the verdict | ACE add-on (v1 for first client) |
| Click-to-call / dialer | Telephony integration; recording of regular phone calls | Later |
| Meeting scheduling | Google Calendar sync, booking link | Later |

### 4. Pipelines & deals

| Feature | Detail | Phase |
| --- | --- | --- |
| Multiple pipelines | One per course, product or program | v1 |
| Kanban board | Drag between stages | v1 |
| Deal value & expected close | Feeds revenue forecast | v1 |
| Won/lost reasons | Mandatory on close; reportable | v1 |
| Products / course catalogue | Price list attached to deals | v1 |

### 5. Sequences (inside Core)

| Feature | Detail | Phase |
| --- | --- | --- |
| Sequence builder | Steps, delays, conditions, branches | v1 |
| Email steps | Templates with variables, per-domain sender | v1 |
| WhatsApp steps | Approved templates; free-form only inside the 24h window | v1 |
| LinkedIn steps | Created as tasks for the rep (connect, message) | v1 |
| Auto-enroll triggers | On new lead, stage change, tag, form | v1 |
| Stop rules | Stop on reply, conversion, opt-out, payment | v1 |
| Quiet hours & throttling | Per tenant and per channel | v1 |
| Sequence analytics | Sent, delivered, opened, replied, converted per step | v1 |
| A/B testing | Subject lines and template variants | Later |

### 6. Unified inbox & channels

| Feature | Detail | Phase |
| --- | --- | --- |
| Unified inbox | Email + WhatsApp replies in one inbox, threaded per lead | v1 |
| Assignment & handoff | Conversation follows lead owner; manager can take over | v1 |
| Canned replies | Saved responses | v1 |
| Multi-domain email | Several sending domains with SPF/DKIM/DMARC | v1 |
| Open/click tracking | Logged to timeline | v1 |
| WhatsApp Cloud API | Tenant's own number; template management; opt-out | v1 |
| WhatsApp health | Quality rating and messaging-tier display | v1 |
| AI replies in inbox | ACE drafts or sends replies | ACE add-on |
| LinkedIn send automation | Opt-in, rate-limited, risk disclosed | Later add-on |
| SMS | Via provider | Later |

### 7. Customer onboarding & documents

| Feature | Detail | Phase |
| --- | --- | --- |
| Convert lead → customer | Keeps full history | v1 |
| Registration form link | ~~Auto-sent on conversion~~ Not built: staff enter details and upload documents (Decision log #33) | — |
| Document checklist | Required docs per product (KYC, ID, photos) | v1 |
| Document vault | Uploads auto-filed per customer | v1 |
| Pending-document reminders | Automated via sequence | v1 |
| Welcome email | Fires on conversion | v1 |
| LMS enrolment trigger | Only once the LMS exposes an API or webhook | Parked |

### 8. Invoicing & payments

| Feature | Detail | Phase |
| --- | --- | --- |
| Invoices | Line items, tax fields (GST), PDF, numbering per entity | v1 |
| Installment plans | Commitment schedule: amount and due date per installment | v1 |
| Payment links | Razorpay (India), Stripe (UAE/US) | v1 |
| Payment status sync | Gateway webhooks mark paid automatically | v1 |
| Manual payment entry | For bank transfers; proof upload | v1 |
| Balance tracking | Paid, due, overdue per customer | v1 |
| Auto reminders | Before due, on due, overdue — email + WhatsApp | v1 |
| Multi-entity, multi-currency | India, Dubai, US entities; INR, AED, USD | v1 |
| Receipts | Auto-sent on payment | v1 |
| Collections aging report | 0–30 / 30–60 / 60+ days | v1 |
| Bank statement import | Reconcile direct transfers | Later |

### 9. Dashboards & analytics

| Dashboard | Shows | Phase |
| --- | --- | --- |
| Salesperson | My leads today, follow-ups due, my pipeline, my conversions, my collections | v1 |
| Sales Manager | Team funnel, source performance, rep leaderboard, leakage, SLA breaches | v1 |
| Owner / Admin | Revenue, collections, overdue, sequence performance, channel health | v1 |
| Finance | Invoices, dues, aging, entity-wise collections | v1 |
| Custom reports | Build-your-own report and export | Later |
| AI summaries | Conversation and pipeline summaries | ACE add-on |

### 10. Admin, security & settings

| Feature | Detail | Phase |
| --- | --- | --- |
| Roles & permissions | Owner, Admin, Sales Manager, Sales User, Finance | v1 |
| Record visibility | Own / team / all, per role | v1 |
| Field-level permissions | View, edit, hidden, mandatory | Later |
| Teams | Group reps; managers see their team | v1 |
| Multi-brand | Several brands and domains in one tenant | v1 |
| Audit log | Who changed what, when | v1 |
| Import / export | CSV both ways | v1 |
| 2FA | For Owner and Admin | v1 |
| Tenant isolation | Separate data per tenant; encrypted at rest | v1 |

### 11. API, webhooks & integrations

| Feature | Detail | Phase |
| --- | --- | --- |
| REST API | Leads, activities, deals, invoices, payments | v1 |
| Inbound webhooks | Capture leads from any source | v1 |
| Outbound webhooks | Admin picks events and a URL; signed JSON; retries | v1 |
| API & webhook logs | Success, failure, payload viewer | v1 |
| Payment gateways | Razorpay, Stripe | v1 |
| Fireflies | Per-tenant API key; listens for the summary-ready webhook; fetches transcript via GraphQL; needs a paid Fireflies plan | ACE add-on |
| Google Workspace | Gmail send, Calendar | Later |
| Zapier / N8n | Generic connector | Later |
| HubSpot / LeadSquared import | Migration tool for switchers | Later |
| Versnq ACE | Native plug-in | ACE add-on |

**Outbound event catalogue (v1):** `lead.created`, `lead.updated`, `lead.assigned`, `lead.stage_changed`, `lead.merged`, `record.created`, `record.updated`, `record.stage_changed`, `record.deleted`, `link.created`, `link.deleted`, `lead.intent_changed`, `activity.logged`, `call.recorded`, `call.analyzed`, `task.created`, `task.due`, `sequence.enrolled`, `sequence.replied`, `deal.created`, `deal.updated`, `deal.stage_changed`, `deal.deleted`, `deal.won`, `deal.lost`, `customer.created`, `document.received`, `document.verified`, `document.rejected`, `invoice.created`, `payment.due`, `payment.received`, `payment.overdue`

### 12. Access

| Feature | Detail | Phase |
| --- | --- | --- |
| Responsive web app | Works on phone browsers | v1 |
| Mobile app / PWA | Reps work leads on the go | Later |

## How people use it (Core + ACE live)

### Three ways a lead enters Core

Every lead carries an **origin** tag, so reports never mix them up.

| Origin | Where it comes from | What happens automatically | What the rep does |
| --- | --- | --- | --- |
| **Inbound** | Website forms, ad forms, inbound WhatsApp or email | Lead created, de-duplicated, assigned by routing rules, welcome sequence starts, rep notified | Calls or messages within the SLA |
| **Outbound (ACE)** | Campaigns ACE runs on email and WhatsApp (LinkedIn later) to an audience list | Cold contacts stay in the **audience**, not the pipeline. Only when someone replies with real interest does ACE create a lead, attach the conversation and an AI summary, tag it Warm, and assign it | Picks up a pre-warmed conversation, not a cold name |
| **Outside the CRM** | Referral, walk-in, event, phone call, personal WhatsApp, LinkedIn DM | Duplicate check; mandatory source field | Adds it by quick-add (web or phone), CSV upload, or forwarding to the tenant's capture email |

### The salesperson's day

1. **Opens "My Day"** — new leads, follow-ups due today, overdue follow-ups, hot leads flagged by ACE, payments due from their customers.
2. **Works the queue.** Opens a lead and sees the full timeline, the ACE summary and a suggested next step.
3. **Acts from inside Core** — calls, WhatsApps or emails without leaving the screen. Everything logs itself.
4. **Logs the outcome** with a disposition (Interested, Callback, Not reachable, Not interested…).
5. **Sets the next follow-up.** Core will not let an open lead sit without one. This is the anti-leakage rule.
6. **Logs custom activities** the admin has defined for the business (see below).
7. **Moves the deal** through stages; on a win, converts the lead to a customer.
8. **Collects:** the rep gathers the documents on the checklist and uploads them (Decision log #33), creates the invoice or installment plan and sends the payment link.
9. **Answers the inbox.** ACE has either replied already (inside the rules) or left a draft; the rep approves, edits or takes over.
10. **Ends the day** with a summary: done, pending, at risk.

**Rules the rep must follow:** every open lead has a next follow-up date; every call has a disposition; every lost deal has a reason; every manually recorded payment has proof attached.

### Custom activities

The admin creates activity types that match the business, each with its own fields. The rep logs them in two clicks; they show on the timeline, can trigger automations and appear in reports.

| Industry | Example custom activities |
| --- | --- |
| EdTech | Demo class attended, Counselling session, Document collected, Batch allotted |
| Real estate | Site visit done, Token paid, Agreement signed |
| FinTech | KYC verified, Application submitted, Loan sanctioned |
| SaaS / agency | Demo given, Proposal sent, Trial started |

### The sales manager

- Team queue and leaderboard; reassigns leads; sees SLA breaches and leads with no follow-up.
- Reviews ACE red flags (angry customer, deal at risk) and steps in.
- Approves discounts and special installment plans if the admin requires approval.

### The admin / owner

- **Sets up once:** industry setup and labels, custom fields, custom activity types, pipelines, routing rules, users and roles, email domains, WhatsApp number, payment gateways, templates and sequences, ACE knowledge base.
- **Runs campaigns with ACE:** picks an audience, channel and approved template, launches, watches replies; positive replies flow to reps automatically.
- **Watches the business:** leads by source and origin, conversion, rep performance, collections, overdue payments, channel health.

### Finance

- Sees invoices, installment schedules and payments across entities; records bank transfers with proof; tracks overdue and aging; receipts go out automatically.

### What the customer (student, buyer, client) sees

- WhatsApp and email messages, payment links, receipts and reminders (they send documents to the rep, who uploads them, Decision log #33). They never log in to Core in v1. A customer portal is a later option.

### Where ACE shows up inside Core

- AI summary and intent tag on every lead (Hot, Warm, Cold, Not interested) — one combined verdict across calls, chats and emails
- Call intelligence: Fireflies-recorded calls matched to the lead and analysed for objections, commitments and next step; action items become tasks
- Draft or automatic replies in the inbox, inside the WhatsApp 24-hour window
- **Hands over to a human** on negative sentiment, pricing negotiation, complaints, or when the customer asks for a person
- Campaign analytics: replies, positive responses, leads created, conversions

## Logins for the first client

| Login | Count | Sees |
| --- | --- | --- |
| Owner | 1 | Everything, including billing and settings |
| Sales User | 2 | Only their own leads, inbox and collections |
| Finance (optional) | 0–1 | Invoices and payments only |

## Who to sell Core to

Best fit = high lead volume, a considered purchase, WhatsApp-heavy buyers, and payment in installments. That is exactly where Core's sequences + payments loop wins.

| Niche | Why it fits | Core features that sell it | Fit |
| --- | --- | --- | --- |
| EdTech, coaching, test prep, course sellers | Many inquiries, counsellor follow-up, installment fees | Lead routing, WhatsApp sequences, installment reminders | Strongest |
| Study-abroad consultancies | Long journey, heavy documents, staged fees | Document checklist, pipelines, payment plans | Strong |
| Real estate brokers & developers | Ad leads, site visits, booking amounts | Ad capture, leakage guard, payment schedule | Strong |
| Clinics, diagnostics, wellness (HealthTech) | Appointment inquiries, packages, follow-ups | WhatsApp reminders, packages, collections | Strong |
| Fintech distributors (loan DSAs, insurance, wealth advisors) | Lead-to-application, KYC documents | KYC vault, document reminders, pipelines | Good — add consent and data-retention controls before selling |
| Agencies & service businesses | Proposals, retainers, recurring invoices | Pipelines, invoicing, reminders | Good |
| B2B SaaS companies | Trials, demos, email-first, company-centric | Sequences, pipelines | Weaker — they need company objects and usually run HubSpot |

Recommended order: **EdTech first** (your first client, a reference case), then study abroad and real estate, which need almost no new features.

## Open questions

1. Confirm the niche list — is "Hector SaaS" HealthTech or something else?
2. Pricing tiers: per tenant, per user, or flat plans (Starter / Growth / Pro)?
3. Payments v1 depth: confirm installment plans + gateway links + reminders as v1, with bank-statement reconciliation later.

## Decision log

### Nov 5, 2026 (@Suyog)

| # | Decision | Overrides |
| --- | --- | --- |
| 1 | **Money is parked.** Invoices, installments, payment links, gateway webhooks, balances, reminders, collections and the money dashboard are not built until unparked. | §8, money parts of §9, "Payments" in Final decisions |
| 2 | **Entities and currencies are not limited** to India / Dubai / US. Any country and any ISO 4217 currency, as long as the tenant's gateway supports it (applies once money is unparked). | §8 "Multi-entity, multi-currency" |
| 3 | **Fireflies call intelligence belongs to ACE**, not Core. A Versnq engine for this already exists (reference folder to be shared). | §3 "Call intelligence" |
| 4 | **ACE outbound audience is ACE's own database.** Campaigns run in ACE. On a positive reply ACE creates the lead in Core (tagged hot/warm). If the contact already exists as a Core lead, ACE only appends the conversation to that lead's timeline. Core does not store audiences. | "Three ways a lead enters Core" — Outbound row |
| 5 | **Core defines `lead.intent_changed` and `call.analyzed`** in its event catalogue; ACE is the producer. | §11 event catalogue |
| 6 | **No limits on tenant size.** Any number of users, teams, admins and managers per tenant. | — |
| 7 | **Platform admin panel** (Versnq staff) to add companies (tenants), their users and access, modelled on the Versnq AMS tenant system (reference to be shared). | §10 |
| 8 | **MCP layer** is wanted and will be built in parallel later, on top of the REST API. Not designed or built yet. | §11 |
| 9 | **API-first.** Build the APIs first; MCP and UI follow. UI design is discussed later. | — |

| 10 | **A lead is either a person or an organisation** (company / agency), chosen per lead. An organisation lead has one or more contact persons. Example: Versnq selling Core treats "Acme Agency" as the lead. EdTech/FinTech mostly use person leads. No industry branches in code. | Niche table ("need company objects") |
| 12 | **Each client company gets its own web address:** `<slug>.<BASE_DOMAIN>` (e.g. `acme.versnq.in`). Domain is a setting. Reserved slugs: www, app, api, admin, platform. End customers (students, buyers) never log in. | §12 Access |
| 13 | Phase 1 answers: one email may belong to several client companies (kept separate); invite/reset emails use a console mailer until the ESP is chosen in Phase 3; no staff "log in as" in Phase 1; Finance role kept with minimal access; app connects as restricted `versnq_app` (RLS enforced). | — |
| 11 | **The developer is Claude**, working with the copied Superpowers skills and subagents where useful. | — |
| 14 | **Group person leads under organisation leads** (Phase 2, with de-duplication). Signals: email/website **domain** (strong) and a **company name** field (weaker). Default = **suggest** ("Rahul looks like he's from Acme — link?"); a tenant may switch domain matches to auto-link. Company-name matches are always suggestions (normalised: case, "Ltd", "Pvt", punctuation). Free email providers (gmail, yahoo, outlook, hotmail, icloud, rediffmail, …) never group. Matching never crosses tenants. Per-tenant on/off, off by default. A person with no match stays a single lead. | — |
| 15 | **Custom fields have a fixed key and a display label.** The key (e.g. `first_source`) never changes and is what the API, webhooks, CSV import and automations use; the label can be renamed freely. Extra attribution such as first/last source is created by each tenant as custom fields; Core keeps its built-in mandatory `source`. | — |
| 16 | **Automation builder in Phase 2:** WHEN an event (lead created, stage changed, field changed, activity logged, task overdue, no response in X hours) IF conditions (any field incl. custom) THEN actions (create task, update field, change owner, change stage, send webhook); sequence-enrol action added in Phase 3. | Spec had fixed automations only |
| 17 | Data model: DM1 (people at an organisation are person leads linked to it), DM2 (duplicates update the existing lead + 'Re-enquiry' activity) and DM4 (`phonenumbers` library) approved. **DM3 changed:** a lead needs at least one identifier — phone, email or LinkedIn profile URL. **DM5 rejected:** no automatic purge of deleted leads; retention rule still open. | data-model.md |
| 18 | **Delete is permanent.** Deleting a lead removes it and its timeline for good, after a confirmation warning. To keep a lead without working it, mark it **Invalid** (a closed lead stage): it stays searchable and can be reopened. Opt-outs survive deletion: opted-out phones/emails stay on a suppression list (identifier only). The audit log records who deleted which lead ID and when, without personal data. Lead identifiers stay limited to phone, email and LinkedIn profile URL (closes DM3, DM5). | data-model.md soft delete for leads |
| 19 | **UI:** clean and minimal (Linear / Attio style); each client's `primary_color` themes their own workspace; shadcn/ui + Tailwind, same versions as AMS; **staff console is a separate app** (like AMS `frontend-admin`); web app only for now (responsive, works in phone browsers — no native or PWA). | — |
| 20 | **Addresses:** clients at `{slug}.core.versnq.in` (`BASE_DOMAIN=core.versnq.in`, mirrors AMS's `{slug}.ams.versnq.in`); Core staff console at `admincore.versnq.in` (`admin.versnq.in` is taken by AMS). Local dev: `{slug}.localhost:3000` and `admincore.localhost:3001`. Frontend libraries approved: openapi-typescript, openapi-fetch, @tanstack/react-query, react-hook-form, zod, @hookform/resolvers, qrcode.react, @playwright/test. | Decision log #12 example domain |
| 21 | **Phase 2 (Nov 7):** Gate 1 approved; real email and go-live work deferred until the product is built. Plan answers: Finance has no lead access until customers (slice D); unassigned leads are seen by team- and all-scope roles; only Owner/Admin delete leads; default stages per pack are editable; a rep's own new lead is theirs; the follow-up rule is strict by default with a per-company "warn only" setting. **Close every gap found against LeadSquared/HubSpot, always generic (never tied to one industry):** required fields per stage, linked dropdowns, unique fields, calling queue and one-step call logging (slice A); calculated fields and engagement score (slice E); record page layouts, field-level permissions and custom record types (new slice G). | Spec "Field-level permissions: Later" (now slice G) |
| 22 | **Build order and step 1/2 plans (Nov 9):** `docs/plans/build-plan.md` approved ("go"): records-and-links engine (custom record types + labelled links) moves ahead of deals; in-app notifications added. Answers: uploaded CSVs stay in the database (≤20 MB / 50,000 rows) until file storage is chosen; round-robin = equal turns; notifications in-app only until email exists; forms protected by a per-source secret key, a rate limit and a hidden spam trap; record-type access set per role (view/create/edit/delete + own/team/all); no limit on record types; packs seed a sample type (Property, Batch); deleting a record is permanent after a warning. Step 1 details: quick-add refuses a duplicate (showing it only if you may see it) unless the company keeps duplicates; a merge deletes the other lead and keeps a snapshot with the survivor; an opt-out on either lead wins; forms are never refused for a missing required field; new event `lead.merged`; new permissions `leads.import`, `leads.merge` (Admin, Sales Manager). | Spec event catalogue (adds `lead.merged`) |
| 23 | **Step 2 — records and links (Nov 9):** companies define their own record types (key fixed, names editable; optional owner and stages; custom fields with every lead field rule, stored under entity `rt:<key>`); access per role and type (view / create / edit / delete + own/team/all; Owner always full; new types start Admin full, Sales Manager team, Sales User own, Finance none, custom roles view-only with their scope); types without owners are shared with everyone who may view; a type with records can only be switched off. Link types join leads and/or record types, named both ways, each side "one" or "many"; linking needs sight of both ends and edit on one; a link is written on both timelines. EdTech pack seeds Batch ("Enrolled in" / "Students"). New events `record.created`, `record.updated`, `record.stage_changed`, `record.deleted`, `link.created`, `link.deleted`. | Spec event catalogue |
| 24 | **Money unparked (Nov 10):** money is part of Core and will be built; it goes into the lineup as step 6 — after customers and documents (invoices hang off a deal or customer) and before dashboards (so owner and finance dashboards show collections). All of §8 is in scope; reminders and receipts start in-app and go out by email / WhatsApp once those channels exist. Decision log #2 (any entity, any currency) and rule 7 (integer minor units) apply. | #1 |
| 25 | **Step 3 — deals and pipelines (Nov 10):** plan in `docs/plans/build-plan.md` §6 approved ("go"). D1: deals are a third kind in the links engine (link to Property, Batch…). D2: every deal belongs to one lead (person or organisation). D3: one currency per pipeline (default: the company's new `default_currency`); no mixing on a deal. D4: everyone with deal access sees prices; reps edit unit price and discount on their own deal lines. D5: win % per stage, used for the weighted forecast. D6: a win leaves the lead untouched until customers (step 5). Lost needs a reason from the company's list. New permissions `deals.create`, `deals.edit`, `deals.delete`; new events `deal.created`, `deal.updated`, `deal.stage_changed`, `deal.deleted`. | Spec event catalogue |
| 26 | **Sign-in rate limit (Nov 10):** approved — sign-ins are limited to 60 per minute per network address (was 10), so a whole office behind one address is not locked out; the client address is the last proxy hop when `TRUST_PROXY_HEADERS` is on. Per-account limits are unchanged. | — |
| 27 | **Step 4 — tags, saved views, scoring, calculated fields, automation (Nov 11):** plan in `docs/plans/build-plan.md` §7 approved ("go"). A1: no separate static lists (tags + saved views). A2: tags on leads and deals. A3: anyone who edits creates tags; `crm.configure` renames, merges, deletes. A4: views private for anyone, team for team managers, everyone for `crm.configure`. A5: fit + engagement score (30-day window, editable), Hot/Warm/Cold thresholds editable; ACE intent separate. A6: formulas on numbers and dates only. A7: automations on leads and deals. A8: no delays until sequences (step 9). A9: simple signed webhook action now; full webhook management in step 11. | #16, #21 |
| 28 | **Message tracking and Smartlead (Nov 11):** Core's own email (step 9) tracks sent, delivered, bounces, spam complaints, unsubscribes, clicks, replies and opens (shown as estimated); hard bounces and complaints are suppressed automatically. WhatsApp (step 10) tracks sent, delivered, read, failed and replies. Cold outreach stays outside Core (#4); an optional **Smartlead connector** (cold campaigns in Smartlead, interested replies become Core leads with the conversation) is in the lineup after step 10, to be decided then. | §5 open/click tracking |
| 29 | **File storage (Nov 12):** uploaded files (documents, KYC, photos, later invoice PDFs and payment proofs) are saved on our own server's disk under `files/<company-id>/<year>/<month>/<random-name>`; Postgres keeps only the record (path, original name, size, type, checksum, uploader, what it belongs to). No outside storage service and no extra cost now. Files are never served straight from disk: every download goes through Core after a company + permission check. Limits per file (about 10 MB) and per company. The files folder is backed up nightly with the database; failed uploads leave nothing behind and a nightly clean-up removes orphans. All saving and reading goes through one storage module, so outside storage (S3 or similar) can replace it later without touching the rest — a future discussion, only when a big client or a second server needs it. | CLAUDE.md tech stack "S3-compatible object storage"; build-plan C1 "moved to S3 in step 5"; data-model `documents.file key (S3)` |
| 30 | **UI look (Nov 12):** Core takes the calm, Apple-like look of the Wondrlab CRM (ideas only, no code copied): grey page (#f5f5f7) with white rounded panels and soft shadows, Inter font, large bold titles and big numbers on record pages, My Day and settings; a frosted top bar; dark mode to match. Work screens (lists, board, My Day queue) keep the same density. Each client's `primary_color` still colours buttons and highlights. Done before step 5. | #19 "Linear / Attio style" |
| 31 | **Wondrlab ideas (Nov 12):** a **Key accounts** add-on (opportunity grid by budget holder, competitor status, relationship depth, account plan, group tree) joins the lineup after step 7, to be planned then. A **client / sponsor portal** is not built now; end customers still do not log in (#12). | — |
| 32 | **Step 5 — customers and documents (Nov 12):** plan in `docs/plans/build-plan.md` §8 approved ("go") with E1–E10 as recommended, except storage: **2 GB per company included**; more storage is a paid add-on (priced with the pricing tiers). Photos are shrunk in the browser before upload (PDFs untouched) so 2 GB holds far more; admins see usage and a warning at 80%. The B2B / SaaS demo company is built once steps 5–7 make Core demo-ready end to end. | #29 (quota detail) |
| 33 | **No customer uploads (Nov 12):** customers do not upload files or fill forms in Core through any link: they could send anything. Only staff (the salesperson or team) upload documents and enter customer details; managers verify. The customer link, its page, its settings and the "submitted by the customer" entry were removed (migration 0016). Customers still never log in (#12). | §7 "Registration form link"; #32 E5–E6; build-plan §8.3 |

Still open: pricing tiers; niche list (Hector SaaS); WhatsApp connection model (direct Meta Cloud API vs a BSP).

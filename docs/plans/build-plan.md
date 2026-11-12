# Versnq Core — what is built, what is left, and the order

Written 2026-11-09. Every row of the spec's feature catalogue, its "How people use it" section and the Decision log is listed here exactly once, so nothing is missed. Status: **Done**, **Part** (what is missing is named), **Planned** (step number), **Parked**, **Later** (spec says later), **ACE** (belongs to ACE).

Principles for every step (no shortcuts to hit a date):

1. Plan first (tables, endpoints, rules, tests, open questions) → Suyog approves → build.
2. Backend rules and tests first: tenant isolation, visibility, permissions, every rule. Then a simple working screen.
3. A step is "done" only when all tests, lint, type checks and the browser walk pass. Nothing half-tested goes into a demo.
4. Always generic: labels, fields, stages and packs, never `if industry`.

---

## 1. Built today

| Area | What works |
| --- | --- |
| Foundation | Companies (tenants) with their own web address, staff console, users, invites, sign-in, password reset, 2FA for Owner/Admin, roles + custom roles, own/team/all visibility, teams of any depth, labels per industry, time zone, branding, module switches, audit log, event outbox, row-level security on every table |
| Leads | Person or organisation leads, several phones/emails/LinkedIn per lead, phones cleaned to international format, custom fields (8 types, groups, required, unique, linked dropdowns), stages with required fields, Invalid stage with reason, sources, UTM fields, safe concurrent edits, permanent delete with ID-only audit |
| Work | Timeline (everything is an activity), calls with outcome, notes, custom activity types with their own fields, follow-up rule (strict or warn per company), one-step logging, tasks, My Day with calling queue, task-due events |
| Lists | Leads and users lists built for thousands of rows: paging, sort any column, multi-value filters, custom-field filters, view tabs with counts, bulk assign / stage / follow-up / delete, column picker, preview panel, full 3-column record page, phone layout |
| Demo | 3 demo companies, 360 leads with history, 250 users, credentials file, one-command reset |
| Tests | 257 backend tests, 4 browser end-to-end tests |

---

## 2. Every spec feature and its status

### Lead capture & distribution (spec §1)

| Feature | Status |
| --- | --- |
| Web form / webhook capture per source | Planned — step 1 |
| Ad lead forms (Meta, Google) | Later |
| CSV import with field mapping and duplicate check | Planned — step 1 |
| Manual quick-add (web and phone) | Done |
| Inbound WhatsApp creates a lead | Planned — step 9 (WhatsApp connector) |
| De-duplication on phone/email + merge tool | Planned — step 1 |
| Source attribution (source, campaign, UTM) | Done (fields); filled automatically by forms in step 1 |
| Auto-assignment: round-robin and rules | Planned — step 1 |
| Leakage guard (untouched in X hours → alert or reassign) | Planned — step 1 |
| Consent capture (email/WhatsApp opt-in with timestamp) | Planned — step 1 |
| Forwarding to a company capture email | Planned — step 8 (needs inbound email) |
| Group people under their organisation (Decision log #14) | Part — the link exists; domain/name suggestions in step 1 |

### Lead management (§2)

| Feature | Status |
| --- | --- |
| 360° lead view | Part — profile, timeline, tasks, links done; deals step 3, documents step 5, invoices step 6 |
| Activity timeline | Done for calls, notes, stage, owner, custom; email/WhatsApp in steps 8–9 |
| Configurable stages | Done |
| Custom fields + grouped field sets | Done for leads; for any record type in step 2 |
| Tags, lists, smart views (per user and team) | Built — step 4 |
| Rule-based lead scoring | Built — step 4 |
| Bulk actions: assign, update | Done |
| Bulk actions: tag, enrol | Tag built — step 4; enrol step 9 |
| AI scoring and red flags | ACE |

### Tasks & activities (§3)

| Feature | Status |
| --- | --- |
| Tasks and follow-ups with owners and due dates | Done |
| Reminders that reach the person (in-app notifications) | Planned — step 1 (**was missing from the roadmap**) |
| Follow-up SLAs: auto-task on stage, escalation if missed | Planned — step 1 |
| Call logging with outcome and next action | Done |
| Call intelligence (Fireflies) | ACE |
| Click-to-call, calendar booking | Later |

### Records and links (from the HubSpot / LeadSquared comparison)

| Feature | Status |
| --- | --- |
| Custom record types (Property, Vehicle, Batch…) with their own fields, stages, owner, timeline | Planned — step 2 (moved up from slice G) |
| Links between any records, with labels ("Decision maker", "Interested in") | Planned — step 2 (**new**) |
| Organisation page listing its people | Planned — step 2 |
| Live lists (update themselves from filters) | Planned — step 4 |

### Pipelines & deals (§4)

| Feature | Status |
| --- | --- |
| Several pipelines (per product, course, program) | Built — step 3 |
| Kanban board with drag | Built — step 3 |
| Deal value and expected close | Built — step 3 |
| Won/lost reasons, mandatory and reportable | Built — step 3 |
| Product / course catalogue with price list | Built — step 3 |

### Automation (Decision log #16) and extras from #21

| Feature | Status |
| --- | --- |
| WHEN event IF conditions THEN actions | Built — step 4 |
| Calculated fields, engagement score | Built — step 4 |
| Record page layouts per company | Planned — step 7 |
| Field-level permissions (view/edit/hidden/mandatory) | Planned — step 7 |

### Customers & documents (§7)

| Feature | Status |
| --- | --- |
| Convert lead → customer keeping history | Planned — step 5 |
| Registration form link | Planned — step 5 (sent by email/WhatsApp from steps 8–9) |
| Document checklist per product | Planned — step 5 |
| Document vault | Planned — step 5 (needs file storage choice) |
| Pending-document reminders, welcome email | Planned — step 8 (via sequences) |
| LMS trigger | Parked |

### Dashboards (§9)

| Feature | Status |
| --- | --- |
| Salesperson: today, follow-ups, my pipeline, conversions, end-of-day summary | Done — My Day + Dashboards → My numbers (step 7) |
| Sales Manager: team funnel, sources, leaderboard, leakage, SLA breaches | Done — Dashboards → Team (step 7) |
| Owner/Admin: revenue, collections, overdue, sequence performance, channel health | Done — Dashboards → Business (step 7); sequence and channel figures with steps 9–10 |
| Finance dashboard: invoices, dues, aging, entity-wise collections | Done — Dashboards → Money (step 7) |
| Custom reports | Later |

### Sequences, inbox, channels (§5, §6)

| Feature | Status |
| --- | --- |
| Sequence builder: steps, delays, conditions, branches | Planned — step 9 |
| Auto-enrol triggers, stop rules, quiet hours, throttling | Planned — step 9 |
| Email steps, templates with variables, per-domain sender | Planned — step 9 |
| Unsubscribe and suppression list | Planned — suppression list created in step 1, used in step 9 |
| Email tracking per message, sequence and campaign: sent, delivered, bounced (hard/soft), spam complaints, unsubscribes, clicks, replies, opens (labelled "estimated": Apple/Gmail image loading inflates them). Hard bounces and complaints go on the suppression list automatically | Planned — step 9 (Decision log #28) |
| WhatsApp tracking: sent, delivered, read, failed, replies (from Meta's status webhooks) | Planned — step 10 (Decision log #28) |
| Smartlead connector (optional add-on): cold campaigns run in Smartlead; interested replies arrive in Core as leads with the conversation, like ACE | Planned — after step 10, decide then (Decision log #28) |
| Unified inbox, assignment and handoff, canned replies | Planned — step 9 (email), step 10 (WhatsApp) |
| Multi-domain email (SPF/DKIM/DMARC), multi-brand | Planned — step 9 |
| WhatsApp connector: own number, templates, 24-hour window, opt-out, health | Planned — step 10 (after Meta registration) |
| LinkedIn steps as rep tasks | Planned — step 9 |
| Sequence analytics per step | Planned — step 9 |
| A/B tests, SMS, LinkedIn automation | Later |

### Admin, security (§10) and go-live

| Feature | Status |
| --- | --- |
| Roles, visibility, teams, audit, 2FA | Done |
| CSV import and export | Import step 1, export step 6 |
| Multi-brand | Planned — step 8 |
| Login history, idle sign-out, IP allowlist, failed-sign-in alert, DPDP export/erasure (S.1–S.5) | Planned — step 10 |
| Real invite/reset emails, lost-phone 2FA recovery, hosting with HTTPS, encryption at rest, backups (G.1–G.3) | Planned — step 11 |

### API & webhooks (§11)

| Feature | Status |
| --- | --- |
| Inbound webhooks for leads | Planned — step 1 |
| REST API with keys and rate limits | Planned — step 10 |
| Outbound signed webhooks with retries, logs, payload viewer | Planned — step 10 |
| ACE endpoints (lead upsert, conversation append, intent, call analysed) | Planned — step 10 |
| Payment gateways (Razorpay, Stripe) | Planned — step 6 |
| Google Workspace, Zapier/N8n, HubSpot/LeadSquared import | Later |

### Money (§8)

Unparked 2026-11-10 (Decision log #24) — **step 6**, after customers. Every row of spec §8:

| Feature | Status |
| --- | --- |
| Invoices: line items, tax fields (GST), PDF, numbering per entity | Done — step 6 |
| Installment plans: amount and due date per installment | Done — step 6 |
| Payment links: Razorpay (India), Stripe (UAE/US) | Done — step 6 |
| Payment status sync from gateway webhooks | Done — step 6 |
| Manual payment entry with proof upload | Done — step 6 |
| Balance tracking: paid, due, overdue per customer | Done — step 6 |
| Auto reminders before due, on due, overdue | Done — step 6: in-app + email from the company's mailbox (#34); WhatsApp from step 10 |
| Multi-entity, any currency (Decision log #2) | Done — step 6 |
| Receipts sent on payment | Done — step 6, by email (#34) |
| Collections aging report 0–30 / 30–60 / 60+ | Done — step 6 report; dashboard tile in step 7 |
| Bank statement import | Later |

Rule 7 applies throughout: amounts are integers in minor units with a currency code; never floats.

---

## 3. Build order

**Progress:** step 1 done 2026-11-09 (309 backend tests, 5 e2e, 23-check walk). Step 2 done 2026-11-09 (324 backend tests, 6 e2e, 20-check walk). Settings clean-up done 2026-11-10: the sidebar holds only places people work in; everything set up once is under one grouped Settings home (326 backend tests, 6 e2e, 34-check walk). Money unparked 2026-11-10 as step 6. Step 3 done 2026-11-10: deals and pipelines with a drag board, lost reasons, products and deal links (342 backend tests, 6 e2e, 26-check walk). Step 4 done 2026-11-11: tags, saved views, scoring, calculated fields and the automation builder (366 backend tests, 6 e2e, 26-check walk incl. a live automation run). UI restyle done 2026-11-12 (Decision log #30). Step 5 done 2026-11-12 (Decision log #32): customers, checklist, staff uploads, review; customer link removed (#33) (376 backend tests, 6 e2e, 30-check walk). Step 6 done 2026-11-12 (Decision log #34): invoices, installments, payments, Razorpay / Stripe links, pay-directly with UPI QR, emails from the company's mailbox, reminders, repeat invoices, aging (406 backend tests, 6 e2e, 30-check walk). Step 7 done 2026-11-12 (Decision log #35): Dashboards with My numbers / Team / Business / Money tabs and CSV export per list, admin-controlled (417 backend tests, 6 e2e, 24-check walk). B2B demo company Brightlane and step 7b key accounts done 2026-11-12 (Decision log #36) (424 backend tests, 6 e2e, 30-check walk). Scale fixes done 2026-11-12 after a 2-lakh-lead load test: trigram search indexes, grouped trend query, connection pool settings (425 backend tests, 6 e2e). Milestone 4 done 2026-11-12 (Decision log #37): API keys with roles, signed webhooks with retries, API and webhook logs with archive, lead upsert / conversation / intent endpoints, Settings → Developers (444 backend tests, 6 e2e, 23-check walk). Step 8 done 2026-11-12 (Decision log #38): page layouts (sections, highlights, add form) and field access per role (edit / view only / hidden) enforced everywhere (458 backend tests, 6 e2e, 23-check walk). Step 9a done 2026-11-12 (Decision log #39): templates with variables, sequences (email, wait, task, check), enrolment by hand / in bulk / by automation, stop rules, quiet hours and daily cap, test sender, open / click tracking, one-click unsubscribe, bounces and suppression, per-step results (471 backend tests, 6 e2e, 21-check walk with the worker sending). Step 9b-1 done 2026-11-12 (Decision log #40): conversations and the shared inbox — full trail with CC and attachments, replies thread and stop sequences, email from the CRM, colleagues added, internal notes with mentions, take over, private threads, saved replies, emailed file into the checklist, merge moves conversations (483 backend tests, 6 e2e, 19-check walk). Step 9b-3 done 2026-11-12 (Decision log #40): connect my inbox by IMAP + SMTP app password — Gmail / Google Workspace, Zoho, any mail server; only emails with known leads synced both ways, quiet 30-day backfill, exclusion list, no duplicates, wrong password shown and sending refused, email from Core through the user's own mailbox with a copy in Sent, disconnect keeps emails, admin removes synced ones (492 backend tests, 6 e2e, 20-check walk). Found while building: Outlook.com and Microsoft 365 no longer accept app passwords, so Outlook users need 9b-4 (one-click Microsoft sign-in); the screen says so. Step 9b-2 done 2026-11-12 (Decision log #40): copy-in address per company and per user — CC / BCC / auto-forward lands on the right lead, a colleague's email logged as theirs, unknown people become leads only when the company turns it on (with a chosen source), exclusions, no duplicates, new address on demand; works through a test entry point until inbound email is switched on with SES at go-live (497 backend tests, 6 e2e, 15-check walk). Step 10a done 2026-11-12 (Decision log #41): the reps' own WhatsApp — the Versnq Chrome extension (side panel with the lead, create / link lead, note, follow-up, saved replies into WhatsApp's box, chats with known leads saved once, group chats skipped, never sends), WhatsApp conversations in the inbox and on the lead, admin list of connected extensions (503 backend tests, 6 e2e, 24-check walk with the real extension on a stand-in WhatsApp Web page; not yet tried on the real WhatsApp Web). Next: 10b the official company number (after Meta Business verification; can be built now with a test sender), then ACE, then security extras and go-live.

| Step | What | Why here |
| --- | --- | --- |
| 1 | **Capture and routing**: CSV import, form/webhook capture, duplicates + merge, organisation suggestions, consent + suppression list, auto-assignment, SLAs and leakage guard, in-app notifications | Leads must come in clean and reach the right person |
| 2 | **Records and links engine**: custom record types, labelled links, organisation page | Deals and customers are built on it |
| 3 | **Deals and pipelines** | First real use of the engine |
| 4 | **Tags, saved views, live lists, scoring, calculated fields, automation builder** | Runs the business without manual work |
| 5 | **Customers and documents** | Files on our own server (Decision log #29). The UI restyle (#30) is done first |
| 6 | **Money**: invoices (tax, PDF, numbering per entity), installment plans, payment links (Razorpay, Stripe), gateway webhooks, manual payments with proof, balances, receipts, reminders, collections aging, any entity and currency | Unparked 2026-11-10 (Decision log #24). Invoices hang off a deal or customer, so it follows step 5 |
| 7 | **Dashboards and CSV export**, including the Finance dashboard and money on the owner's | Needs data from steps 1–6 |
| 7b | **Key accounts add-on** (opportunity grid, competitor status, relationship depth, account plan, group tree) | Decision log #31; planned after step 7 |
| 8 | **Page layouts and field-level permissions** | |
| 9 | **Sequences, email, inbox, multi-brand** | Needs an email provider decision. Payment reminders and receipts also go by email from here |
| 10 | **WhatsApp connector** | After Meta registration. Payment reminders by WhatsApp from here |
| 11 | **Public API, outbound webhooks, ACE endpoints, security S.1–S.5** | |
| 12 | **Go-live G.1–G.3** | Before the first paying client |

**Demo:** Wednesday 2026-11-11 shows what is built today plus steps 1 and 2, but only parts that have passed every test. Anything not fully tested by Wednesday morning is left out of the demo, not rushed in.

---

## 4. Step 1 in detail: capture and routing

### 4.1 Tables (all with `tenant_id`, forced row-level security, same-company keys)

| Table | Purpose |
| --- | --- |
| `capture_sources` | One endpoint per lead source: name, source, secret key (stored hashed), field mapping, default owner rule, consent wording, active. Websites post leads here |
| `imports` | CSV import job: uploaded by, file name, column mapping, duplicate policy, status, counts (created / updated / skipped / errors) |
| `import_rows` | One row per CSV line: raw values, result, lead id, error message. Lets the user download the failed rows |
| `lead_merges` | Who merged which lead into which, with a snapshot of the merged lead (removed with the survivor) |
| `consents` | Lead, channel (email / WhatsApp), opted in or out, source, time, evidence. Full history; the latest row is the current state |
| `suppression_list` | Channel + identifier + reason (opt-out, bounce, complaint). Not linked to a lead, so it survives deletion (#18) |
| `external_refs` | System + external ID → lead. Makes repeated form posts and API calls safe to retry |
| `assignment_rules` | Order, conditions (source, language, region, any custom field), strategy (round-robin over chosen users or a team, one user, leave unassigned), active, whose turn was last (locked per lead, so two leads arriving together never get the same turn) |
| `sla_rules` | Trigger (lead created, stage entered), within N minutes/hours, create a task, action when missed (alert the manager, reassign) |
| `lead_slas` | One running response-time clock per lead and rule: deadline, met, missed |
| `notifications` | In-app messages for a user: kind, text, link, read time |
| Settings | `duplicate_policy` (update existing (default, DM2) / flag / always create), `org_grouping` (off / suggest / auto-link domains, #14), leakage hours |

`leads` gains `possible_duplicate_of_id`, current email/WhatsApp consent, `leak_alerted_at` and dismissed organisation suggestions.

### 4.2 Rules the backend enforces

- **Duplicates (R5):** on every entry path (form, CSV, quick-add, API), match on cleaned phone or email within the company. Default: update the existing lead, keep its owner, add a "Re-enquiry" activity and reopen it if closed. Other per-company options: flag as a possible duplicate, or always create new.
- **Merge:** pick the surviving lead and, field by field, which value to keep (blanks are always filled). Phones, emails, timeline, tasks, consents and linked people move over; an opt-out on either lead wins. The other lead is deleted, a snapshot is kept with the survivor, and old links point to the survivor. Needs `leads.merge` and both leads visible.
- **Quick-add duplicates:** a person adding a lead by hand is told it already exists (with a link only if they may see it), unless the company keeps duplicates.
- **Organisation suggestions (#14):** match on the email domain, then on the company name (ignoring case, "Ltd", "Pvt" and punctuation). Free email providers never match. Off by default.
- **Consent:** forms and imports can record opt-in with time and wording. An opt-out adds the identifier to the suppression list, and that is never undone by a later import.
- **Assignment:** rules run top to bottom and the first match wins. Round-robin skips disabled users. A lead is never given to someone outside the rule's pool. Every assignment writes an activity and the `lead.assigned` event.
- **Leakage guard and SLAs:** the worker checks every minute and acts once per lead per rule. Every action is on the timeline, and the manager gets a notification.
- **Forms:** public endpoint with a per-source secret, rate-limited, hidden spam-trap field, and the same validation as quick-add. It never reveals whether a lead already exists.
- **Import:** runs in the worker, not the browser. Every row goes through the same rules as a manual add, and a bad row never stops the good ones.

### 4.3 Endpoints (under `/api/v1`)

- Capture: `capture-sources` CRUD; public `POST /capture/{source_key}`.
- Import: upload, `GET` preview, `POST` start, `GET` progress, failed-rows download.
- Leads: `GET /leads/{id}/duplicates`, `POST /leads/merge`, organisation suggestions accept/dismiss, consent get/set.
- Rules: `assignment-rules` and `sla-rules` CRUD and reorder.
- Notifications: list, mark read.

### 4.4 Screens

- Settings: Lead capture (sources with copyable form snippet), Assignment rules, SLA rules, Duplicates and grouping.
- Leads list: "Import" button with a 3-step wizard (upload → match columns → review and start, then live progress).
- Lead record: duplicate banner with "Merge", consent badges, organisation suggestion.
- A notification bell in the top bar.

### 4.5 Tests ("done" means these pass)

- **Isolation:** every new table and endpoint, across companies.
- **Duplicates:** each policy, on each entry path.
- **Merge:** what moves, what is kept, permissions.
- **Assignment:** order, conditions on custom fields, round-robin fairness when leads arrive at the same time, disabled users skipped.
- **SLAs and leakage:** each fires once, at the right time.
- **Consent and suppression:** survive deletion and import.
- **Forms:** wrong key refused, spam trap works, rate limit applies, a repeated post is not duplicated.
- **Import:** 10,000 rows, mixed good and bad.
- **Browser walk:** import a CSV → leads routed → rep notified → overdue SLA alerts the manager.

### 4.6 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| C1 | Where does the uploaded CSV live until file storage (S3) is chosen? | In the database, up to 20 MB / 50,000 rows per file; moves to the file store on our server in step 5 (Decision log #29) |
| C2 | Round-robin: equal turns, or skip people who already have many open leads? | Equal turns now; "least loaded" as a later option |
| C3 | Notifications: in-app only for now? | Yes; email copies arrive with step 8 |
| C4 | Spam protection for forms | Secret key + rate limit + hidden trap field now; captcha later if needed |

---

## 5. Step 2 in detail: records and links engine

### 5.1 Tables

| Table | Purpose |
| --- | --- |
| `record_types` | Company-defined type: fixed key (`property`), singular/plural labels, icon, has owner, has stages, which field is the name, order, active |
| `record_type_stages` | Stages for types that have them (open/closed, colour, required fields), same rules as lead stages |
| `records` | One row per record: type, name, owner, team, stage, custom fields, created by, version |
| `link_types` | Allowed link between two kinds (lead↔property, property↔record of any type…): label each way ("Interested in" / "Interested buyers"), one or many on each side |
| `links` | One row per link: link type, from, to. No duplicates; checked by the database |
| `record_type_access` | Per role and per record type: view / create / edit / delete, and scope own / team / all |

Changes to existing tables:

- `custom_field_definitions`: also used for record types (all field rules apply: required, unique, linked dropdowns).
- `activities` and `tasks`: may belong to a record instead of a lead, so every record has a timeline and tasks.

### 5.2 Rules

- **Generic types:** every record type is plain configuration. Industry packs can seed them (Real estate: Property; EdTech: Batch), but nothing in the code depends on a type's name.
- **Visibility:** the same own/team/all model as leads, per role and per type. Enforced in the backend; links never reveal a record you cannot see.
- **Links:** both ends must belong to the same company, and "one" limits are enforced (for example, a property has one developer). Deleting a record removes its links. Adding or removing a link writes an activity on both sides and emits an event.
- **Organisations:** DM1 stays: people stay leads linked to their organisation lead. The organisation page lists its people, and the organisation link can carry labels.
- **Changing a type:** a key never changes, and a type in use cannot be deleted, only switched off.

### 5.3 Screens

- Settings → Record types (fields, stages, link types, access per role).
- Each type gets a sidebar entry and the same list (paging, filters, bulk actions) and 3-column record page the leads have.
- A "Links" card on every record page to link, unlink and open linked records.

### 5.4 Tests

- **Isolation:** across companies.
- **Visibility:** per role and per type, including through links.
- **Records:** every custom-field rule on records; stages and required fields.
- **Links:** limits, both-sides timeline entries, no cross-company links.
- **Packs:** a real-estate company gets Property, an EdTech company gets Batch, from the packs only.
- **Browser walk:** create a type, add records, link them to leads.

### 5.5 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| R1 | Access per record type, set per role? | Yes, as HubSpot does: view / create / edit / delete + own/team/all |
| R2 | A limit on the number of record types per company? | None now (Decision log #6); revisit with pricing tiers |
| R3 | Should packs seed a sample type? | Yes: Property (real estate), Batch (EdTech); nothing for generic |
| R4 | Deleting a record | Permanent after a warning, like leads (#18); links and timeline removed |

---

## 6. Step 3 in detail: deals and pipelines

A deal is one sale to one lead (person or organisation): "Riya — Data Science course", "Mehta family — Flat 1203". A lead can have several deals at once. Names come from the labels the company already has (EdTech: "Course enrolment", "Course pipeline").

### 6.1 Tables (all with `tenant_id`, forced row-level security, same-company keys)

| Table | Purpose |
| --- | --- |
| `pipelines` | Name, order, active, default currency. A company has one or more (one per course, product, program) |
| `pipeline_stages` | Stages of one pipeline: name, order, colour, win probability %, required fields, and kind: open / won / lost. Each pipeline keeps at least one open, one won and one lost stage |
| `deals` | Name, lead (required), pipeline, stage, status (open / won / lost), owner, team, amount in minor units + currency code (rule 7), expected close date, closed at, lost reason, close note, custom fields, created by, version |
| `lost_reasons` | The company's list of lost reasons (editable, can be switched off, never deleted once used) |
| `products` | Catalogue: name, code, description, price in minor units + currency, active. EdTech pack seeds sample courses |
| `deal_products` | Lines on a deal: product, quantity, unit price (copied from the catalogue, editable), discount, line total. When a deal has lines, its amount is their sum |

Changes to existing tables (all through a migration):

- `activities` and `tasks` gain `deal_id`. Deal activities are written with the lead too, so they show on the lead's timeline (rule 5) and can be filtered to one deal.
- `link_types` / `links` can have a deal at either end, so a deal links to a Property or Batch like any other record (D1).
- `tenant_settings` gains `default_currency` (ISO 4217, set from the country: INR for India).
- Custom fields: entity `deal`, with every existing field rule (required, unique, linked dropdowns).
- New permissions: `deals.create`, `deals.edit`, `deals.delete`. Pipelines, stages, lost reasons and products are set up under `crm.configure`. Defaults: Admin all; Sales Manager create + edit; Sales User create + edit; Finance none (it gets read access with money in step 6).

### 6.2 Rules the backend enforces

- **Visibility:** the same own / team / all scope as leads. A rep sees their own deals; a manager sees the team's. Visibility follows the deal's own owner and team (not the lead's), and creating a deal needs sight of the lead.
- **Stages:** moving to a stage checks its required fields. Moving to won needs no extra input; moving to lost needs a lost reason (spec: "mandatory on close") and allows a note. Reopening a won/lost deal clears closed-at and the reason, and is logged.
- **Money:** amounts are integers in minor units with a currency; no floats anywhere. Each pipeline has one currency; a deal's products must be in it (no mixing currencies on one deal). Discounts and totals are computed exactly and tested.
- **Timeline and events:** create, stage change, amount change, won, lost and reopen each write an activity on the lead and the deal; `deal.won` / `deal.lost` are already in the event catalogue, and `deal.created`, `deal.updated`, `deal.stage_changed` are added.
- **Forecast numbers** (for the board header and later dashboards): open value and weighted value (amount × stage probability), per stage and per pipeline, computed in the database, respecting visibility.
- **Deleting:** pipelines in use can only be switched off; a stage with deals asks where to move them first; a deal is deleted permanently after a warning (#18).
- **Won deal → customer:** marked on the lead now ("has a won deal"); the actual customer record arrives in step 5.

### 6.3 Endpoints (under `/api/v1`)

- `pipelines` CRUD + order; `pipelines/{id}/stages` CRUD + order; `lost-reasons` CRUD; `products` CRUD.
- `deals`: list (filters: pipeline, stage, status, owner, lead, expected close range, custom fields; sort; paging), create, get, patch (with version), delete, bulk (owner / stage), `deals/{id}/move` (stage + lost reason), `deals/{id}/products` lines.
- `deals/board?pipeline=` (stages with cards and per-stage totals) and `deals/summary` (forecast numbers).
- `deals/{id}/activities`, notes and tasks reuse the existing timeline and task endpoints.

### 6.4 Screens

- Sidebar: **Deals** (company label). Board view (kanban, drag between stages, per-stage count and value, pipeline switcher) and a list view with the same filters.
- Dropping on a lost stage opens a small "Why was it lost?" box; dropping on a stage with required fields opens those fields.
- Deal page: same 3-column layout as leads (details and products, timeline, linked lead and records, tasks).
- Lead page: a **Deals** card with that lead's deals and "+ New deal".
- Settings → Records and fields → Deals: pipelines and stages, lost reasons, products, deal fields, rules.

### 6.5 Tests ("done" means these pass)

- **Isolation:** deals, pipelines, products across companies.
- **Visibility:** own / team / all for deals, on the board and the summary numbers too.
- **Rules:** lost needs a reason, required fields per stage, reopen, a pipeline keeping its won/lost stages, no currency mixing.
- **Money:** line totals, discounts, deal amount = sum of lines, weighted forecast, big amounts (no overflow), zero-decimal currencies (JPY) and three-decimal ones (KWD).
- **Timeline and events** for every change; concurrent edits refused by version.
- **Packs:** EdTech gets "Course pipeline" stages and sample courses; generic gets a plain sales pipeline.
- **Browser walk:** create a deal from a lead, drag it across the board, lose one with a reason, win one; rep and manager views; phone width.

### 6.6 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| D1 | Can a deal be linked to records (Property, Batch)? | Yes: deals become a third kind in the links engine (HubSpot does this), so "Mehta — Flat 1203" links to the flat |
| D2 | Must every deal belong to a lead? | Yes, one lead (person or organisation). Other people go in as links |
| D3 | One currency per pipeline? | Yes, set on the pipeline (default: the company's); different currencies need different pipelines. Keeps totals exact without exchange rates |
| D4 | Products: who sees prices, and can a rep change the price on a deal? | Everyone with deal access sees prices; reps may edit the unit price and discount on their own deal lines |
| D5 | Win probability per stage | Yes, editable per stage, used only for the weighted forecast |
| D6 | Lead stage on a win | Untouched now; in step 5 a win offers "Make customer" |

---

## 7. Step 4 in detail: tags, saved views, scoring, calculated fields, automation

Goal: the CRM runs the routine work itself. Leads sort themselves (tags, views, scores), numbers fill themselves in (calculated fields), and "when this happens, do that" needs no developer (automation, Decision log #16). Everything is company configuration; nothing is tied to an industry.

### 7.1 Tables (all with `tenant_id`, forced row-level security, same-company keys)

| Table | Purpose |
| --- | --- |
| `tags` | The company's tags: name, colour. Unique per company |
| `taggings` | One tag on one lead or one deal (database checks exactly one; no duplicates) |
| `saved_views` | A saved filter: what it lists (leads / deals), name, filters, sort, columns, who sees it (just me / my team / everyone), owner, order |
| `score_rules` | Points rules. **Fit:** "source is Website +10", "city is Pune +5", any field incl. custom. **Engagement:** "each Call with outcome Interested +15", "each note +2", counted over the last N days |
| `automations` | Name, on/off, what it watches (leads or deals), WHEN (trigger), IF (conditions), THEN (ordered actions), order |
| `automation_runs` | One row per run: automation, the event, the lead/deal, result (done / skipped / failed), what each action did, error text |

Changes to existing tables (through a migration):

- `leads`: `fit_score`, `engagement_score` (the existing `score` becomes their sum) and `score_band` (Hot / Warm / Cold).
- `tenant_settings`: engagement window in days (default 30) and the Hot / Warm thresholds.
- `custom_field_definitions`: new field type **Calculated**, with its formula. Works for leads, deals and every record type.
- `events`: `automation_handled_at`, so the worker processes each event once.

### 7.2 Rules the backend enforces

- **Tags:** anyone who may edit a lead or deal can tag it, and can create a new tag while doing so. Renaming, recolouring, merging and deleting tags is `crm.configure`. Tagging writes a timeline entry and `lead.updated` / `deal.updated` with `fields: ["tags"]`. Bulk tag and untag on lists, with the same skip-and-report rule as other bulk actions.
- **Saved views:** a view is filters plus sort plus columns, run live (so it is always up to date, a "smart list"). Everyone sees only what their role allows: a shared view never shows a rep someone else's leads. "Just me" for anyone; "my team" for team managers; "everyone" for `crm.configure`. Views appear as tabs on the Leads and Deals lists, with counts.
- **Scoring:** fit score recalculates whenever the lead changes; engagement score recalculates on every activity and nightly (so old activity drops out of the window). Score bands come from the company's thresholds. The lead page shows the breakdown ("+10 source Website, +15 call Interested"). ACE intent (hot/warm from conversations) stays a separate field.
- **Calculated fields:** formulas on numbers and dates only: `+ − × ÷`, brackets, `round()`, `days_between()`, `today()`, and a default when a field is empty. Read-only; recalculated on every save and nightly (for `today()`). Parsed by our own small safe parser, never `eval`. Money fields stay exact (integer arithmetic, rounded half up once at the end). Cycles (A uses B uses A) are refused when the field is saved.
- **Automation (WHEN / IF / THEN):**
  - **WHEN:** lead created, lead stage changed, a field changed (pick the field), activity logged (pick the type and outcome), task overdue, no response within X hours, deal created, deal stage changed, deal won, deal lost.
  - **IF:** any field, built-in or custom, with is / is not / is any of / contains / is empty / is not empty / more than / less than; tags (has / has not); owner; score band. All conditions must match.
  - **THEN (in order):** create a task (title, due in X hours, for the owner or a named person), update a field, add or remove a tag, change owner (a person, or "by assignment rules"), change stage, send an in-app notification, send a webhook (signed POST, 3 retries).
  - **How it runs:** the worker reads new events within seconds, runs matching automations in the company's own session, and writes `automation_runs`. Time-based triggers (overdue, no response) are checked every minute. Actions are done by "Automation: <name>" on the timeline, follow every normal rule (required fields, stage rules, lost needs a reason), and a failed action stops that run and is shown in the run history.
  - **Loop guard:** an automation's own changes can trigger other automations up to 3 levels deep; the same automation never runs twice for the same lead from one chain. A broken automation that keeps failing is switched off after 20 failures in a row, with a notification to admins.
- **Permissions:** automations, scoring rules and calculated fields are set up under `crm.configure`. No new permission codes.
- **Events:** no new event types; tags and score changes use the existing `lead.updated` / `deal.updated`.

### 7.3 Endpoints (under `/api/v1`)

- `tags` CRUD + merge; `leads/{id}/tags`, `deals/{id}/tags` (set); bulk tag/untag in `/leads/bulk` and `/deals/bulk`; `tag` filter on lead and deal lists.
- `views` CRUD + order (`?entity=leads|deals`), with counts.
- `score-rules` CRUD; `crm-rules` gains the scoring window and thresholds; `leads/{id}/score` (breakdown); recalculate-all after rules change (worker job).
- Custom fields accept type `calculated` with a `formula`; a `formula/check` endpoint validates and previews a formula.
- `automations` CRUD + order + on/off; `automations/{id}/runs`; `automations/{id}/test` (shows which conditions match a chosen lead, changes nothing).

### 7.4 Screens

- **Leads and Deals lists:** view tabs (Mine, Overdue… plus saved views), "Save view" after filtering, tag column and tag filter, bulk Tag.
- **Lead and deal pages:** tags in the header (add / remove inline); score and band on the lead with a breakdown on click.
- **Settings → Records and fields → Leads:** a new **Scoring** tab (rules + thresholds). **Tags** gets its own small page under Records and fields.
- **Field dialog:** new type "Calculated" with a formula box, live preview and the list of fields you can use.
- **Settings → Automation** (new group): list with on/off and last run; builder with WHEN / IF / THEN in plain sentences; run history per automation; "Test on a lead".

### 7.5 Tests ("done" means these pass)

- **Isolation:** tags, views, rules, automations and runs across companies; an automation never touches another company.
- **Visibility:** a shared view shows each person only what they may see; automation-made changes respect the record's rules.
- **Scoring:** fit and engagement rules, window drop-off, bands, recalculation after a rule change.
- **Formulas:** parser (precedence, brackets, division by zero, empty fields, dates), cycle refusal, money stays exact, malicious input refused.
- **Automation:** each trigger, each condition operator, each action; order of actions; a failing action; loop guard and depth; auto switch-off; time-based triggers; webhook signature and retries.
- **Browser walk:** tag leads in bulk, save and share a view, set scoring and watch a score change, build "When a lead is created from Website, assign by rules and create a call task in 1 hour", see it run.

### 7.6 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| A1 | Separate static lists, or tags + saved views? | Tags + saved views cover it (a "list" = a tag, or a saved view). Revisit in step 9 if sequence enrolment needs fixed lists |
| A2 | What can be tagged? | Leads and deals now; records later if asked |
| A3 | Who creates tags? | Anyone who edits leads/deals creates them while tagging; admins tidy (rename, merge, delete) |
| A4 | Who can share views? | Anyone: just me. Team managers: my team. `crm.configure`: everyone |
| A5 | Score shape | Fit + engagement (last 30 days, editable), bands Hot / Warm / Cold with editable thresholds; ACE intent stays separate |
| A6 | Formula scope | Numbers and dates only for now (no text formulas) |
| A7 | Automations on records (Property, Batch)? | Leads and deals now; record triggers later if asked |
| A8 | "Wait 2 days, then…" delays in automations | Not now (not in #16); comes with sequences in step 9 |
| A9 | Webhook action before step 11 | Yes, a simple signed POST with retries now; full webhook management (logs, secrets per endpoint) in step 11 |

---

## 8. Step 5 in detail: customers and documents

Goal: a won deal turns into a customer without losing anything, and the paperwork that follows (registration details, ID proofs, signed forms, photos) is collected, checked and filed per customer. Files live on our own server (Decision log #29). Money (step 6) then hangs invoices off the customer. Everything is company configuration: "Customer" is a label ("Student", "Buyer", "Client", "Applicant"), and the checklist is whatever each company needs.

### 8.1 How a customer works

- **A customer is a lead that became a customer.** It keeps the same record and the same timeline: every call, note, deal and task stays where it was. A `customers` row holds what is new: customer number, since when, status and customer-only fields.
- **Becoming a customer:** "Make customer" on a won deal (offered right after the win), or on the lead page. A lead becomes a customer once; later wins add to the same customer.
- **Customer status:** Active / Inactive (a company can rename; no deletions while money exists, from step 6).
- **The customer page is the lead page with more on it:** a Customer card (number, since, status, fields), the document checklist and the registration link. No second page to keep in step.
- **Who sees customers:** the same rules as leads (owner, team, everyone). A role that reads customers but does not work leads (Finance) sees every customer, read-only, and still no leads or deals (as agreed in Decision log #21).

### 8.2 Documents

- **Checklist (per company):** each item has a name (Aadhaar, Passport, 10th marksheet, Signed agreement), required or optional, accepted file types, and whether it applies to every customer or only when a deal includes certain products (e.g. "Visa documents" only for the Study Abroad course).
- **Each customer's checklist** shows every item as Pending → Received → Verified, or Rejected with a reason (which asks for a new upload).
- **Uploads:** staff upload on the customer page; the customer uploads through the secure link (8.3). More than one file per item is allowed (front and back of an ID). Extra files that are not on the checklist go under "Other documents".
- **Verifying:** a new permission `documents.verify` (default: Admin, Sales Manager). Every upload, verify, reject and delete writes an activity on the timeline and an audit entry.
- **Viewing:** images and PDFs preview in the browser; everything else downloads. Every view and download goes through Core after a company + permission check.

### 8.3 ~~Registration and document link~~ Removed (Decision log #33)

Customers do not upload anything into Core. Only staff upload documents and enter customer details; managers verify. The secure link, its page and its settings were built and then removed before release (migration 0016).

### 8.4 Files on our server (Decision log #29)

- One storage module saves and reads every file: `FILES_DIR/<company-id>/<year>/<month>/<random-name>`. Postgres keeps the record (original name, size, type, checksum, who uploaded, what it belongs to).
- **Limits:** 10 MB per file; **2 GB per company included**, more as a paid add-on (Decision log #32). Photos are shrunk in the browser before upload (about 2000 px, good quality); PDFs are untouched. Settings shows usage, with a warning at 80%. Allowed: PDF, JPG, PNG, WEBP, HEIC; Word and Excel only if the checklist item allows them. The real file type is checked from its contents, not just the name.
- **Safety:** files are never served straight from the folder; they are sent with "download" headers so a file cannot run as a web page. A half-finished upload leaves nothing behind (saved to a temporary name, then moved). A nightly job removes files that lost their record and flags records whose file is missing.
- **Backups:** the nightly backup (go-live, step 12) must include the files folder. On your Mac the folder is `backend/var/files/` and is kept out of git.

### 8.5 Tables (all with `tenant_id`, forced row-level security, same-company keys)

| Table | Purpose |
| --- | --- |
| `customers` | One per lead (unique): customer number (per company, e.g. C-0001), since, status, customer fields, the deal that made them a customer |
| `files` | Every stored file: path, original name, size, type, checksum, uploaded by (a person, or "the customer via link"), uploaded at |
| `document_requirements` | The company's checklist items: name, required, accepted types, applies to all or to chosen products, order, active |
| `documents` | One checklist item for one customer: status (pending / received / verified / rejected), reject reason, verified by / at; links to its files |
| `document_files` | Which files belong to which document (several per item); "Other documents" have no checklist item |
| `form_links` | Secure links: customer, code hash, which fields to ask, expires at, cancelled at, submitted at, created by |

Changes to existing tables (through a migration):

- `custom_field_definitions`: entity `customer` (customer-only fields, e.g. "Admission number", "Passport number").
- `tenant_settings`: link validity in days (default 14), customer number prefix (default "C-").
- New permissions: `customers.create` (make customer), `documents.verify`; Finance gets read on customers and documents.
- New activity types: Became customer, Document uploaded, Document verified, Document rejected, Submitted by the customer.

### 8.6 Rules the backend enforces

- Only a lead the person can see and edit can be made a customer; once only.
- Uploads: size, type (by content) and company quota checked before saving; the record is written only after the file is safely on disk.
- A rejected document needs a reason; verifying needs `documents.verify`; only signed-in staff upload (#33).
- Merging two leads moves customers' documents with them (if both are customers, the merge is refused with a clear message).
- A lead that is a customer cannot be deleted (it will hold invoices from step 6); it can be set Inactive.
- **Events:** `customer.created` and `document.received` (already in the catalogue), plus new `document.verified` and `document.rejected`. Automations get two new triggers: "becomes a customer" and "document received".

### 8.7 Endpoints (under `/api/v1`)

- `POST /leads/{id}/customer` (make customer), `GET/PATCH /customers/{id}`, `GET /customers` (list, filters, saved views reuse the leads engine).
- `GET/POST/PATCH/DELETE /document-requirements`, `PUT /document-requirements/order`.
- `GET /customers/{id}/documents`; `POST /customers/{id}/documents/{doc_id}/files` (upload); `POST …/verify`; `POST …/reject`; `DELETE /files/{id}`; `GET /files/{id}` (view or download after checks).
- `POST /customers/{id}/links`, `DELETE /links/{id}`; public (no login): `GET /public/links/{code}`, `POST /public/links/{code}/files`, `POST /public/links/{code}/submit`.
- Settings: link validity and number prefix in the existing settings endpoint.

### 8.8 Screens

- **Customers** in the sidebar (company label, e.g. "Enrolled students", "Buyers"): list with number, name, since, owner, documents done (e.g. 3 of 5), status; filters and saved views like the leads list.
- **Customer page** (the lead page): Customer card; Documents card with the checklist, upload by drag-and-drop or the phone camera, preview, verify / reject; "Send registration link" with Copy and Open in WhatsApp.
- **Won deal:** "Make customer" right after the win.
- **The customer's page** (public link): company name and colour, the fields to fill, each pending document with an upload button; works well on a phone; a clear "All done, thank you" at the end.
- **Settings → Records → Customer:** customer fields, the document checklist, link validity, number prefix.

### 8.9 Tests ("done" means these pass)

- **Isolation:** customers, documents, files and links across companies; a file from company A can never be read with company B's session or link, even with its id.
- **Visibility:** a rep sees only their customers' documents; Finance reads but cannot verify; verify needs `documents.verify`.
- **Files:** size, type by content (a renamed .exe is refused), quota, half-finished upload leaves nothing, nightly clean-up, download headers.
- **Links:** expired, cancelled, already submitted and wrong codes are refused; rate limit; a link reaches only its own customer and pending items.
- **Conversion:** once only, keeps the timeline, numbering per company, merge and delete rules, events and automation triggers.
- **Browser walk:** win a deal → make customer → send the link → open it on a phone, fill fields and upload → owner sees it → manager verifies one and rejects one with a reason → customer re-uploads.

### 8.10 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| E1 | A separate customer record, or the lead page with customer parts? | The lead page with customer parts (one record, one timeline, nothing to keep in step) |
| E2 | Can a lead become a customer without a won deal? | Yes, from the lead page (e.g. walk-in admissions, old customers being imported) |
| E3 | Checklist per product, or one for everyone? | Both: each item applies to everyone or only to chosen products |
| E4 | Who verifies documents? | New `documents.verify`; default Admin and Sales Manager; companies change it in Roles |
| E5 | How does the customer get the link before email/WhatsApp exist? | ~~Copy link + WhatsApp share~~ No customer link at all: staff upload (#33) |
| E6 | Link validity | ~~14 days~~ No customer link (#33) |
| E7 | File limits | 10 MB per file, **2 GB per company, extra storage paid** (#32); photos shrunk in the browser; PDF and images always, Word/Excel only where an item allows them |
| E8 | Reminders for missing documents | In-app now: owner gets a task when documents are still pending after N days (default 3). Message reminders come with sequences (step 9) |
| E9 | A "File" custom field type (attach a file to any field) | Not now; the documents checklist covers it. Add later if asked |
| E10 | Deleting files and old documents (data protection) | Only Admin deletes; every delete is in the audit log. Retention rules (auto-delete after X years) with the security work in step 11 |

---

## 9. Step 6 in detail: money

Goal: after a sale, the team bills the customer, collects by payment link or bank transfer, and always knows what is paid, due and overdue, without a spreadsheet. Rule 7 throughout: every amount is a whole number in minor units (paise, fils, cents) with its currency code; no floats anywhere, in the database, the API or the screens. The `money` module switch (built in phase 1, off by default) turns this on per company.

### 9.1 How money works

- **Billing entity:** the legal company that issues the invoice (e.g. "Acme Learning Pvt Ltd, India, INR, GSTIN …" and "Acme FZ-LLC, Dubai, AED, TRN …"). A company has one or more; any country and any currency (Decision log #2). Each entity has its own invoice and receipt numbering, tax ids, address, bank details printed on invoices, and its own gateway account.
- **Invoice:** belongs to one customer (and usually the deal it came from), one entity, one currency. Lines come from the deal's products (editable) or are typed. **Draft** (editable, no number) → **Issued** (gets the next number, locked) → **Partly paid** → **Paid**. An issued invoice is never deleted or edited; it is **Voided** with a reason (the number stays used, as tax law expects).
- **Taxes:** the company keeps a list of tax rates, each made of parts (e.g. "GST 18%" = CGST 9% + SGST 9%; "IGST 18%"; "VAT 5%"; "No tax"). Each line picks one. Tax is worked out per line and rounded half-up to the minor unit; the invoice shows each part. No country rules in code: India, UAE and US are just different rate lists in the industry packs.
- **Installment plan:** an invoice can be split into installments, each an amount and a due date. The installments must add up to the invoice total exactly (checked by the backend). An invoice with no plan has one installment: the total, due on its due date.
- **Payment:** money received against one invoice — by gateway (automatic) or manually (bank transfer, cash, cheque, UPI) with proof attached (spec rule). A payment is applied to the oldest unpaid installment first. A payment larger than the balance is refused (credit notes and refunds come later). A wrong manual payment is reversed with a reason, never deleted.
- **Balance:** per invoice and per customer, per currency: total, paid, due, overdue. Currencies are never added together.
- **Receipt:** every payment gets a receipt number (per entity) and a receipt page/PDF.

### 9.2 Payment links and gateways

- Each entity connects its own **Razorpay** (India) or **Stripe** (UAE/US and others) account in Settings; keys are stored encrypted, never shown again in full.
- "Send payment link" on an installment (or the whole balance) creates a link on the gateway's own hosted payment page. **The customer pays on Razorpay's / Stripe's page, not on ours** — nothing of ours is open to the public except the gateway webhook address (#33 still holds: customers send nothing into Core).
- The link is copied or opened in WhatsApp (as with other links before step 9/10 exist).
- **Gateway webhooks** mark the installment paid: the signature is checked, the gateway's payment id makes a repeated webhook harmless, and the amount and currency must match. A nightly check asks the gateway about links still open, in case a webhook was missed.
- No gateway connected yet? Everything else works; payments are recorded manually.
- **Two ways to pay, chosen per invoice:** when issuing, the user ticks **Payment link** (Razorpay / Stripe, marked paid automatically) and/or **Pay directly** (the invoice PDF shows the entity's bank details and a UPI QR with the exact amount and invoice number filled in; free, no gateway fee; staff mark it paid with proof, like any bank transfer). The company sets the default; the user can change it on each invoice. An invoice can carry both.
- **One gateway module:** all gateway calls go through one module (like file storage), so another provider — e.g. an open-source orchestrator such as Hyperswitch, still under research — can be added later without touching invoices or payments.

### 9.3 Reminders, receipts, aging

- **Reminders (in-app now):** N days before due (default 3), on the due day, and every N days while overdue (default 7): the customer's owner gets a notification and a task; Finance sees the overdue list. Events `payment.due` and `payment.overdue` fire so automations and later email (step 9) / WhatsApp (step 10) can send to the customer.
- **Receipts:** made on every payment, in-app now, sent by email from step 9.
- **Collections aging:** overdue amounts in 0–30 / 31–60 / 61–90 / 90+ days, per entity and currency, with a list behind each bucket; the dashboard tile comes in step 7.

### 9.4 Tables (all with `tenant_id`, forced row-level security, same-company keys)

| Table | Purpose |
| --- | --- |
| `billing_entities` | Legal name, country, currency, tax ids, address, bank details, invoice prefix and next number, receipt prefix and next number, number reset each financial year (yes/no, start month), active |
| `tax_rates` | Name, parts (name + rate in basis points, e.g. 900 = 9%), active, order |
| `invoices` | Customer, deal (optional), entity, currency, number (null while draft), status, issue date, due date, notes, totals (subtotal, discount, tax, total — minor units), void reason, created by |
| `invoice_lines` | Product (optional), description, quantity, unit price, discount, tax rate (copied at issue so later rate changes never change old invoices), line totals (checked by the database) |
| `installments` | Invoice, position, amount, due date, paid amount, status (due / partly paid / paid / overdue — worked out, not typed) |
| `payments` | Invoice, entity, amount, currency, method (gateway / bank / cash / cheque / UPI / other), paid on, reference, gateway payment id (unique), proof file, receipt number, recorded by, reversed (by, at, reason) |
| `payment_allocations` | Which part of a payment went to which installment |
| `payment_links` | Installment (or invoice), gateway, gateway link id, amount, status, url, expires at |
| `gateway_accounts` | Entity, gateway, keys (encrypted), webhook secret (encrypted), mode (test / live) |
| `gateway_events` | Every webhook received: gateway, event id (unique), payload, result — for safe retries and support |

Changes to existing tables: `tenant_settings` gets reminder days (before / overdue repeat). New permissions: `invoices.read`, `invoices.create`, `invoices.void`, `payments.record`, `payments.reverse`, `money.settings`. New activity types: Invoice issued, Invoice voided, Payment received, Payment reversed, Payment link sent. Industry packs get tax rates and a starting entity (India GST for EdTech; generic gets "No tax").

### 9.5 Rules the backend enforces

- Every sum is integer arithmetic; line total = quantity × unit price − discount; tax per line rounded half-up; invoice total = sum of lines; installments add up to the total exactly; allocations add up to the payment exactly. All checked again by the database where possible.
- Numbering is gapless per entity (locked row, like customer numbers); voided numbers stay used.
- Issued invoices and recorded payments never change; only void / reverse with a reason. Every action is an activity on the customer's timeline and in the audit log.
- Visibility follows customers: a rep sees invoices of customers they can see; Finance sees all money and no leads (Decision log #21, #32).
- A customer with any issued invoice cannot be set Inactive while money is due (it shows why).
- Gateway webhooks: signature checked, duplicates ignored, amount/currency mismatch flagged for Finance instead of applied.
- **Events:** `invoice.created` (on issue), `payment.received`, `payment.due`, `payment.overdue` (already in the catalogue), plus new `invoice.voided` and `payment.reversed`. Automation triggers: invoice issued, payment received, payment overdue.

### 9.6 Endpoints (under `/api/v1`)

- Entities, tax rates, gateway accounts: CRUD under Settings (`money.settings`).
- `GET /invoices` (filters: status, entity, customer, owner, overdue, dates), `POST /invoices` (draft, optionally from a deal), `GET/PATCH /invoices/{id}` (draft only), `POST /invoices/{id}/issue`, `POST /invoices/{id}/void`, `PUT /invoices/{id}/installments`, `GET /invoices/{id}/pdf`.
- `POST /invoices/{id}/payments` (manual, with proof upload), `POST /payments/{id}/reverse`, `GET /payments`, `GET /payments/{id}/receipt`.
- `POST /installments/{id}/payment-link`, `DELETE /payment-links/{id}`.
- Public, no login: `POST /webhooks/razorpay/{entity}`, `POST /webhooks/stripe/{entity}` (signature-checked only).
- `GET /customers/{id}/balance`, `GET /money/aging`.

### 9.7 Screens

- **Money** in the sidebar (Finance, Admin, Owner; reps see it for their own customers): tabs Invoices, Payments, Overdue, Aging.
- **Customer / lead page:** a Money card — balance per currency, invoices, next installment due, "New invoice", "Record payment", "Send payment link".
- **Won deal:** "Create invoice" next to "Make customer", lines pre-filled from the deal.
- **Invoice editor:** lines, tax per line, live totals, installment schedule (split equally / custom), preview, Issue.
- **Invoice page and PDF:** entity details, customer, lines, tax parts, totals, installments, bank details, payment link.
- **Settings → Money:** billing entities, numbering, tax rates, gateways (connect, test, webhook address to paste), reminder days.

### 9.8 Tests ("done" means these pass)

- **Every money calculation** (rule 7): line totals, discounts, tax rounding, multi-part tax, invoice totals, installment splits (e.g. ₹10,000 in 3 = 3,333.34 + 3,333.33 + 3,333.33), allocations across installments, partial payments, balances per currency, aging buckets, zero-decimal and three-decimal currencies (JPY, KWD).
- **Isolation and visibility:** invoices, payments, links, gateway keys across companies; a webhook for company A can never touch company B; reps only their customers; Finance everything, read and record.
- **Lifecycle:** draft edits, issue numbering (gapless under parallel issues), void, reverse, locked issued invoices, inactive-with-dues rule.
- **Gateways (no real money):** signed test webhooks for Razorpay and Stripe — valid, bad signature, repeated, wrong amount, unknown link; the missed-webhook nightly check with a fake gateway.
- **Browser walk:** win a deal → make customer → create invoice from the deal → 3 installments → issue → PDF → record a bank transfer with proof → balance updates → payment link created (test mode) → simulated webhook marks it paid → receipt → move a due date into the past → overdue reminder and aging.

### 9.9 Open questions

Answered 2026-11-12 (Decision log #34): all as recommended. Added: emails to the customer (invoice, receipt, reminders, cancellation) from the company's own mailbox in step 6, and a "Send on WhatsApp" button; automatic WhatsApp in step 10.


| # | Question | Recommendation |
| --- | --- | --- |
| M1 | Invoice PDFs need a PDF library (new dependency) | Approve **`reportlab`** (BSD licence, pure Python, no system packages). The alternative is a print-ready invoice page saved as PDF from the browser, but then emails in step 9 cannot attach it |
| M2 | Talking to Razorpay / Stripe needs an HTTP client in production | Move **`httpx`** from dev-only to the main dependencies (already used by the automation webhook action, which today only works because the dev tools are installed — a gap worth closing anyway). No Razorpay / Stripe SDKs: direct, small calls |
| M3 | Who can create invoices and record payments? | Reps: create and issue invoices and send links for their own customers; record manual payments with proof. Finance: everything, including void and reverse. Sales Manager: their team's. Changeable in Roles |
| M4 | Discount and special-plan approval (spec: "if the admin requires approval") | Not in step 6. Add later as an optional setting if a client asks |
| M5 | Overpayments, refunds, credit notes | Refuse overpayment now; credit notes and refunds later (with bank-statement import) |
| M6 | Recurring invoices (SaaS / retainers, spec "recurring billing") | Include a simple **repeat** on an invoice: every 1 / 3 / 12 months, creates the next issued invoice on schedule. Keeps Core fit for B2B SaaS without subscriptions logic |
| M7 | Number reset each financial year (India: April) | Per entity setting, on by default for India packs (e.g. INV/2026-27/0001) |
| M8 | Demo data | Acme (India, INR, GST 18%) and Bluewave (Dubai, AED, VAT 5%) get invoices at every state: paid, partly paid, due soon, overdue 0–90+ days; gateways in test mode only |
| M10 | UPI QR on the invoice needs a QR-code library (new dependency) | ~~Approve `segno`~~ Not needed: `reportlab` draws QR codes itself (#34) |
| M11 | Open-source gateways | Researched: Hyperswitch (Apache 2.0) is a router that still needs Razorpay / Stripe underneath; running a gateway that holds clients' money needs an RBI payment-aggregator licence (₹15 crore net worth at application). Not in step 6; can plug into the gateway module later |
| M9 | Real gateway test | Built and tested with signed fake webhooks; a real test-mode run needs your Razorpay / Stripe **test** keys, entered in Settings (never in code). Can be done any time after |

---

## 10. Step 7 in detail: dashboards and CSV export

Goal: everyone opens Core and sees how they, their team or the business is doing, from first enquiry to money in the bank, and can take any list out as a CSV file. Every number comes from data already in Core (steps 1–6); nothing is typed in twice. Every number obeys the same visibility as the lists (a rep's numbers never count other reps' leads), and every number can be clicked to open the list behind it.

### 10.1 The dashboards (spec §9)

One **Dashboards** page in the sidebar with a tab per view; each person sees only the tabs their role allows. Team, Business and Money are permissions (`dashboards.team`, `dashboards.business`, `dashboards.money`) the admin can give or take per role (Decision log #35).

| Tab | Who | Shows |
| --- | --- | --- |
| **My numbers** | Everyone who works leads | New leads assigned, follow-ups done / due / overdue, calls logged, my open pipeline (value and weighted), deals won (count, value), my customers' collections and overdue, today's summary |
| **Team** | Sales Managers (their team), Owner / Admin (everyone) | Funnel (leads → contacted → qualified → deal → won), source performance (leads, conversion %, won value per source), rep leaderboard (calls, leads worked, deals won, value, collections), leakage (leads not touched in time), response-time (SLA) breaches, lost reasons |
| **Business** | Owner / Admin | Booked revenue (won deals), collected money, overdue, new customers, pipeline forecast (weighted), conversion trend by month. Email / WhatsApp performance joins in steps 9–10 |
| **Money** | Finance, Owner / Admin | Invoiced, collected, due, overdue; aging (0–30 / 31–60 / 61–90 / 90+); collections per billing entity and per payment method; upcoming dues (next 30 days); customers with the most overdue |

- **Period:** today, this week, this month (default), last month, this quarter, this year, or chosen dates; each number shows the change against the period before. Dates follow the company's time zone.
- **Filters:** team, owner, source, pipeline, billing entity (where they apply).
- **Money is never added across currencies:** each currency gets its own figures.
- **Click-through:** every number opens the matching list (leads, deals, customers, invoices) with those filters already applied.
- **My Day stays the rep's home page**, with a small strip of their key numbers linking to "My numbers".

### 10.2 CSV export (spec §10 "Import / export, CSV both ways")

- An **Export** button on the Leads, Deals, Customers, Invoices and Payments lists: it exports exactly what the list shows (same filters, search and saved view) with the columns shown, plus custom fields.
- Only records the person may see; amounts as plain numbers with a currency column; dates in the company's time zone.
- One permission per list, **`leads.export`, `deals.export`, `customers.export`, `invoices.export`** (invoices and payments). Default: Owner and Admin only; the admin grants them to any role in Roles (Decision log #35). Every export is in the audit log (who, which list, how many rows) and Owners / Admins get an in-app alert.
- Safe to open in Excel: a cell starting with `=`, `+`, `-` or `@` is written so it can never run as a formula.
- Up to 50,000 rows downloaded straight away; bigger exports later through the worker.

### 10.3 How the numbers are worked out

- Live from the existing tables, using the company's activity, deal, invoice and payment records; no new tables. Indexes are added where a dashboard query needs one.
- Definitions written down once and shown on hover ("Converted = became a customer in this period"), so every screen means the same thing.
- If dashboards get slow for very large companies, nightly summaries can be added later without changing the screens.

### 10.4 Endpoints (under `/api/v1`)

- `GET /dashboards/me`, `GET /dashboards/team`, `GET /dashboards/business`, `GET /dashboards/money` — each with `period` / `from` / `to` and the filters; each answers only with what the caller may see (403 for a tab the role lacks).
- `GET /leads/export`, `/deals/export`, `/customers/export`, `/invoices/export`, `/payments/export` — the same query parameters as each list, answering a CSV file.

### 10.5 Screens

- **Dashboards** page: tabs, period and filter bar, number tiles with the change, and simple charts (bars for the funnel, sources and aging; a line for the monthly trend; a table for the leaderboard). Works on a phone.
- **Export** button on the five lists.
- **My Day:** a strip of the rep's key numbers.

### 10.6 Tests ("done" means these pass)

- Every number checked against a hand-built set of leads, activities, deals, invoices and payments, including period edges (midnight in the company's time zone, month ends).
- Visibility: a rep's numbers only count their own records; a manager's only their team; Finance sees money and no lead numbers; another company's data never appears.
- Money: never summed across currencies; matches the step 6 balances and aging exactly.
- Export: the same rows as the list, permission and audit, formula-safe cells, custom fields, 50,000-row limit.
- Browser walk: each role opens their tabs, changes the period, clicks a number into its list, exports a CSV.

### 10.7 Open questions

Answered 2026-11-12 (Decision log #35): all as recommended, except R4 (export per list, admin decides, default Owner / Admin only).


| # | Question | Recommendation |
| --- | --- | --- |
| R1 | Charts need a chart library? | **No new library:** simple bars and lines drawn by Core itself (enough for these views, nothing to install). A library (e.g. Recharts) only if you later want rich interactive charts |
| R2 | Where do dashboards live? | One **Dashboards** page with role tabs; My Day stays the rep's home with a small numbers strip |
| R3 | Default period and week start | This month; weeks start on Monday; company time zone |
| R4 | Who may export? | ~~One `data.export`~~ **Decision log #35:** one permission per list (`leads.export`, `deals.export`, `customers.export`, `invoices.export`); default Owner and Admin only; the admin grants it to any role in Roles; every export is audited and Owners / Admins get an in-app alert |
| R5 | "Revenue" means? | Show both: **booked** (won deal value) and **collected** (payments received), side by side |
| R6 | Build-your-own reports, scheduled email of dashboards | Later (spec: custom reports "Later"); email of reports once email exists (step 9) |
| R7 | Different dashboards per industry | Same dashboards for everyone, in each company's own words (Student / Buyer / Client); per-industry dashboard layouts later if needed |

---

## 11. B2B / SaaS demo company, then step 7b: key accounts add-on

### 11.1 The B2B demo company (built first, so 7b has real-looking data)

- **A new industry pack `b2b_saas`** (configuration only, rule 2): words Prospect / Opportunity / Client; lead stages New → Contacted → Discovery call → Qualified → Nurture / Unqualified; pipeline Discovery → Demo → Proposal → Negotiation → Won / Lost with win %; sources Website, LinkedIn, Referral, Event, Outbound, Partner; fields company size, industry, seats, current tool, decision timeline; lost reasons (price, chose competitor, no budget, timing); products with per-seat yearly prices and a one-time implementation fee; documents (signed MSA, purchase order, GST certificate); GST 18%.
- **Demo company "Brightlane Software"** (invented, India, INR, sells an HR and payroll suite): about 150 prospects across invented client companies, reps and a manager, opportunities at every stage, won deals that became clients, yearly and quarterly repeat invoices, some overdue, documents collected. Its own login like Acme and Bluewave.
- No real company or brand names anywhere in demo data.

### 11.2 Step 7b: key accounts (Decision log #31)

For companies that sell to large organisations over months. An add-on: a module switch (off by default, on for Brightlane), so EdTech and real-estate companies never see it and nothing in Core changes for them.

| Part | What it is | Built on |
| --- | --- | --- |
| **Key account** | An organisation marked as key: tier (strategic / growth / maintain), account owner, yearly target, health (on track / at risk / off track) | Organisations (step 1) |
| **Group tree** | Parent and subsidiaries (Varanta Group → Varanta Motors, Varanta Retail); won, pipeline and collected roll up the tree, per currency | New parent link |
| **Budget holders** | The departments that buy (HR, Finance, IT), each with its budget holder (a contact) | Contacts on the organisation |
| **Opportunity grid** | Departments × products: each cell shows Won / In progress / Lost from real deals, or "With competitor X" / "Not a fit" set by the rep; click a cell to open its deals or start one | Deals + products (step 3) |
| **Competitors** | The company's list of competitors; each grid cell can name who holds it today | New small list |
| **People map** | Each contact's role (decision maker / influencer / user / gatekeeper), stance (champion / supporter / neutral / blocker) and strength, with their last touch from the timeline | Contacts + activities |
| **Account plan** | Goals (with target amount and date) and next actions (tasks), reviewed on the account page | Tasks (step 1) |

- **Screens:** "Key accounts" in the sidebar (list with tier, owner, target vs won this year, pipeline, health); an account page with tabs Overview (roll-ups, plan), Opportunity grid, People map, Group tree.
- **Rules:** account visibility follows the organisation's (owner / team / all); new permission `key_accounts.manage` (default Owner, Admin, Sales Manager; reps edit accounts they own). Every change writes an activity on the organisation's timeline; events `account.updated` for automations and webhooks.
- **Tests:** isolation, visibility, roll-ups per currency across the tree (no loops in the tree), grid from real deals, module switched off answers 404, browser walk on Brightlane.

### 11.3 Open questions

Answered 2026-11-12 (Decision log #36): all as recommended.


| # | Question | Recommendation |
| --- | --- | --- |
| K1 | Separate "account" records, or mark existing organisations as key? | **Mark organisations** (one record, one timeline; nothing to keep in step) |
| K2 | Is a department a contact or its own thing? | **Its own small record** under the account, with a contact as budget holder (a department outlives the person) |
| K3 | Health: set by hand or worked out? | **Set by the owner**, with a hint from data (no touch in 30 days, overdue money, lost deals) |
| K4 | Paid add-on? | Yes, priced separately (your call on the price) |
| K5 | Demo industry | HR and payroll software ("Brightlane"), unless you prefer another |

## 12. Milestone 4 in detail: API, webhooks and the ACE endpoints

What it is for: other software talks to Core safely. A company's developer (or Zapier, n8n, their website) reads and writes leads, deals, invoices and payments; Core tells their systems the moment something happens; ACE plugs in through exactly the same doors (rule 4: ACE uses Core's API and events, nothing special inside Core).

Already built and reused: the event outbox (every important change is already written as an event, with a `published_at` waiting for this step), form capture keys (spec "inbound webhooks" — step 1), signed webhook sending and the public-address check (step 4 automations), the lead `intent` field and the `outbound_ace` lead origin.

### 12.1 API keys (spec §11 "REST API")

- An admin creates a key in Settings → Developers: a name ("Website", "ACE", "Zapier") and a **role** (one of the company's roles, e.g. Admin, or a narrower custom role). The key can do exactly what that role can do, through the same `/api/v1` endpoints people use, so there is one API, one set of permission and visibility rules, and nothing duplicated.
- Behind the key sits an **integration user** (cannot sign in, has no password, never counts as a seat), so records it creates have an owner trail, timeline entries read "by API · Website", and the audit log names the key.
- The key is shown once (`vq_live_…`), stored only as a hash, can be revoked at any time, records when it was last used. Sent as `Authorization: Bearer vq_live_…`.
- Rate limit per key (default 100 requests a minute, using the Redis limiter we already have); `429` with `Retry-After` when exceeded.
- Two-factor and login rules do not apply to keys; revoking is instant.

### 12.2 Outbound webhooks (spec §11)

- Admin adds an endpoint (up to 10 per company): an `https://` public address (same check as automations, re-checked at every send so a name cannot later point inside our network), picks events from the catalogue (or "all"), gets a signing secret (encrypted at rest).
- Every minute the worker turns new events into deliveries for each matching endpoint. Body: `{id, type, occurred_at, data}`; headers `Versnq-Event`, `Versnq-Delivery`, `Versnq-Signature: t=<time>,v1=<HMAC-SHA256 of "t.body">` (the receiver checks it and rejects old timestamps).
- 10-second timeout, no redirects followed. Any 2xx is success. Otherwise retried with backoff: 1 min, 5 min, 30 min, 2 h, 6 h, 12 h, 24 h (8 tries over about two days), then marked failed. An endpoint failing for 3 days in a row is switched off and admins are notified.
- The same event is never delivered twice as new: the event id is in the body so receivers can ignore repeats.
- "Send test" and "Resend" buttons.

### 12.3 Logs (spec §11 "API & webhook logs")

- **API log:** every request made with a key: time, key, method, path, status, duration, IP. **Webhook log:** every delivery attempt: event, endpoint, status code, duration, response snippet, with a payload viewer.
- Live in the app for 30 days; then archived nightly to a compressed file per company on our server (kept 12 months, downloadable by the admin, erased when a company leaves) and removed from the database (Decision log #37).

### 12.4 ACE endpoints (spec §11, Decision log #4, #5)

ACE gets an ordinary API key with a role allowing these; nothing special in Core's code.
- `POST /api/v1/leads/upsert` — find by phone or email (the identities we already de-duplicate on); if found, return it untouched; if new, create it with origin `outbound_ace`, routed by the normal routing rules. Optional intent and conversation in the same call.
- `POST /api/v1/leads/{id}/conversation` — append a conversation (channel, messages, AI summary) as one activity on the timeline (rule 5); the next step's inbox will hold the message-by-message view.
- `PUT /api/v1/leads/{id}/intent` — hot / warm / cold / not interested, with a reason; writes an activity and emits `lead.intent_changed`.
- `call.analyzed` stays defined in the catalogue; its endpoint is built with call analysis (parked, #36).
- These are general enough for any outside tool, not only ACE.

### 12.5 Tables (all with `tenant_id`, forced row-level security, same-company keys) — migration 0021

`api_keys` (name, prefix, hash, integration user, created by, last used, revoked at) · `webhook_endpoints` (url, events, secret encrypted, active, failing since) · `webhook_deliveries` (event, endpoint, attempt count, next try at, status, last code, last error, duration) · `api_request_log` · users get a `kind` (person / integration). New permission `integrations.manage` (Owner and Admin by default). Activity types `api_conversation`, `intent_changed`.

### 12.6 Screens

Settings → **Developers**: API keys (create, copy once, revoke, last used) · Webhooks (add, pick events, send test, on / off, deliveries with status and payload viewer, resend) · API log (filter by key, status). A short "how to verify our signature" note with a code sample.

### 12.7 Tests ("done" means these pass)

A key reads only its own company (isolation) and only what its role allows (a Sales User key sees only its own leads); revoked key → 401 at once; rate limit → 429; integration users cannot sign in and are not seats; webhook signature verifies, retries follow the schedule, a private address is refused at save and at send, delivery after 3 days of failure switches off and notifies; event → delivery for only the endpoints that asked for it; upsert matches by phone and by email and never duplicates; conversation and intent write activities and emit events; logs cleaned after 30 days; browser walk of Settings → Developers.

### 12.8 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| W1 | What can a key do? | **Pick a role** (reuses roles and visibility; no separate scope list to learn) |
| W2 | Who manages keys and webhooks? | **Owner and Admin** (`integrations.manage`, grantable in Roles) |
| W3 | Retry schedule and switch-off | **8 tries over ~2 days; switch off after 3 days failing**, admins notified |
| W4 | Log retention | **30 days** for API and webhook logs |
| W5 | ACE conversation on the timeline | **One activity per conversation** (messages + summary), not one per message |
| W6 | Rate limit | **100 requests a minute per key** (Suyog, Nov 12), raise per company later if needed |
| W7 | `call.analyzed` endpoint | **Later, with call analysis** (parked, #36); event stays in the catalogue |

## 13. Step 8 in detail: page layouts and field permissions

What it is for: each company decides what its people see on a record and what they may change, without code (rule 3). A real-estate firm puts Budget and Locality at the top; a B2B firm puts Seats and Current tool; and an owner can stop a sales rep from seeing or changing fields such as deal value, discount or a client's PAN.

Already built and reused: custom fields with a group and an order, required fields (always, or from a stage onwards), linked dropdowns, unique fields, roles.

### 13.1 Page layouts (per company, per kind of record: lead, deal, customer, each record type)

- **Sections:** named, ordered boxes on the record page ("Contact", "Requirement", "Billing"). Built-in fields (company, website, city, industry…) and custom fields can both be placed in any section, in any order, or left off the page.
- **Highlights:** up to 4 fields shown under the record's name at the top (e.g. Budget, Locality), so the most important facts are seen first.
- **Add form:** which fields appear when someone adds a record (required fields always appear).
- One layout per kind of record for the whole company; what a role may see is set by field permissions (13.2), so there is one layout to keep tidy, not one per role.
- Every company starts with today's page as its layout, so nothing moves until an admin changes it.

### 13.2 Field permissions (per role, per field)

For each role and each field: **Edit** (default), **View only**, or **Hidden**. "Mandatory" stays per field and per stage, as today.
- Owner and Admin always edit everything (nobody can lock the company out).
- Enforced in the backend everywhere the field could leak: the record page, lists and saved-view columns, search and filters on that field, CSV export, CSV import (a view-only field is not overwritten), the API (keys follow their role), the "Details changed" lines on the timeline (a hidden field's old and new values are not shown), and merge. A view-only field cannot be changed by that role from anywhere.
- Required fields a role cannot edit do not block that role (the rule asks only what the person can fill).
- Calculated fields follow their own permission; a hidden input never shows through a calculation the role can see unless the admin allows that calculation.

### 13.3 Screens

Settings → Records and fields → each kind of record gets two new tabs: **Layout** (drag fields between sections, choose highlights and the add form, live preview) and **Field access** (a grid: fields down the side, roles across the top, Edit / View / Hidden in each cell).

### 13.4 Tables — migration 0022

`record_layouts` (company, kind of record, sections with their fields in order, highlights, add-form fields) · `field_permissions` (company, role, kind of record, field key, access view / hidden; no row = edit). Both company-scoped with forced RLS.

### 13.5 Tests ("done" means these pass)

Isolation; a hidden field never appears for that role in the record, list, search, filter, export, API or timeline; a view-only field cannot be changed by API, import, merge or the page; Owner/Admin unaffected; required-but-not-editable does not block; layouts keep working when a field is deleted or renamed; a company with no layout sees today's page; browser walk on Brightlane (hide Deal value from Sales User, reorder the lead page, add highlights) on desktop and phone.

### 13.6 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| P1 | One layout per company, or per role? | **One per company**; roles differ through field permissions |
| P2 | Which built-in fields can be hidden or made view-only? | **All except the name and the owner**; phone and email may be **view only** but not hidden (reps must be able to call and write) |
| P3 | "Mandatory" per role? | **No**: stays per field and per stage |
| P4 | Can a calculated field show a value built from a hidden field? | **No by default**; the admin can allow it per calculated field |
| P5 | Highlights | **Up to 4** per kind of record |

## 14. Steps 9–10 in detail: sequences, email, shared inbox, WhatsApp

What it is for: follow-ups run themselves. A new enquiry gets a welcome email and a WhatsApp, a reminder two days later, a task for the rep on day three; the moment the person replies, pays or opts out, the sequence stops and the reply lands in one shared inbox on the lead's timeline (rule 5). Everything is built and tested now with a **test sender** (messages are saved, not sent); the real email provider and Meta number plug in later without changing the rest.

Already built and reused: the company's mailbox sending (step 6), the suppression list and consent per channel (step 1), the automation builder (its "put into a sequence" action was reserved for this step, #16), events `sequence.enrolled` and `sequence.replied`, the timeline, API keys and webhooks (milestone 4).

### 14.1 Built in three slices, each tested before the next

| Slice | What | Needs from Suyog |
| --- | --- | --- |
| **9a** Sequences + email | Templates, sequence builder, enrolment, stop rules, quiet hours, sending limits, tracking, unsubscribe, step analytics | Nothing (test sender) |
| **9b** Shared inbox (email) | Replies threaded per lead, assignment, manager takeover, canned replies, reply from the inbox | Nothing (test inbound) |
| **10** WhatsApp | The company's own number, approved templates, the 24-hour window, opt-out, delivery / read status, inbound from an unknown number creates a lead, WhatsApp in sequences and the inbox, number health | Nothing until go-live (test Meta), then Meta keys |

### 14.2 Sequences (spec §5)

- **Steps:** email, WhatsApp, task for the rep (LinkedIn connect / message, call), wait (hours or days), and a **check** ("if they opened / clicked / have tag X / field Y = Z, go to step N, otherwise carry on") — that is how branches work.
- **Templates with variables:** `{{lead.first_name}}`, `{{owner.name}}`, `{{company.name}}`, any custom field, each with a fallback ("there" when the first name is blank). Preview with a real lead before saving.
- **Enrolment:** by hand (one or many from a list), from the automation builder ("when a lead comes from the website form → put into Welcome sequence"), or through the API. A lead is in one sequence at a time unless the admin allows more.
- **Stop rules:** the person replies, opts out, is unsubscribed or bounces, becomes a customer, a deal is won, a payment arrives, the lead is closed, or someone stops it by hand. Each stop is logged.
- **Quiet hours and limits:** no sends outside the company's hours (e.g. 9:00–20:00, in the company time zone) or on chosen days; a daily cap per sending address and per channel, so a new domain warms up slowly.
- **Respecting people (rule 8):** consent and the suppression list are checked at every send, not only at enrolment; every marketing email has a one-click unsubscribe.
- **Analytics per step:** sent, delivered, opened (marked estimated, #28), clicked, replied, bounced, unsubscribed, and how many went on to a deal or became customers.

### 14.3 Email (spec §6, #28)

- **Sending:** through one "sender" switch: the test sender now; at go-live the chosen provider (SES recommended) from the company's own domain, after it adds the DNS records we show (SPF, DKIM, DMARC) — several domains and brands per company (roadmap 3.10). The company's own mailbox (Gmail / Zoho, already used for invoices) stays available for small volumes.
- **Replies:** each email carries a reply address that routes the answer back into Core's inbox, so replies thread onto the right lead.
- **Tracking:** opens (pixel, labelled estimated), clicks (links go through our address first), bounces and spam complaints (hard bounces and complaints are suppressed automatically), unsubscribes.

### 14.4 Shared inbox (spec §6)

- One list of conversations (email now, WhatsApp in step 10), each tied to a lead; unread counts; filters: mine, unassigned, team, waiting for us.
- A conversation follows the lead's owner; a manager can take it over or hand it on; reps see only conversations of leads they can see.
- Reply from the inbox (email free text; WhatsApp only inside the 24-hour window, else an approved template); canned replies with variables.
- A reply stops the person's sequence and shows on the timeline; `sequence.replied` is emitted for automations, webhooks and later ACE.

### 14.5 WhatsApp (spec §6, step 10)

- The company's own number through the Meta Cloud API (direct, no reseller) — keys entered in settings, encrypted.
- Templates: written in Core, sent to Meta for approval, status shown (approved / rejected / paused); only approved ones can start a conversation.
- The 24-hour window: free text only within 24 hours of the person's last message; otherwise Core offers templates only.
- Opt-out words ("STOP") switch WhatsApp consent off at once; delivered / read / failed come from Meta's status messages; number quality and messaging limit shown.
- A message from an unknown number creates a lead (roadmap 3.5) through the normal intake and routing.

### 14.6 Tables (company-scoped, forced RLS) — migrations 0023 (9a), 0024 (9b), 0025 (10)

`message_templates`, `sequences`, `sequence_steps`, `enrolments`, `messages` (every email / WhatsApp in or out, with status and tracking), `message_events` (opened, clicked, bounced…), `sending_domains`, `conversations`, `canned_replies`, `whatsapp_accounts`, `whatsapp_templates`. Permissions `sequences.manage`, `templates.manage`, `inbox.reply`, `inbox.take_over`.

### 14.7 Tests ("done" means these pass)

Isolation; a sequence sends in order and waits; quiet hours and caps hold; every stop rule stops; opted-out, unsubscribed, bounced or suppressed people are never sent to, even mid-sequence; variables fill and fall back; unsubscribe link works without logging in; tracking counts; replies thread to the right lead and stop the sequence; reps see only their conversations; WhatsApp free text refused outside 24 hours; STOP opts out; unknown number creates a lead; browser walks per slice on desktop and phone.

### 14.8 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| E1 | Build order | **9a, then 9b, then 10**, each approved before the next |
| E2 | Email provider at go-live | **Amazon SES** (Mumbai), sending from each company's own domain; company mailbox kept for small volumes |
| E3 | WhatsApp connection | **Direct Meta Cloud API** (no reseller fees) |
| E4 | Branches | **"Check" steps that jump** (if … go to step N), not a drawing canvas — simpler to build and to understand |
| E5 | One sequence at a time per lead? | **Yes by default**; the admin can allow more |
| E6 | Quiet hours | **Company time zone**, default 9:00–20:00, Monday–Saturday, editable |
| E7 | Daily sending cap per address | **200 emails a day to start**, editable (protects new domains) |
| E8 | Auto-enrol | **Through the automation builder** (one place for "when X happens") rather than a second set of triggers |

## 15. Step 9b in detail: the full email trail and the shared inbox (replaces 14.4)

Goal (Suyog, Nov 12): match everything LeadSquared does with email, then go past it. LeadSquared captures the full mail trail three ways: each rep's Google Workspace / Office 365 mailbox synced (attachments included, CC'd people seen), a "copy-in" address (MarkCopy) for any mail app, and one-to-one emails from the CRM. Its limits: no personal Gmail / Outlook, one provider per account, no open / click tracking on copied-in mail.

### 15.1 Built in four slices

| Slice | What | Testable now? | Needs from Suyog |
| --- | --- | --- | --- |
| **9b-1** Threads and the shared inbox | Every email in or out with a lead grouped into conversations (by the email's own thread headers), CC'd people shown, attachments kept on the lead; inbox with mine / shared with me / unassigned / team / waiting for us; reply and new email from the CRM (with CC); colleagues added to a conversation; internal notes with @mentions; saved replies; a reply stops the person's sequences; merging two leads merges their conversations | Yes (test inbound) | Nothing |
| **9b-2** Copy-in address | One secret address per company (and per user): CC / BCC it on any email, or auto-forward, and the email lands on the right lead; an unknown sender can become a lead (company setting) | Yes (test inbound) | Inbound mail at go-live (with SES) |
| **9b-3** Connect my inbox (any provider) | Each user connects their own mailbox by IMAP + SMTP with an app password — Gmail (personal too), Google Workspace, Zoho, any mail server (Outlook / Microsoft 365 no longer accept app passwords: they come with 9b-4). Two-way: emails with known leads (sent or received, any device) sync to the lead; emails sent from the CRM go out from their own mailbox and appear in their Sent folder. Only emails with leads are stored; admin exclusion list (domains / addresses); each user can mark a thread private; disconnecting stops sync | Yes (simulated mailbox in tests) | Nothing |
| **9b-4** One-click Gmail / Outlook sign-in | The same sync, but connected with "Sign in with Google / Microsoft" instead of an app password | At go-live | Google OAuth app + Google's security review for Gmail access (weeks, paid); Microsoft app registration |

### 15.2 Where we go past LeadSquared

| | LeadSquared | Versnq Core |
| --- | --- | --- |
| Personal Gmail / Outlook.com | No (Workspace / 365 only) | **Yes** (9b-3) |
| Several providers in one company | One provider at a time | **Any mix** — each user connects their own |
| Open / click tracking on CRM emails | Not on copied-in mail | **Yes**, on every email sent from Core |
| Email + WhatsApp in one conversation per lead | Separate | **One thread** (step 10) |
| A reply stops every sequence, on any channel | Partly | **Yes** |
| Colleagues join a conversation, internal notes, @mentions | Limited | **Yes** |
| An emailed document (PAN, contract) saved to the customer checklist in one click | No | **Yes** (step 5 checklist) |
| Who may see which email | Mailbox-level | **Lead visibility + field access** (step 8) apply to emails too |
| AI drafts and replies | Add-on | **ACE**, same inbox |

### 15.3 Privacy and safety

Mailbox passwords and tokens encrypted (as gateway keys are). Only emails to or from known leads are kept — never the rest of someone's mailbox. Admin exclusion list. A user can mark a thread private (only they and admins see it). Disconnecting stops sync; their synced emails stay on the leads unless an admin removes them. Attachments go through the same file checks as uploads (type, size, storage quota). Everything audited.

### 15.4 Tables — migration 0024

`conversations` (lead, channel, subject, assignee, status open / waiting / closed, last message, private), `conversation_members` (colleagues added), `conversation_notes` (internal, with mentions), `message_attachments` (file record per attachment), `mailboxes` (per user: provider, IMAP / SMTP settings, encrypted secret, last sync, sync cursor, status), `canned_replies`; `messages` gains thread ids (Message-ID, In-Reply-To), CC list, mailbox and conversation links. Tenant settings: copy-in address, unknown-sender policy, exclusion list. Permissions `inbox.reply` (default everyone who edits leads), `inbox.take_over` (managers), `mailboxes.manage` (admins: exclusions, see who is connected).

### 15.5 Tests ("done" means these pass)

Isolation; replies thread onto the right conversation by headers and by address; CC'd people and attachments kept; reps see only conversations of leads they can see, plus ones shared with them; a shared colleague sees the conversation and lead basics but not deals or money unless their role allows; internal notes never go out in an email; a reply stops sequences; merge moves conversations; copy-in address logs to the right lead and creates one only when the setting allows; mailbox sync stores only emails with known leads, honours exclusions and private threads, never duplicates an email seen twice, survives a wrong password (status shows it); sending from the CRM through the user's own mailbox; browser walks per slice, desktop and phone.

### 15.6 Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| I1 | Build order | **9b-1 → 9b-3 → 9b-2**, 9b-4 at go-live (9b-3 gives the full trail without waiting for Google) |
| I2 | A colleague added to a conversation sees… | **The conversation + the lead's basics** (name, contact, stage); deals and money only if their role allows |
| I3 | Unknown sender on the copy-in address or a synced mailbox | **Don't create a lead by default**; company setting "create a lead" (copy-in only) |
| I4 | How far back to sync when a mailbox is connected | **30 days**, then live |
| I5 | When a user disconnects | **Keep their synced emails on the leads**; an admin can remove them |
| I6 | Who can read a synced email on a lead | **Whoever can see the lead**, unless the user marked the thread private |

## 16. Step 10 in detail: WhatsApp (replaces 14.5)

Agreed with Suyog (Nov 12) after comparing four ways in: Meta's official API alone (the number leaves the phone app), **official API + Coexistence** (one number on the WhatsApp Business app and the API at once), an unofficial gateway (WA-AKG / Baileys: against WhatsApp's terms, numbers can be banned, our server would hold their login) and a **Chrome extension on WhatsApp Web**. Decision: **B + D only.** WA-AKG is parked (only reconsidered if Coexistence is unavailable in India). **No group chats. No auto-replies on anyone's own WhatsApp** — autoresponding stays on the official company number only.

| Way in | Who | What it gives |
| --- | --- | --- |
| Official company number (Meta Cloud API; later with Coexistence) | The company | Sequences, payment reminders, campaigns, the autoresponder; Meta's template and 24-hour rules enforced by Core |
| The rep's own WhatsApp + the Versnq Chrome extension | Every salesperson, any number of them | Chats freely as today; a panel beside WhatsApp Web shows the lead; chats with known leads are logged to Core; nothing is ever sent by the extension |
| Coexistence (10c) | Company number and any rep on WhatsApp Business | Same app on the phone, every chat (phone too) in Core, officially |

### 16.1 Slices

| Slice | What | Needs from Suyog |
| --- | --- | --- |
| **10a** Reps' WhatsApp (now) | WhatsApp as a channel in conversations, the inbox and the lead's trail; "Chat on WhatsApp" button on the lead (opens the rep's own WhatsApp); the Chrome extension: connect with a one-time code from My account, side panel with the lead (stage, owner, next follow-up, open deals, balance due), create lead from an unknown number, add a note or a follow-up date, saved replies put into the message box (the rep presses Send), automatic logging of chats with known leads, "Sync this chat"; admin list of connected extensions with last activity, revoke | Nothing to build; a Google developer account (one-time $5) to publish it unlisted later |
| **10b** Official company number | Meta keys in Settings, templates sent for approval, the 24-hour window, STOP words, delivered / read, unknown number → lead, WhatsApp steps in sequences, payment reminders on WhatsApp, autoresponder (this number only), number health; built with a test sender | Meta Business verification |
| **10c** Coexistence | One-click "Connect WhatsApp Business" (Embedded Signup) for the company and any rep on WhatsApp Business; the extension skips numbers connected this way | Versnq approved as a Meta Tech Provider; confirm Coexistence is available for Indian numbers |

### 16.2 The extension (10a)

- **Where:** `extension/` in this repo, TypeScript compiled with the TypeScript already in the frontend; no new libraries. Chrome, Edge, Brave (Manifest V3). Loaded by hand while piloting; published **unlisted** on the Chrome Web Store for customers.
- **Connecting:** My account → WhatsApp extension → "Connect" shows a one-time code (10 minutes). The rep types the workspace address and the code into the extension; it gets its own token, which works only on the extension's endpoints and can be revoked by the rep or an admin. No password is ever typed into the extension.
- **Reading:** only the open one-to-one chat; group chats skipped. The chat's number comes from WhatsApp Web's own message ids when present, otherwise the rep links the chat to a lead once ("Link to lead") and Core remembers it. Each message's own id means nothing is logged twice; sent or received is read from WhatsApp itself. The code that reads WhatsApp Web lives in one file, so a WhatsApp change is a quick fix; the admin list shows each rep's last activity, so a break is noticed.
- **Privacy:** messages of people who are not leads never leave the laptop; a number is sent only to ask "is this a lead?" and is not stored. Photos and files are logged as "[photo]" / "[document]" for now.
- **Never:** sends by itself, bulk anything, reads groups, copies the contact list.

### 16.3 Tables — migration 0027

`extension_tokens` (user, token hash, one-time connect code hash + expiry, device name, version, last used, revoked); `whatsapp_chat_links` (chat key → lead, for chats without a number); `messages` gain `external_id` (WhatsApp's message id, unique per company). Timeline types `whatsapp_sent`, `whatsapp_received`. Connected extensions shown to holders of `mailboxes.manage` (Settings → Connected inboxes).

### 16.4 Tests ("done" means these pass)

Isolation; a connect code works once and expires; an extension token is refused on every other endpoint and after revoking; lookup finds only leads the rep may see; messages land on the right lead, in one WhatsApp conversation, once (same id twice → once); a received WhatsApp stops sequences that stop on replies; a sent one counts as contacting the lead; create lead from the panel goes through intake and duplicate rules; reps see only conversations of leads they can see; the extension's reader on a saved WhatsApp Web page; browser walk desktop and phone.

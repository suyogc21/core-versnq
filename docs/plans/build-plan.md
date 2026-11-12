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
| Salesperson: today, follow-ups, my pipeline, conversions, end-of-day summary | Part — My Day done; the rest step 6 |
| Sales Manager: team funnel, sources, leaderboard, leakage, SLA breaches | Planned — step 6 |
| Owner/Admin: revenue, collections, overdue, sequence performance, channel health | Planned — step 7 (+ steps 9–10 data) |
| Finance dashboard: invoices, dues, aging, entity-wise collections | Planned — step 7 |
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

**Progress:** step 1 done 2026-11-09 (309 backend tests, 5 e2e, 23-check walk). Step 2 done 2026-11-09 (324 backend tests, 6 e2e, 20-check walk). Settings clean-up done 2026-11-10: the sidebar holds only places people work in; everything set up once is under one grouped Settings home (326 backend tests, 6 e2e, 34-check walk). Money unparked 2026-11-10 as step 6. Step 3 done 2026-11-10: deals and pipelines with a drag board, lost reasons, products and deal links (342 backend tests, 6 e2e, 26-check walk). Step 4 done 2026-11-11: tags, saved views, scoring, calculated fields and the automation builder (366 backend tests, 6 e2e, 26-check walk incl. a live automation run). UI restyle done 2026-11-12 (Decision log #30). Step 5 done 2026-11-12 (Decision log #32): customers, checklist, staff uploads, review; customer link removed (#33) (376 backend tests, 6 e2e, 30-check walk). Step 6 done 2026-11-12 (Decision log #34): invoices, installments, payments, Razorpay / Stripe links, pay-directly with UPI QR, emails from the company's mailbox, reminders, repeat invoices, aging (406 backend tests, 6 e2e, 30-check walk). Next: step 7, dashboards.

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

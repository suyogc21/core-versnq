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
| Tags, lists, smart views (per user and team) | Planned — step 4 |
| Rule-based lead scoring | Planned — step 4 |
| Bulk actions: assign, update | Done |
| Bulk actions: tag, enrol | Planned — tag step 4, enrol step 8 |
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
| WHEN event IF conditions THEN actions | Planned — step 4 |
| Calculated fields, engagement score | Planned — step 4 |
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
| Invoices: line items, tax fields (GST), PDF, numbering per entity | Planned — step 6 (PDF storage needs the step 5 file-storage decision) |
| Installment plans: amount and due date per installment | Planned — step 6 |
| Payment links: Razorpay (India), Stripe (UAE/US) | Planned — step 6 |
| Payment status sync from gateway webhooks | Planned — step 6 |
| Manual payment entry with proof upload | Planned — step 6 |
| Balance tracking: paid, due, overdue per customer | Planned — step 6 |
| Auto reminders before due, on due, overdue | Planned — step 6 (in-app at first; email from step 9, WhatsApp from step 10) |
| Multi-entity, any currency (Decision log #2) | Planned — step 6 |
| Receipts sent on payment | Planned — step 6 (by email from step 9) |
| Collections aging report 0–30 / 30–60 / 60+ | Planned — step 6 report, step 7 dashboard |
| Bank statement import | Later |

Rule 7 applies throughout: amounts are integers in minor units with a currency code; never floats.

---

## 3. Build order

**Progress:** step 1 done 2026-11-09 (309 backend tests, 5 e2e, 23-check walk). Step 2 done 2026-11-09 (324 backend tests, 6 e2e, 20-check walk). Settings clean-up done 2026-11-10: the sidebar holds only places people work in; everything set up once is under one grouped Settings home (326 backend tests, 6 e2e, 34-check walk). Money unparked 2026-11-10 as step 6. Step 3 done 2026-11-10: deals and pipelines with a drag board, lost reasons, products and deal links (342 backend tests, 6 e2e, 26-check walk). Step 4 plan approved 2026-11-11 (Decision log #27); building.

| Step | What | Why here |
| --- | --- | --- |
| 1 | **Capture and routing**: CSV import, form/webhook capture, duplicates + merge, organisation suggestions, consent + suppression list, auto-assignment, SLAs and leakage guard, in-app notifications | Leads must come in clean and reach the right person |
| 2 | **Records and links engine**: custom record types, labelled links, organisation page | Deals and customers are built on it |
| 3 | **Deals and pipelines** | First real use of the engine |
| 4 | **Tags, saved views, live lists, scoring, calculated fields, automation builder** | Runs the business without manual work |
| 5 | **Customers and documents** | Needs a file-storage decision |
| 6 | **Money**: invoices (tax, PDF, numbering per entity), installment plans, payment links (Razorpay, Stripe), gateway webhooks, manual payments with proof, balances, receipts, reminders, collections aging, any entity and currency | Unparked 2026-11-10 (Decision log #24). Invoices hang off a deal or customer, so it follows step 5 |
| 7 | **Dashboards and CSV export**, including the Finance dashboard and money on the owner's | Needs data from steps 1–6 |
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
| C1 | Where does the uploaded CSV live until file storage (S3) is chosen? | In the database, up to 20 MB / 50,000 rows per file; moved to S3 in step 5 |
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

# Versnq Core — what is built, what is left, and the order

Written 2026-11-09. Every row of the spec's feature catalogue, its "How people use it" section and the Decision log is listed here exactly once, so nothing is missed. Status: **Done**, **Part** (what is missing is named), **Planned** (step number), **Parked** (Decision log #1), **Later** (spec says later), **ACE** (belongs to ACE).

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
| 360° lead view | Part — profile, timeline, tasks done; deals step 3, documents step 5, invoices Parked |
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
| Several pipelines (per product, course, program) | Planned — step 3 |
| Kanban board with drag | Planned — step 3 (needs `@dnd-kit`, to approve) |
| Deal value and expected close | Planned — step 3 (integer minor units + currency, rule 7) |
| Won/lost reasons, mandatory and reportable | Planned — step 3 |
| Product / course catalogue with price list | Planned — step 3 |

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
| Owner/Admin (non-money parts): sequence performance, channel health | Planned — step 6 (+ steps 8–9 data) |
| Finance dashboard, collections | Parked |
| Custom reports | Later |

### Sequences, inbox, channels (§5, §6)

| Feature | Status |
| --- | --- |
| Sequence builder: steps, delays, conditions, branches | Planned — step 8 |
| Auto-enrol triggers, stop rules, quiet hours, throttling | Planned — step 8 |
| Email steps, templates with variables, per-domain sender | Planned — step 8 |
| Unsubscribe and suppression list | Planned — suppression list created in step 1, used in step 8 |
| Open/click tracking | Planned — step 8 |
| Unified inbox, assignment and handoff, canned replies | Planned — step 8 (email), step 9 (WhatsApp) |
| Multi-domain email (SPF/DKIM/DMARC), multi-brand | Planned — step 8 |
| WhatsApp connector: own number, templates, 24-hour window, opt-out, health | Planned — step 9 (after Meta registration) |
| LinkedIn steps as rep tasks | Planned — step 8 |
| Sequence analytics per step | Planned — step 8 |
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
| Payment gateways | Parked |
| Google Workspace, Zapier/N8n, HubSpot/LeadSquared import | Later |

### Money (§8)

Parked (Decision log #1). Not built until unparked.

---

## 3. Build order

| Step | What | Why here |
| --- | --- | --- |
| 1 | **Capture and routing**: CSV import, form/webhook capture, duplicates + merge, organisation suggestions, consent + suppression list, auto-assignment, SLAs and leakage guard, in-app notifications | Leads must come in clean and reach the right person |
| 2 | **Records and links engine**: custom record types, labelled links, organisation page | Deals and customers are built on it |
| 3 | **Deals and pipelines** | First real use of the engine |
| 4 | **Tags, saved views, live lists, scoring, calculated fields, automation builder** | Runs the business without manual work |
| 5 | **Customers and documents** | Needs a file-storage decision |
| 6 | **Dashboards and CSV export** | Needs data from steps 1–5 |
| 7 | **Page layouts and field-level permissions** | |
| 8 | **Sequences, email, inbox, multi-brand** | Needs an email provider decision |
| 9 | **WhatsApp connector** | After Meta registration |
| 10 | **Public API, outbound webhooks, ACE endpoints, security S.1–S.5** | |
| 11 | **Go-live G.1–G.3** | Before the first paying client |

**Demo:** Wednesday 2026-11-11 shows what is built today plus steps 1 and 2, but only parts that have passed every test. Anything not fully tested by Wednesday morning is left out of the demo, not rushed in.

---

## 4. Step 1 in detail: capture and routing

### 4.1 Tables (all with `tenant_id`, forced row-level security, same-company keys)

| Table | Purpose |
| --- | --- |
| `capture_sources` | One endpoint per lead source: name, source, secret key (stored hashed), field mapping, default owner rule, consent wording, active. Websites post leads here |
| `imports` | CSV import job: uploaded by, file name, column mapping, duplicate policy, status, counts (created / updated / skipped / errors) |
| `import_rows` | One row per CSV line: raw values, result, lead id, error message. Lets the user download the failed rows |
| `lead_merges` | Who merged which lead into which, with a snapshot of the merged lead |
| `consents` | Lead, channel (email / WhatsApp), opted in or out, source, time, evidence. Full history; the latest row is the current state |
| `suppression_list` | Channel + identifier + reason (opt-out, bounce, complaint). Not linked to a lead, so it survives deletion (#18) |
| `external_refs` | System + external ID → lead. Makes repeated form posts and API calls safe to retry |
| `assignment_rules` | Order, conditions (source, language, region, any custom field), strategy (round-robin over chosen users or a team, one user, leave unassigned), active |
| `assignment_cursors` | Remembers whose turn is next for each round-robin rule, safe when two leads arrive together |
| `sla_rules` | Trigger (lead created, stage entered), within N minutes/hours, action (create a task, alert the manager, reassign) |
| `notifications` | In-app messages for a user: kind, text, link, read time |
| Settings | `duplicate_policy` (update existing (default, DM2) / flag / always create), `org_grouping` (off / suggest / auto-link domains, #14), leakage hours |

`leads` gains `merged_into_id`, `possible_duplicate_of_id`, `first_response_at`.

### 4.2 Rules the backend enforces

- **Duplicates (R5):** on every entry path (form, CSV, quick-add, API), match on cleaned phone or email within the company. Default: update the existing lead, keep its owner, add a "Re-enquiry" activity and reopen it if closed. Other per-company options: flag as a possible duplicate, or always create new.
- **Merge:** pick the surviving lead and, field by field, which value to keep. Phones, emails, timeline, tasks and consents move over. The merged lead is hidden but kept for history, and its old links point to the survivor. Needs `leads.edit` on both leads.
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

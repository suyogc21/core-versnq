# Phase 2 — Core CRM: plan

Status: **proposed 2026-11-07, waiting for Suyog's approval.** Source of truth: the spec (§1–4, §7, §9 non-money parts, Decision log #10, #14–#18), `docs/specs/data-model.md` (approved) and the approved main-screen mockup (`docs/design/mockup-main.html`).

Goal: the actual CRM. A salesperson's whole day (leads, history, follow-ups, deals) runs in Core, and Versnq can run its own pipeline in it from the end of slice B.

## How Phase 2 is split

Each slice ends with something you can demo. It gets demo data, backend tests, browser checks and its own short approval.

| Slice | Roadmap items | You can demo |
| --- | --- | --- |
| **A. Leads, timeline, tasks** | 2.1 (no import), 2.7, 2.8, My Day part of 2.12 | Add a lead, see its full history, log calls and notes, set follow-ups, a real My Day |
| **B. Pipelines and deals** | 2.9 | Pipelines per product/course, kanban drag, won/lost reasons, product catalogue |
| **C. Capture and routing** | 2.2, 2.3, 2.3b, 2.4, 2.5, 2.6 | Web form/webhook capture, CSV import, duplicate check + merge, org grouping, consent, auto-assignment, leakage guard |
| **D. Customers and documents** | 2.10 | Convert lead → customer, registration link, document checklist and upload |
| **E. Views, scoring, automation** | 2.11, 2.11b | Tags, saved views, bulk actions, scoring rules, WHEN/IF/THEN automations |
| **F. Dashboards and export** | 2.12, 2.13 | Salesperson, manager and owner dashboards; CSV export |

Suggested order A → B → (Versnq starts using it) → C → D → E → F. Slices C–F get the same detailed plan as A below, each approved before it starts.

---

## Slice A in detail

### A1. Tables (all with `tenant_id`, forced RLS, composite tenant FKs)

Exactly as in the approved data model. Only the parts slice A needs are built now:

| Table | Built now | Left for later |
| --- | --- | --- |
| `lead_stages` | name, order, `is_open`, `is_unqualified`, colour; seeded **Invalid** closed stage | `is_converted` used in slice D |
| `lead_sources` | name, `is_active` | — |
| `leads` | kind, person/org fields, display name, primary email/phone, owner, team, stage, follow-up, last activity/contact, last disposition, origin, source, created_via, UTM + attribution, language, city/region/country, custom_fields, unqualified_reason, created_by, version | `organisation_id` linking UI (C), score (E), intent (Phase 4), customer link (D), merged_into (C) |
| `lead_identities` | email / phone / LinkedIn, normalized value, primary, label, is_whatsapp | duplicate matching uses its index in C |
| `custom_field_definitions` | entity `lead` only; key (fixed) + label; types text, number, date, select, multi-select, phone, email, url; required; group; order | `file` type (needs S3, slice D); deal/customer entities (B, D) |
| `activity_types` | system types (note, call, stage_changed, owner_changed, lead_created, field_changed) + tenant custom types ("Site visit done") with a small fields schema | message types arrive with Phase 3 |
| `activities` | lead_id, type, actor (user/system/api), occurred_at, summary, data, disposition | deal/customer links (B, D) |
| `tasks` | lead_id, title, due_at, owner, status, priority, created_from, completed_at | `sla_rules` in C |

One migration per table group. Industry packs gain stages, sources and starter custom fields (EdTech: "Course interest", "Qualification"; generic: none). Configuration only, no code branches.

### A2. Rules enforced by the backend

- **R1:** a lead needs at least one phone, email or LinkedIn URL; organisation leads need `org_name`.
- **R7:** phones stored as E.164 using the company's default country (`phonenumbers` library, approved in DM4). Emails are trimmed and lowercased.
- **R4, the anti-leakage rule:** after a rep logs a call or note on an **open** lead, it must have a next follow-up date. The API refuses without one. Closed stages (including Invalid) need none.
- **Invalid / unqualified stages** need a reason.
- **Delete is permanent** (#18): permission `leads.delete`, confirmation in the UI, timeline removed, audit row keeps only the lead ID. Converted leads cannot be deleted (applies from slice D).
- **Two people editing at once:** every edit sends the `version` it started from. A stale edit gets "changed by someone else, reload" (409) instead of silently overwriting.
- **Everything is an activity:** creation, stage change, owner change and field edits write timeline rows. Each also emits its catalogue event (`lead.created`, `lead.updated`, `lead.assigned`, `lead.stage_changed`, `activity.logged`, `task.created`, `task.due`).
- `task.due` is emitted by the background worker (arq cron, already in the stack) when a task falls due.

### A3. Who sees and does what

Visibility follows each role's scope (Phase 1): **own** = leads they own; **team** = leads owned by anyone in the teams they manage (and sub-teams); **all** = everything.

New permissions (deny by default, Owner has all):

| Permission | Allows | Default roles |
| --- | --- | --- |
| `leads.create` | Add leads | Admin, Sales Manager, Sales User |
| `leads.edit` | Edit visible leads, log activities, manage their tasks | Admin, Sales Manager, Sales User |
| `leads.assign` | Change a lead's owner | Admin, Sales Manager |
| `leads.delete` | Permanently delete | Admin |
| `crm.configure` | Stages, sources, custom fields, activity types | Admin |

### A4. API (all under `/api/v1`, all behind the `crm` module)

| Area | Endpoints |
| --- | --- |
| Leads | `GET /leads` (search, filter by stage/owner/source/follow-up due/unassigned, sort, paged) · `POST /leads` · `GET/PATCH/DELETE /leads/{id}` · `PUT /leads/{id}/owner` · identities edited inside PATCH |
| Timeline | `GET /leads/{id}/activities` (newest first, paged) · `POST /leads/{id}/activities` (note, call with disposition + next follow-up, custom type) |
| Tasks | `GET /tasks` (mine / my team, due filter) · `POST /tasks` · `PATCH /tasks/{id}` (done, reschedule, reassign) · `DELETE /tasks/{id}` |
| My Day | `GET /me/day`: overdue + today's follow-ups and tasks, new leads assigned to me; for managers also the unassigned queue |
| Configuration | `GET/POST/PATCH/DELETE` for `/lead-stages`, `/lead-sources`, `/custom-fields`, `/activity-types` (reorder via PATCH; a stage or source in use cannot be deleted) |

### A5. Screens (following the approved mockup)

- **Leads list** (titled with the company's label, e.g. "Students"): table, search, filters, "follow-up due" chips, quick-add dialog. Phone-friendly.
- **Lead page (360):** header (name, stage, owner, next follow-up) · profile with identities and custom fields · timeline with a composer (note / log call with disposition / custom activity) · tasks panel.
- **My Day:** overdue, today, new leads; one click to log a call and set the next follow-up.
- **Settings → Pipeline setup:** stages, sources, custom fields, activity types (drag to reorder).

### A6. Tests ("done" means these pass)

- **Isolation:** every new table is invisible across companies (RLS + API 404).
- **Visibility:** a Sales User sees only their own leads; a manager sees their team's and not another team's; Admin sees everything. Checked on list, detail, timeline and tasks.
- **Permissions:** each action is refused without its permission; no one can assign a lead to a user they cannot see.
- **Rules:** R1, R4, R7 (Indian, UAE and US numbers), Invalid needs a reason, stale edit → 409, delete removes the timeline and leaves an ID-only audit row.
- **Events and activities** written for every change; `task.due` fired once by the worker.
- **Labels and packs:** an EdTech company sees "Students" and its seeded stages; nothing is industry-coded.
- **End-to-end (browser):** a Sales User adds a lead → logs a call → must set a follow-up → it appears on My Day; their manager sees it, a rep on another team doesn't.
- **Demo data:** Acme gets ~300 invented students across stages, owners and sources, with a few weeks of calls, notes and tasks.

### A7. New dependencies

- `phonenumbers` (backend). Already approved in data-model DM4.
- Nothing new for the frontend in slice A. Kanban drag-and-drop in slice B will need one library (e.g. `@dnd-kit`); I'll ask then.

### A8. Open questions for Suyog

| # | Question | Recommendation |
| --- | --- | --- |
| Q1 | Should **Finance** see leads? The spec says Finance sees invoices, payments and reminders, all parked. | **No lead access** for now; Finance gets customers in slice D |
| Q2 | Who sees **unassigned** leads (no owner yet)? | Team-scope and all-scope roles (managers, Admin, Owner); Sales Users don't |
| Q3 | Who can **delete** leads? | Owner and Admin only (`leads.delete`); everyone else uses the Invalid stage |
| Q4 | Default **stages** | Generic: New → Contacted → Qualified → Nurturing → Won / Lost / Invalid. EdTech: New enquiry → Counselling done → Application → Enrolled / Not interested / Invalid. Editable per company |
| Q5 | Can a **Sales User create a lead** that is then owned by them automatically? | Yes, a rep's own new lead is theirs; managers choose an owner or leave it unassigned |
| Q6 | Is the **follow-up rule (R4)** strict for every company? | Strict by default, with a per-company setting to make it a warning instead |

# Versnq Core — Data Model

Status: **approved 2026-11-05** except DM5 (retention) — see spec Decision log #15–#17. Tables are built phase by phase from this document; changes go through this file first.

## Rules that apply to every table

- `id uuid` primary key; `created_at`, `updated_at` (timestamptz, UTC).
- Every business table has `tenant_id uuid not null` + forced row-level security (Phase 1-A).
- Soft delete where records matter for history: `deleted_at timestamptz null` (leads, deals, customers, contacts). Hard delete only for junk/imports undone.
- Money columns (when Money is unparked): `amount_minor bigint` + `currency char(3)`. Never floats.
- Free-form tenant data lives in `custom_fields jsonb`, validated against `custom_field_definitions`. Never add a column for one client.
- Labels shown to users (Lead → "Student") come from tenant settings; table names never change.
- Every change to a lead/deal/customer writes an `activities` row and an `events` row (rules 5 and 6).

---

## 1. Leads (Phase 2) — the centre of Core

A **lead** is the record a salesperson works. It is either a **person** (student, buyer, applicant) or an **organisation** (company, agency) — Decision log #10.

### 1.1 `leads`

| Column | Type | Required | Notes |
| --- | --- | --- | --- |
| `kind` | `person` / `organisation` | yes | Chosen at creation; can be changed by Admin |
| **Person fields** | | | |
| `first_name` | text | see rule R1 | |
| `last_name` | text | no | Many Indian leads have one name only |
| **Organisation fields** | | | |
| `org_name` | text | yes if organisation | |
| `website` | text | no | |
| `domains` | text[] | no | e.g. `{acme.com, acme.in}` — used for grouping (#14) |
| `industry`, `employee_range` | text | no | |
| **Shared** | | | |
| `display_name` | text (generated) | — | `first_name last_name` or `org_name`; falls back to primary phone/email |
| `primary_email` | citext | see R1 | Copy of the primary row in `lead_identities`, for fast display |
| `primary_phone` | text (E.164, e.g. `+919876543210`) | see R1 | Copy of the primary row in `lead_identities` |
| `organisation_id` | uuid → `leads` | no | A person lead linked to an organisation lead (#14) |
| `owner_user_id` | uuid → `users` | no | Null = unassigned queue |
| `team_id` | uuid → `teams` | no | Owner's team at assignment time (for team visibility) |
| `assigned_at` | timestamptz | no | |
| `stage_id` | uuid → `lead_stages` | yes | Tenant-configurable lifecycle (New, Contacted, Qualified, …) |
| `stage_changed_at` | timestamptz | yes | |
| `is_open` | bool | yes | Copied from stage; open leads must have a next follow-up |
| `next_follow_up_at` | timestamptz | rule R4 | Anti-leakage rule |
| `last_activity_at`, `last_contacted_at`, `first_response_at` | timestamptz | no | SLA and leakage guard |
| `last_disposition` | text | no | Interested, Callback, Not reachable… |
| `score` | int | yes (default 0) | Rule-based lead scoring |
| `intent` | `hot` / `warm` / `cold` / `not_interested` | no | Set by ACE through the API (`lead.intent_changed`) |
| `intent_updated_at` | timestamptz | no | |
| `origin` | `inbound` / `outbound_ace` / `outside` | yes | Spec "Three ways a lead enters Core" |
| `source_id` | uuid → `lead_sources` | yes | Website, Meta ads, Walk-in, Referral… (mandatory per spec) |
| `created_via` | `form` / `api` / `csv` / `manual` / `whatsapp` / `email` / `ace` | yes | Technical channel |
| `campaign`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content` | text | no | Reportable attribution |
| `attribution` | jsonb | no | Everything else: referrer, landing page, gclid, fbclid, form id |
| `preferred_language` | text (e.g. `hi`, `en`) | no | Used by routing rules |
| `city`, `region`, `country_code` | text | no | Routing by region |
| `custom_fields` | jsonb | no | Validated against definitions (course interest, budget, KYC group…) |
| `customer_id` | uuid → `customers` | no | Set when converted |
| `converted_at` | timestamptz | no | |
| `unqualified_reason` | text | no | Mandatory when moved to an "unqualified" stage |
| `merged_into_id` | uuid → `leads` | no | Set when merged; record kept for history |
| `created_by_user_id` | uuid | no | Null for system/API |
| `version` | int | yes | Stops two people overwriting each other's edits |
| `deleted_at` | timestamptz | no | Soft delete |

### 1.2 `lead_identities` — every email and phone a lead has

| Column | Type | Notes |
| --- | --- | --- |
| `lead_id` | uuid | |
| `type` | `email` / `phone` / `linkedin` | A WhatsApp number is a phone; LinkedIn = profile URL |
| `value` | text | As entered |
| `value_normalized` | text | Email: trimmed, lowercased. Phone: E.164 using the tenant's default country |
| `is_primary` | bool | One primary per type per lead |
| `label` | text | Personal, Work, Parent… |
| `is_whatsapp` | bool | Number is reachable on WhatsApp |

Index on `(tenant_id, type, value_normalized)` for de-duplication lookups.

### 1.3 Rules

| Rule | Decision |
| --- | --- |
| **R1 Minimum data** | A lead needs **at least one identifier: phone, email or LinkedIn profile URL** (Decision log #17). Name is optional (display name falls back to the identifier). Organisation leads need `org_name`. |
| **R2 Email optional?** | **Yes.** Most EdTech/real-estate leads arrive with a phone only. |
| **R3 What is unique?** | **Nothing is hard-unique** on email or phone. Real case: two siblings enquire using one parent's phone. Instead, a **de-duplication rule** runs on every capture (below). |
| **R4 Follow-up** | Every **open** lead must have `next_follow_up_at` once a rep has touched it. The API rejects closing an activity without one (spec "anti-leakage rule"). |
| **R5 Duplicate policy** (per tenant) | Match on normalized phone **or** email within the tenant. Default: **update the existing lead** (log a "Re-enquiry" activity, keep the owner, re-open if closed). Options: *flag as possible duplicate* or *always create new*. Merge tool for manual merges. |
| **R6 Grouping** | Domain / company-name matching suggests linking a person to an organisation lead (Decision log #14). |
| **R7 Normalization** | Phones stored as E.164 using the tenant's default country code; emails lowercased and trimmed (Gmail dots are **not** removed). |

### 1.4 Supporting tables (Phase 2)

| Table | Purpose |
| --- | --- |
| `lead_stages` | Per-tenant lifecycle: name, order, `is_open`, `is_converted`, `is_unqualified`, colour |
| `lead_sources` | Per-tenant sources: name, `is_active` |
| `tags`, `lead_tags` | Tags and the many-to-many link |
| `custom_field_definitions` | entity (`lead` / `deal` / `customer` / `activity`), **key (fixed backend ID, never changes; used by API/webhooks/automations)**, label (display name, renamable), type (text, number, date, select, multi-select, phone, email, url, file), options, required, group (e.g. KYC), order |
| `consents` | lead_id, channel (`whatsapp` / `email`), status (`opted_in` / `opted_out`), source, captured_at, evidence — full history; latest row = current state |
| `lead_merges` | survivor_id, merged_id, merged_by, snapshot jsonb |
| `external_refs` | entity, entity_id, system (`ace`, `website`, `hubspot`…), external_id — unique per tenant+system+external_id; makes API/ACE upserts safe to retry |
| `assignment_rules` | order, conditions jsonb (source, language, region, custom field), strategy (`round_robin` / `specific_user` / `team`), target, is_active |
| `saved_views` | name, owner (user or team), entity, filters jsonb, columns |
| `imports` | CSV import jobs: file, mapping, counts (created / updated / duplicates / errors), status |

---

## 2. Activities and tasks (Phase 2)

| Table | Key columns |
| --- | --- |
| `activity_types` | key, label, `is_system` (email_sent, whatsapp_received, call, note, stage_changed…), fields schema for custom types ("Site visit done"), icon, counts toward score |
| `activities` | lead_id, deal_id, customer_id (any of), type_id, actor_type (`user` / `system` / `api` / `ace`), actor_id, occurred_at, summary, data jsonb (call outcome, message id, old→new stage…), disposition |
| `tasks` | lead_id / deal_id, title, due_at, owner_user_id, status (`open` / `done` / `cancelled`), priority, created_from (`manual` / `sla_rule` / `sequence` / `ace`), completed_at |
| `sla_rules` | trigger (stage entered, lead created), within_minutes, action (create task / alert manager / reassign) |

## 3. Pipelines, deals, customers, documents (Phase 2)

| Table | Key columns |
| --- | --- |
| `pipelines` | name (one per course / product / program), is_default |
| `pipeline_stages` | pipeline_id, name, order, probability, `is_won`, `is_lost` |
| `deals` | lead_id, pipeline_id, stage_id, owner_user_id, title, value_minor + currency, expected_close_date, won_at / lost_at, lost_reason_id, custom_fields |
| `lost_reasons` | per-tenant list, mandatory on lost |
| `products` | name, code, price_minor + currency, is_active (course catalogue) |
| `deal_products` | deal_id, product_id, quantity, price_minor |
| `customers` | lead_id (unique — conversion keeps full history), customer_since, status, custom_fields |
| `document_requirements` | product_id or global, name (Aadhaar, Passport, Photo), required |
| `documents` | customer_id / lead_id, requirement_id, file key (S3), filename, size, status (`pending` / `received` / `verified` / `rejected`), uploaded_via (`link` / `user`) |
| `form_links` | registration / document-upload links: token hash, expires_at, used_at |

## 4. Sequences, messaging, inbox (Phase 3) — outline

`sequences`, `sequence_steps`, `sequence_enrollments`, `message_templates`, `email_domains`, `whatsapp_accounts`, `whatsapp_templates`, `conversations`, `messages`, `suppression_list`, `canned_replies`. Detailed in the Phase 3 plan.

## 5. API and webhooks (Phase 4) — outline

`api_keys`, `webhook_endpoints`, `webhook_deliveries`, `api_logs`. Detailed in the Phase 4 plan.

---

## Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| DM1 | People at an organisation lead: separate "contacts" table, or person leads linked to the organisation (`organisation_id`)? | **Person leads linked to the organisation.** One kind of person record, one timeline, works with grouping (#14) |
| DM2 | Default duplicate policy (R5) | **Update the existing lead** + "Re-enquiry" activity |
| DM3 | Minimum data (R1) | **Phone or email required**; name optional |
| DM4 | Phone normalization needs the `phonenumbers` library (new dependency) | Approve |
| DM5 | Soft-deleted leads: keep forever or purge after N days? | **Open** — 90-day purge rejected; awaiting Suyog's rule |

# Versnq Core — Master Roadmap

The single checklist for building Core. Source of truth for features: the spec (`docs/specs/`) and its Decision log.

**How we work through this file**

1. Work top to bottom. A phase starts only when the previous phase's **Gate** is ticked.
2. Before a phase starts, its detailed plan is written to `docs/plans/phase-N-<name>.md` (writing-plans skill) and approved by Suyog.
3. Every item is built test-first (test-driven-development skill): write the test → see it fail → build → see it pass.
4. Tick `[x]` only after the item's tests are run and green (verification-before-completion skill). Never tick on "should work".
5. Every **Test:** line is its own tick. One commit per ticked item.
6. **Gate** = all tests green + Suyog reviews and approves. No gate, no next phase.

**Current build order (2026-11-09):** `docs/plans/build-plan.md` lists every spec feature with its status and the step that builds it. It moves custom record types and links (2.17) ahead of deals, and adds in-app notifications (step 1), which were missing.

Legend: `[ ]` to do · `[x]` done and verified · `⏸` parked

---

## Phase 0 — Project setup

- [x] 0.1 Git repository initialised, `.gitignore`, first commit
- [x] 0.2 Decisions confirmed (see "Decisions needed before Phase 0" below)
- [x] 0.3 Folder structure created (see "Proposed folder structure")
- [x] 0.4 `docker-compose.yml`: Postgres 16 + Redis for local dev and tests
  - [x] Test: both containers start and report healthy
- [x] 0.5 Backend skeleton: FastAPI app, settings from env vars, `/health` endpoint
  - [x] Test: `/health` returns ok and confirms DB + Redis reachable
- [x] 0.6 Alembic set up against Postgres (empty baseline migration)
  - [x] Test: upgrade and downgrade both run cleanly
- [x] 0.7 Test harness: pytest on a real Postgres test database, fresh schema per run
  - [x] Test: a sample test passes; the suite refuses to run against a non-test DB
- [x] 0.8 Worker skeleton (Redis queue) with one sample job
  - [x] Test: a job is queued, picked up and completed
- [x] 0.9 `.env.example` complete; no secret in the repo
  - [x] Test: secret scan of the repo is clean
- [x] 0.10 `Makefile` / scripts: `dev`, `test`, `migrate`, `lint`
- [x] **Gate 0:** whole setup runs from a clean clone with one command; Suyog approves

## Phase 1 — Foundation (Milestone 1)

### 1A Backend

- [x] 1.1 Platform staff (Versnq super-admins): model, login, sessions separate from tenant sessions
  - [x] Test: staff token rejected on tenant routes and vice versa
- [x] 1.2 Tenants (companies): create, list, view, update, suspend; one-step provisioning (company + first Owner + invite + default roles + industry labels)
  - [x] Test: provisioning is all-or-nothing (failure leaves nothing behind)
  - [x] Test: suspended tenant cannot log in
- [x] 1.3 Tenant isolation: `tenant_id` on every business table + Postgres row-level security + app-level filter
  - [x] Test: tenant A can never read or write tenant B's rows (API and direct SQL)
  - [x] Test: cross-tenant IDs return 404, not 403
  - [x] Test: a query without tenant context returns nothing
- [x] 1.4 Users: invite, accept invite, login, logout, logout-all, refresh, forgot/reset password, temporary password with forced change
  - [x] Test: invite and reset links are single use and expire
  - [x] Test: password change revokes all sessions
- [x] 1.5 2FA (TOTP) for Owner and Admin
  - [x] Test: Owner/Admin cannot reach protected routes without the second factor
- [x] 1.6 Roles and permissions: permission codes, default roles (Owner, Admin, Sales Manager, Sales User, Finance), custom roles, scope own / team / all
  - [x] Test: deny by default for every unknown permission
  - [x] Test: Sales User sees only own records; Manager sees team; Owner/Admin see all
  - [x] Test: nobody can raise their own role; a tenant always keeps one Owner
- [x] 1.7 Teams: teams and manager hierarchy of any depth, no size limits
  - [x] Test: a manager sees every level below, never sideways or above
- [x] 1.8 Tenant settings: industry labels (Lead → "Student" etc.), timezone, branding
  - [x] Test: labels are per tenant and never leak across tenants
- [x] 1.9 Feature flags per tenant (module on/off)
  - [x] Test: a switched-off module's endpoints return 404 and emit no events
- [x] 1.10 Audit log: who changed what, when, before/after; staff audit separate from tenant audit
  - [x] Test: every write in 1.1–1.9 produces an audit row; secrets never stored
- [x] 1.11 Event bus foundation (internal events table + catalogue from the spec)
  - [x] Test: events are written in the same transaction as the change
- [x] 1.12 Route safety net: every route requires auth unless on an explicit public list
  - [x] Test: walking all routes finds no unlisted public route and no staff/tenant guard mix
- [x] 1.13 OpenAPI spec published and versioned
  - [x] Test: spec generates without errors and matches the routes

### 1B Frontend (after the UI discussion)

- [x] 1.14 UI decisions agreed (component library, layout, theme)
- [x] 1.15 Next.js skeleton + typed API client generated from the OpenAPI spec
- [x] 1.16 Staff console: login, companies list, create / edit / suspend company, staff audit
- [x] 1.17 Tenant app: login, invite accept, reset password, 2FA, users, roles, teams, settings and labels
  - [x] Test: end-to-end — create company → owner accepts invite → adds a Sales User → user sees only allowed screens
- [x] 1.18 Phase 1 review fixes (from the 2026-11-07 audit against the spec)
  - [x] Works in phone browsers: slide-in menu, tables scroll in place (spec §12, Decision log #19)
  - [x] Turn off 2FA with password + current code (`POST /auth/2fa/disable`; in the approved proposal, missed in the 1-B plan)
  - [x] Security headers on both apps (no framing, nosniff, referrer policy) — e2e checked
  - [x] My account: change password, 2FA on/off, sign out of all devices
  - [x] Demo data (`make demo-reset`) and dev-only `DEMO_SKIP_2FA` for invented demo accounts
- [x] **Gate 1:** all tests green, Suyog walks the flow end to end and approves (2026-11-07: "let's start with phase 2")

## Before the first real client (go-live)

- [ ] G.1 Real email sending for invites and password resets (pull the transactional part of 3.2 forward; provider needs Suyog's approval)
- [ ] G.2 Lost-phone recovery: one-time backup codes; Owner/Admin can reset a user's 2FA; staff can reset an Owner's 2FA (audited)
- [ ] G.3 Deployment: hosting, HTTPS + HSTS at the proxy, backend reachable only through the proxy (TRUST_PROXY_HEADERS; nginx must append the visitor address with `$proxy_add_x_forwarded_for`), encrypted database storage (spec §10 "encrypted at rest"), daily backups with a tested restore, error monitoring
- [ ] **Gate G:** a real company can be created, invited and used over HTTPS; Suyog approves

## Phase 2 — Core CRM (Milestone 2)

- [x] 2.1 Leads: create, edit, person or linked to a company/account; custom fields; source and UTM; origin tag
- [x] 2.2 Lead capture: web form / webhook endpoint per source, manual quick-add, CSV import with field mapping (step 1)
- [x] 2.3 De-duplication on phone and email + merge tool (step 1)
- [x] 2.3b Group person leads under organisation leads by domain / company name (suggest, optional auto-link; Decision log #14) (step 1)
- [x] 2.4 Consent capture (WhatsApp and email opt-in with timestamp) + suppression list (step 1)
- [x] 2.5 Auto-assignment: round-robin and rule-based routing (step 1)
- [x] 2.6 Leakage guard: untouched in X hours → alert or reassign (step 1)
- [x] 2.7 Activity timeline + custom activity types ("everything is an activity")
- [x] 2.8 Tasks and follow-ups, follow-up SLAs and escalation, call logging with dispositions — *slice A + step 1 (response-time rules, escalation, in-app notifications)*
- [x] 2.9 Pipelines, stages, deals, kanban moves, won/lost reasons, products / catalogue (step 3, Decision log #25)
- [x] 2.10 Convert lead → customer, document checklist and vault (files on our server, #29; step 5, #32). No customer upload link: staff upload only (#33)
- [x] 2.11 Tags, lists, smart views, bulk actions, rule-based lead scoring (step 4, Decision log #27; lists = tags + saved views)
- [x] 2.11b Automation builder: WHEN event IF conditions THEN actions (task, field, owner, stage, webhook) — Decision log #16
- [x] 2.12 Dashboards: Salesperson ("My Day"), Sales Manager, Owner/Admin (non-money parts) — *My Day with the calling queue done in slice A*
- [x] 2.13 CSV export
- [ ] 2.14 Frontend for 2.1–2.13
- [x] 2.15 Record page layouts per company (slice G)
- [x] 2.16 Field-level permissions: view / edit / hidden / mandatory per role (slice G)
- [x] 2.17 Custom record types (custom objects) on the same generic engine, plus labelled links between any records (step 2, moved up)
- Each item gets its own Test lines in the Phase 2 detailed plan (isolation + visibility tests on every item)
- [ ] **Gate 2:** all tests green, Suyog approves

## Phase 3 — Sequences + Inbox (Milestone 3)

- [x] 3.1 Sequence engine: steps, delays, conditions, branches, auto-enroll triggers, stop rules, quiet hours, throttling
- [ ] 3.2 Email: ESP integration, multi-domain (SPF/DKIM/DMARC), templates with variables, open/click tracking, unsubscribe and suppression
- [x] 3.3 Unified inbox (email first): threads per lead, assignment and handoff, canned replies
- [ ] 3.4 WhatsApp Cloud API: tenant's own number, template management, 24-hour window, opt-out, quality rating and tier display
- [ ] 3.5 Inbound WhatsApp from unknown number creates a lead
- [ ] 3.6 WhatsApp in sequences and the unified inbox
- [ ] 3.7 LinkedIn steps as rep tasks
- [x] 3.8 Sequence analytics per step
- [ ] 3.9 Frontend for 3.1–3.8
- [ ] 3.10 Multi-brand: several brands and sending domains in one company (spec §10, v1 — was missing from the roadmap)
- [ ] **Gate 3:** all tests green, Suyog approves

## Phase 4 — API, webhooks and ACE endpoints (Milestone 4)

- [x] 4.1 Public REST API with API keys per tenant, rate limits
- [x] 4.2 Outbound webhooks: admin picks events + URL, signed JSON, retries with backoff
- [x] 4.3 API and webhook logs with payload viewer
- [x] 4.4 ACE-facing endpoints: lead upsert from ACE (positive reply → hot/warm lead), append conversation to an existing lead, `lead.intent_changed` (`call.analyzed` endpoint later with call analysis, Decision log #37)
- [x] 4.5 Frontend for API keys, webhooks and logs
- [ ] **Gate 4:** all tests green, Suyog approves

## Money (unparked 2026-11-10, Decision log #24; build step 6, after customers)

- [x] M.1 Billing entities (legal company, country, tax ids, invoice numbering) and currencies (any ISO 4217, Decision log #2)
- [x] M.2 Invoices: line items from the deal's products, tax fields (GST), totals in minor units, numbering per entity, PDF
- [x] M.3 Installment plans: schedule of amounts and due dates per customer or deal
- [x] M.4 Payment links and gateway webhooks: Razorpay (India), Stripe (UAE/US); paid automatically on webhook; duplicate webhooks safe
- [x] M.5 Manual payments (bank transfer) with proof upload; balances paid / due / overdue
- [x] M.6 Receipts, reminders (before due, on due, overdue), collections aging; events invoice.created, payment.due, payment.received, payment.overdue
- [x] M.7 Finance role: sees invoices, payments, reminders (spec Roles); every money calculation tested
- [ ] **Gate M:** all tests green (every money calculation), Suyog approves

## Add-ons in the lineup

- [x] Key accounts (Decision log #31, after step 7): opportunity grid by budget holder, competitor status, relationship depth, account plan, group tree
- ⏸ Client / sponsor portal: not now (Decision log #31; end customers do not log in, #12)

## Security and data protection (after Phase 2)

- [ ] S.1 Login history (who, when, IP, device) and admin "sign out everyone"
- [ ] S.2 Auto sign-out after idle time, set per company
- [ ] S.3 IP allowlist per company (optional)
- [ ] S.4 Email alert to the user after repeated failed sign-ins
- [ ] S.5 India DPDP readiness: export everything a company owns; full erasure when a company leaves; breach-notice runbook

## Phase 5 — MCP layer ⏸ (design when asked)

- ⏸ 5.1 MCP server over the REST API (read tools first, write tools with confirmation)

## Parked ⏸

- ⏸ Later items in the spec: ad lead forms, Google Workspace, Zapier/n8n, HubSpot/LeadSquared import, A/B testing, SMS, PWA, custom reports
- ⏸ Future discussion (Decision log #29): outside file storage (S3 or similar), only when a big client or a second server needs it
- ⏸ Not now (2026-11-07 review): single sign-on (Google / Microsoft), custom password rules

---

## Decisions needed before Phase 0

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Backend language | ✅ FastAPI (Python) |
| D2 | Python version | ✅ 3.12, managed by uv (system 3.14 untouched) |
| D3 | Local infra | ✅ Docker Compose: Postgres 16 (5433) + Redis 7 (6380); app runs on host |
| D4 | Package manager | ✅ uv (installed in ~/.local/share/uv-tool; Homebrew belongs to another macOS user) |
| D5 | Worker | ✅ arq |
| D6 | Lint / format | ✅ ruff |
| D7 | WhatsApp connection | Direct Meta Cloud API (needed by Phase 3, not now) |

## Proposed folder structure

```
CORE/
├── CLAUDE.md
├── docker-compose.yml
├── Makefile
├── .env.example
├── docs/
│   ├── specs/          # product spec + decision log
│   └── plans/          # ROADMAP.md + one detailed plan per phase
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/       # config, db, security, tenancy, permissions
│   │   ├── platform/   # staff console: staff users, tenants, provisioning
│   │   ├── modules/    # one folder per module (auth, users, roles, teams, settings, leads, ...)
│   │   ├── events/     # event bus + catalogue
│   │   └── workers/    # background jobs
│   ├── migrations/     # Alembic
│   └── tests/          # pytest on real Postgres
└── frontend/           # Next.js (created in Phase 1B)
```

## Progress log

| Date | Item | Note |
| --- | --- | --- |
| 2026-11-05 | — | Roadmap created |
| 2026-11-05 | 0.1–0.10 | Phase 0 built and verified: 11 tests green on Postgres, lint clean, gitleaks clean, fresh-clone `make setup && make test` green. Gate 0 approved by Suyog |
| 2026-11-05 | Phase 1 | Proposal written and approved |
| 2026-11-05 | 1-A | Slice 1-A built: DB roles (app cannot bypass RLS), tenant context, tenants/settings/roles/users with forced RLS + tripwire, industry packs, staff login with refresh rotation + reuse detection, one-step provisioning, append-only platform audit. 89 tests green; live run verified. Staff 2FA, suspended-workspace block and API cross-tenant tests done in 1-B |
| 2026-11-05 | 1-B | Slice 1-B built: workspace from web address, user login/refresh/logout(-all), invites, reset, change password, temporary-password and 2FA restrictions, TOTP 2FA for users + staff (staff actions require it), Redis rate limits. 127 tests green. Cross-tenant ID 404 done in 1-C |
| 2026-11-05 | 1-C | Slice 1-C built: permission catalogue + deny-by-default, default/custom roles, anti-escalation, teams of any depth with visibility (own/team/all), user management, tenant audit log (moved forward from 1.10). 159 tests green. **Harness bug found and fixed:** one test run wrote ~76 junk tenants into the dev DB (shared fixtures imported before the test DB switch); added an engine guard proven to stop such a run, and rebuilt the dev DB |
| 2026-11-05 | 1-D | Slice 1-D built: settings editing (labels/timezone/locale/country/branding), module switches (money and ace off by default, crm always on, 404 + no events when off), events outbox with the spec's 20-event catalogue, audit of self-service security actions, route tripwire (self-checked against the API spec), committed OpenAPI spec (`make openapi`). 184 tests green. **Phase 1 backend (1A) complete**; 1B frontend waits for the UI discussion |
| 2026-11-07 | 1B + review | Both apps built (client admin pages, staff console), Gate 1 e2e test on its own database, demo data. Audit against the spec found 4 gaps (phones, 2FA off, framing headers, My account) — fixed. Go-live items (G.1–G.3), multi-brand (3.10) and security/DPDP items (S.1–S.5) added to the roadmap. 209 tests + 3 e2e green |
| 2026-11-07 | Gate 1 / Phase 2 | Gate 1 approved. Email/go-live deferred until the product is built (Suyog). Phase 2 plan written (`phase-2-crm.md`): slices A–F, slice A in detail, 6 open questions |
| 2026-11-07 | 2-A | Slice A built: stages, sources, custom fields (linked, unique, stage-required), activity types, leads (person/company, identities in E.164, visibility, assign, delete), timeline, follow-up rule (strict/warn), one-step call logging, tasks, My Day with calling queue, task.due worker, pipeline setup screens, demo data (300 + 60 leads). 249 backend tests + 4 e2e green |
| 2026-11-09 | 2.2–2.6, 2.8 | Step 1 (capture and routing) built and verified: one intake path for every entry route, duplicates + merge, consent + suppression, organisation grouping, assignment rules, response-time rules, leakage guard, notifications, web forms, CSV import; 309 backend tests, 5 e2e, 23-check browser walk. Two bugs found in the walk and fixed with tests |
| 2026-11-09 | 2.17 | Step 2 (records and links) built and verified: company-defined record types with fields, stages and access per role; labelled links between leads and records; tasks and notes on records; EdTech pack seeds Batch; 324 backend tests, 6 e2e, 20-check browser walk. Found and fixed: per-address rate limits were shared by everyone behind the proxy |
| 2026-11-10 | Money | Unparked by Suyog (Decision log #24): added to the lineup as step 6, after customers and before dashboards |
| 2026-11-10 | 3 | Deals and pipelines built (Decision log #25): several pipelines (one currency each), stages with win %, deals on a lead with exact amounts, drag board with per-stage value and weighted forecast, lost needs a reason, product catalogue with deal lines, deals linked to records (Property, Batch), deal timeline/tasks, Deals card on the lead, Deals settings. 342 backend tests + 6 e2e + 26-check browser walk green |
| 2026-11-11 | 4 | Tags (leads, deals; bulk), saved views (private/team/everyone, live counts), fit + engagement scoring with Hot/Warm/Cold and a breakdown, calculated fields (safe formula parser, exact money), automation builder (WHEN/IF/THEN, worker every 5 s, run history, test on a lead, loop guard, auto switch-off, signed webhooks). Message tracking and a Smartlead connector added to the lineup (#28). 366 backend tests + 6 e2e + 26-check walk green |
| 2026-11-12 | UI | New look (Decision log #30): grey page with white panels, soft shadows, Inter, big titles and numbers; lead, deal and record pages as cards; My Day with number tiles; frosted top bar; dark mode matched; lists and board stay compact. Files on our server (#29); Key accounts in the lineup (#31). 6 e2e + 26-check walk green |
| 2026-11-12 | 5 | Customers and documents: make customer (won deal or lead), numbered per company, same record and timeline; Customers list; checklist per company or per product (packs ship one); upload, preview, verify / reject with reason; staff-only uploads (customer link removed, #33); photos shrunk in the browser; files on our server with 2 GB quota; Finance reads all customers; nightly reminders and file clean-up. Also fixed: merging leads deleted the other lead's deals, tags and links. 376 backend tests + 6 e2e + 30-check walk (step 4 walk still green) |
| 2026-11-12 | 6 | Money (Decision log #34): billing entities with gapless numbering (yearly reset), tax rates with parts from the pack, invoices draft → issued → paid / void, exact installments, payments oldest first with proof, reversals, balances per currency, aging; Razorpay / Stripe links with signed webhooks and a nightly check; pay directly with bank details and a UPI QR; invoice, receipt, reminder and cancellation emails from the company's own mailbox; reminders, overdue tasks, repeat invoices. 406 backend tests + 6 e2e + 30-check walk green |
| 2026-11-12 | 7 | Dashboards (Decision log #35): My numbers, Team (funnel, sources, leaderboard, leakage, slow responses, lost reasons), Business (booked vs collected, forecast, 6-month trend), Money (invoiced, collected, due, overdue, aging, by method and entity, who owes most); periods in the company's time zone with the change vs before; numbers open their lists. CSV export of leads, deals, customers, invoices and payments, one permission per list (Owner / Admin by default), formula-safe, audited, admins alerted. 417 backend tests + 6 e2e + 24-check walk green |
| 2026-11-12 | 7b | B2B / SaaS industry pack and the Brightlane Software demo company (28 invented client companies, contacts, seat-priced opportunities, clients, yearly invoices). Key accounts add-on (Decision log #36): marked organisations with tier, owner, target and health hints; group tree with per-currency roll-ups; departments with budget holders; opportunity grid from real deals plus competitor / not-a-fit cells, deals started from the grid; competitors; people map; account plan. 424 backend tests + 6 e2e + 30-check walk green |

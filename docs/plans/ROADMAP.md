# Versnq Core — Master Roadmap

The single checklist for building Core. Source of truth for features: the spec (`docs/specs/`) and its Decision log.

**How we work through this file**

1. Work top to bottom. A phase starts only when the previous phase's **Gate** is ticked.
2. Before a phase starts, its detailed plan is written to `docs/plans/phase-N-<name>.md` (writing-plans skill) and approved by Suyog.
3. Every item is built test-first (test-driven-development skill): write the test → see it fail → build → see it pass.
4. Tick `[x]` only after the item's tests are run and green (verification-before-completion skill). Never tick on "should work".
5. Every **Test:** line is its own tick. One commit per ticked item.
6. **Gate** = all tests green + Suyog reviews and approves. No gate, no next phase.

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
- [ ] **Gate 0:** whole setup runs from a clean clone with one command; Suyog approves

## Phase 1 — Foundation (Milestone 1)

### 1A Backend

- [ ] 1.1 Platform staff (Versnq super-admins): model, login, sessions separate from tenant sessions
  - [ ] Test: staff token rejected on tenant routes and vice versa
- [ ] 1.2 Tenants (companies): create, list, view, update, suspend; one-step provisioning (company + first Owner + invite + default roles + industry labels)
  - [ ] Test: provisioning is all-or-nothing (failure leaves nothing behind)
  - [ ] Test: suspended tenant cannot log in
- [ ] 1.3 Tenant isolation: `tenant_id` on every business table + Postgres row-level security + app-level filter
  - [ ] Test: tenant A can never read or write tenant B's rows (API and direct SQL)
  - [ ] Test: cross-tenant IDs return 404, not 403
  - [ ] Test: a query without tenant context returns nothing
- [ ] 1.4 Users: invite, accept invite, login, logout, logout-all, refresh, forgot/reset password, temporary password with forced change
  - [ ] Test: invite and reset links are single use and expire
  - [ ] Test: password change revokes all sessions
- [ ] 1.5 2FA (TOTP) for Owner and Admin
  - [ ] Test: Owner/Admin cannot reach protected routes without the second factor
- [ ] 1.6 Roles and permissions: permission codes, default roles (Owner, Admin, Sales Manager, Sales User, Finance), custom roles, scope own / team / all
  - [ ] Test: deny by default for every unknown permission
  - [ ] Test: Sales User sees only own records; Manager sees team; Owner/Admin see all
  - [ ] Test: nobody can raise their own role; a tenant always keeps one Owner
- [ ] 1.7 Teams: teams and manager hierarchy of any depth, no size limits
  - [ ] Test: a manager sees every level below, never sideways or above
- [ ] 1.8 Tenant settings: industry labels (Lead → "Student" etc.), timezone, branding
  - [ ] Test: labels are per tenant and never leak across tenants
- [ ] 1.9 Feature flags per tenant (module on/off)
  - [ ] Test: a switched-off module's endpoints return 404 and emit no events
- [ ] 1.10 Audit log: who changed what, when, before/after; staff audit separate from tenant audit
  - [ ] Test: every write in 1.1–1.9 produces an audit row; secrets never stored
- [ ] 1.11 Event bus foundation (internal events table + catalogue from the spec)
  - [ ] Test: events are written in the same transaction as the change
- [ ] 1.12 Route safety net: every route requires auth unless on an explicit public list
  - [ ] Test: walking all routes finds no unlisted public route and no staff/tenant guard mix
- [ ] 1.13 OpenAPI spec published and versioned
  - [ ] Test: spec generates without errors and matches the routes

### 1B Frontend (after the UI discussion)

- [ ] 1.14 UI decisions agreed (component library, layout, theme)
- [ ] 1.15 Next.js skeleton + typed API client generated from the OpenAPI spec
- [ ] 1.16 Staff console: login, companies list, create / edit / suspend company, staff audit
- [ ] 1.17 Tenant app: login, invite accept, reset password, 2FA, users, roles, teams, settings and labels
  - [ ] Test: end-to-end — create company → owner accepts invite → adds a Sales User → user sees only allowed screens
- [ ] **Gate 1:** all tests green, Suyog walks the flow end to end and approves

## Phase 2 — Core CRM (Milestone 2)

- [ ] 2.1 Leads: create, edit, person or linked to a company/account; custom fields; source and UTM; origin tag
- [ ] 2.2 Lead capture: web form / webhook endpoint per source, manual quick-add, CSV import with field mapping
- [ ] 2.3 De-duplication on phone and email + merge tool
- [ ] 2.4 Consent capture (WhatsApp and email opt-in with timestamp)
- [ ] 2.5 Auto-assignment: round-robin and rule-based routing
- [ ] 2.6 Leakage guard: untouched in X hours → alert or reassign
- [ ] 2.7 Activity timeline + custom activity types ("everything is an activity")
- [ ] 2.8 Tasks and follow-ups, follow-up SLAs and escalation, call logging with dispositions
- [ ] 2.9 Pipelines, stages, deals, kanban moves, won/lost reasons, products / catalogue
- [ ] 2.10 Convert lead → customer, registration form link, document checklist and vault (S3)
- [ ] 2.11 Tags, lists, smart views, bulk actions, rule-based lead scoring
- [ ] 2.12 Dashboards: Salesperson ("My Day"), Sales Manager, Owner/Admin (non-money parts)
- [ ] 2.13 CSV export
- [ ] 2.14 Frontend for 2.1–2.13
- Each item gets its own Test lines in the Phase 2 detailed plan (isolation + visibility tests on every item)
- [ ] **Gate 2:** all tests green, Suyog approves

## Phase 3 — Sequences + Inbox (Milestone 3)

- [ ] 3.1 Sequence engine: steps, delays, conditions, branches, auto-enroll triggers, stop rules, quiet hours, throttling
- [ ] 3.2 Email: ESP integration, multi-domain (SPF/DKIM/DMARC), templates with variables, open/click tracking, unsubscribe and suppression
- [ ] 3.3 Unified inbox (email first): threads per lead, assignment and handoff, canned replies
- [ ] 3.4 WhatsApp Cloud API: tenant's own number, template management, 24-hour window, opt-out, quality rating and tier display
- [ ] 3.5 Inbound WhatsApp from unknown number creates a lead
- [ ] 3.6 WhatsApp in sequences and the unified inbox
- [ ] 3.7 LinkedIn steps as rep tasks
- [ ] 3.8 Sequence analytics per step
- [ ] 3.9 Frontend for 3.1–3.8
- [ ] **Gate 3:** all tests green, Suyog approves

## Phase 4 — API, webhooks and ACE endpoints (Milestone 4)

- [ ] 4.1 Public REST API with API keys per tenant, rate limits
- [ ] 4.2 Outbound webhooks: admin picks events + URL, signed JSON, retries with backoff
- [ ] 4.3 API and webhook logs with payload viewer
- [ ] 4.4 ACE-facing endpoints: lead upsert from ACE (positive reply → hot/warm lead), append conversation to an existing lead, `lead.intent_changed`, `call.analyzed`
- [ ] 4.5 Frontend for API keys, webhooks and logs
- [ ] **Gate 4:** all tests green, Suyog approves

## Phase 5 — MCP layer ⏸ (design when asked)

- ⏸ 5.1 MCP server over the REST API (read tools first, write tools with confirmation)

## Parked ⏸

- ⏸ Money: invoices, installments, payment links, gateways, balances, reminders, money dashboard (any country / currency when unparked)
- ⏸ Later items in the spec: ad lead forms, Google Workspace, Zapier/n8n, HubSpot/LeadSquared import, A/B testing, SMS, PWA, custom reports, field-level permissions

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
| 2026-11-05 | 0.1–0.10 | Phase 0 built and verified: 11 tests green on Postgres, lint clean, gitleaks clean, fresh-clone `make setup && make test` green. Awaiting Gate 0 approval |

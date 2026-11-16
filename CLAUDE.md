# CLAUDE.md — Versnq Core

Read this file and `docs/specs/Versnq Core — Product & Feature Spec (v0).md` (the spec) before every task. The spec is the source of truth for features; its "Decision log" section overrides older text in the spec and in this file. If anything here conflicts with the spec, stop and ask.

## What we're building

**Versnq Core** is a generic, multi-tenant CRM sold as monthly SaaS. It runs one tree for every business:

Lead → Follow-up → Deal → Customer → Invoice / installment plan → Payment → Balance → Reminders → Money dashboard

Email sequences, WhatsApp sequences, the unified inbox, tasks and every activity live inside Core. Money (invoices, installments, payments, balances) is part of Core, not an add-on.

**Versnq ACE** (the AI conversation engine) is a separate product that attaches to Core later. Do not build ACE features unless explicitly asked.

## Non-negotiable rules

1. **Multi-tenant from day one.** Every business table has `tenant_id`. Enforce isolation with Postgres row-level security. Never write a query that can return another tenant's data.
2. **One generic tree.** Industry differences (EdTech "Student", real estate "Buyer", fintech "Applicant") are configuration: labels, custom fields, pipeline stages, templates and seed data. Never write `if industry == ...` branches in code.
3. **Customer tweaks go through settings and custom fields.** Never fork code for one customer.
4. **Core never depends on ACE or any add-on.** Add-ons depend on Core and communicate through Core's events.
5. **Everything is an activity.** Every email, WhatsApp message, call, note, stage change, invoice and payment writes an activity on the lead/customer timeline.
6. **Every important change emits an event** (see the event catalogue in the spec) so webhooks and add-ons can subscribe.
7. **Money is exact.** Store amounts as integers in minor units (paise, fils, cents) with an explicit currency code. Never use floats for money.
8. **Respect messaging rules.** WhatsApp: first business-initiated message must be an approved template; free-form only inside the 24-hour window; honour opt-outs. Email: honour unsubscribes and suppression lists.

## Tech stack

- Backend: Python, FastAPI
- Database: PostgreSQL (Supabase acceptable), row-level security, Alembic migrations
- Background jobs: Redis + a worker (Celery or RQ) for sends, retries, reminders and scheduled triggers
- Frontend: Next.js (React, TypeScript)
- Auth: per-tenant organisations with role-based access
- File storage: our own server's disk, with the file record (path, name, size, type) in Postgres (Decision log #29). Outside object storage (S3 or similar) is a future discussion, not now.
- Payments: Razorpay (India), Stripe (UAE/US), via their webhooks
- Email: an ESP with multi-domain support
- WhatsApp: WhatsApp Cloud API, using each tenant's own number and credentials

Ask before adding any dependency not listed here.

## Roles

Owner, Admin, Sales Manager, Sales User, Finance.

- Sales User sees only leads they own.
- Sales Manager sees their team.
- Owner and Admin see everything.
- Finance sees invoices, payments and reminders.

Enforce visibility in the backend, not only in the UI.

## Build order (one milestone at a time)

1. **Foundation:** tenants, users, auth, roles, permissions, tenant settings (industry labels), audit log
2. **Core CRM:** lead capture and routing, lead 360 + timeline, tasks, pipelines and deals, customers, dashboards
3. **Sequences + inbox:** email first, then WhatsApp
4. **API and webhooks:** REST API, outbound signed webhooks with retries, API logs, ACE-facing endpoints (lead upsert, conversation logging)
5. **MCP layer:** design only when asked; do not build yet
6. **ACE integration:** only when asked

**Money** (invoices, installment plans, payment links, gateway webhooks, balances, reminders, money dashboard) was parked and is now in the lineup (Decision log #24): it is built after customers and documents, before dashboards. Rule 7 applies.

Do not start a milestone until the previous one runs and is approved.

## How to work

- **Plan before code.** For each milestone, first propose the schema, endpoints, screens and open questions. Wait for approval.
- **Schema changes need approval.** Always via migrations; never edit the database by hand.
- **Small commits** with clear messages, one logical change each.
- **Tests:** write tests for permissions, tenant isolation and every money calculation. Run them before saying a task is done.
- **Secrets** come from environment variables only. Never commit keys; keep `.env.example` updated.
- **When unsure, ask.** Don't invent features or requirements that aren't in `docs/SPEC.md`.

## Out of scope for now

LMS integration, blog generation, LinkedIn send automation. Mention them only if asked.

Telephony and the phone app are **in scope since 2026-11-16** (Suyog): one call pipeline fed by the company's own Twilio and by our Android app reading the phone's own recorder folder. Plan: `docs/plans/calls-plan.md`.

## Coding guidelines (from andrej-karpathy-skills, MIT)

Project rules above take precedence over these guidelines.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Project skills (`.claude/skills/`, copied verbatim from obra/superpowers v7.0.2, MIT)

Installed: writing-plans, test-driven-development, systematic-debugging, verification-before-completion, receiving-code-review. Load one only when the task needs it.
Any reference inside them to a skill not in `.claude/skills/` (e.g. `superpowers:using-git-worktrees`, `superpowers:executing-plans`, `superpowers:subagent-driven-development`, `superpowers:brainstorming`, `superpowers:writing-skills`) is not installed: ignore it and never guess its content. Execute plans inline, one milestone at a time, with approval as described above.

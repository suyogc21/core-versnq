# Phase 1 — Foundation: Proposal

Status: **awaiting approval** · Roadmap items 1.1–1.17 · Spec §10 + Decision log #6, #7, #10

This is the design for Phase 1 (schema, security model, endpoints, screens, tests, open questions). After approval, each slice below gets its own step-by-step plan (writing-plans skill) and is built test-first.

Patterns reused from AMS (reviewed 2026-11-05): permission codes + role scope + deny by default, anti-escalation rules, token design, 404 for cross-tenant IDs, public-route tripwire test, before/after audit rows, one-step tenant provisioning. Improved over AMS: Postgres RLS as a second wall, one database, tests on Postgres, feature flags, teams of any depth, editable custom roles, 2FA.

---

## 1. Security model (the most important decision)

**Three Postgres roles**

| Role | Used by | Can bypass RLS? |
| --- | --- | --- |
| `versnq_owner` | Alembic migrations only; owns all tables | n/a (owner) |
| `versnq_app` | The API and worker at runtime | **No** — `NOBYPASSRLS`, not table owner |
| `postgres` superuser | Docker container admin only, never used by code | — |

**Tenant isolation = two walls**

1. **App wall:** every tenant query goes through a helper that adds `tenant_id = :current_tenant`.
2. **Database wall (RLS):** every tenant table has `ENABLE` + `FORCE ROW LEVEL SECURITY` and one policy:
   `USING (tenant_id = current_setting('app.tenant_id', true)::uuid)` (same `WITH CHECK`).
   Each request runs in a transaction that starts with `SELECT set_config('app.tenant_id', :tid, true)` taken from the signed token. No tenant set → the setting is NULL → **zero rows**, never all rows.

**No code path uses BYPASSRLS.** Staff provisioning a tenant sets that new tenant's ID as context for the provisioning transaction. Staff screens read only platform tables (tenants, staff, platform audit).

**Visibility inside a tenant** (own / team / all) is enforced in the app layer on top of RLS (RLS = which tenant; app = which records within it).

## 2. Schema

UUID primary keys everywhere; `created_at`, `updated_at` (timestamptz) on every table.

### Platform tables (no `tenant_id`, no RLS, staff-only)

| Table | Key columns |
| --- | --- |
| `platform_staff` | email (unique), name, password_hash, is_active, totp_secret_enc, totp_enabled |
| `platform_staff_sessions` | staff_id, refresh_token_hash, expires_at, revoked_at, ip, user_agent |
| `platform_audit_log` | staff_id, action, target_type, target_id, tenant_slug_snapshot, before, after (jsonb), ip — append-only |
| `tenants` | name, slug (unique), status (`active` / `suspended`), industry_pack, timezone, created_by_staff_id |
| `tenant_modules` | tenant_id, module_key, enabled — feature flags |
| `permissions` | code (PK, e.g. `users.manage`), module_key, description — global catalogue, seeded |

### Tenant tables (`tenant_id` + RLS on every one)

| Table | Key columns |
| --- | --- |
| `users` | email (unique per tenant), name, phone, password_hash, status (`invited` / `active` / `disabled`), role_id, must_change_password, totp_secret_enc, totp_enabled, last_login_at |
| `user_sessions` | user_id, refresh_token_hash, expires_at, revoked_at, ip, user_agent |
| `auth_tokens` | user_id, kind (`invite` / `reset`), token_hash, expires_at (invite 72 h, reset 60 min), used_at — single use |
| `roles` | name, is_system, scope (`own` / `team` / `all`) |
| `role_permissions` | role_id, permission_code |
| `teams` | name, parent_team_id, path (`ltree`, for any-depth hierarchy) |
| `team_members` | team_id, user_id, is_manager |
| `tenant_settings` | labels (jsonb: singular/plural for lead, deal, customer, …), timezone, locale, branding (jsonb) |
| `audit_log` | actor_type (`user` / `staff` / `system` / `api`), actor_id, action, entity_type, entity_id, before, after (jsonb), ip — append-only (UPDATE/DELETE revoked from `versnq_app`) |
| `events` | type (from spec catalogue), payload (jsonb), occurred_at, published_at — written in the same transaction as the change (outbox) |

**Default roles seeded per tenant:** Owner (all, scope all, cannot be deleted, at least one always exists) · Admin (all except billing/ownership, scope all) · Sales Manager (scope team) · Sales User (scope own) · Finance (finance codes; mostly empty while Money is parked). Custom roles are created by copying and editing.

**Team visibility:** a manager of team T sees members of T and of every team below T (`path <@ T.path`), never sideways or above. No limit on depth or size.

**Industry packs (Phase 1):** `generic` and `edtech` label sets only (first client is EdTech). Packs are seed data, never code branches.

## 3. Auth design

- Login: workspace (tenant slug) + email + password → access JWT (15 min) + refresh token (opaque, stored hashed, rotated on every use, httpOnly cookie scoped to `/auth`).
- Token carries `typ` (`staff` / `user`), `sub`, `tenant_id`. Staff and user tokens never work on each other's routes.
- Password change or reset → all sessions revoked. Forgot-password always returns the same response.
- Temporary password from an admin → every route blocked until changed (server-enforced).
- 2FA (TOTP): required for Owner, Admin and all platform staff. Secrets encrypted at rest with a key from env.
- Login and reset endpoints rate-limited per IP + per account (Redis-backed, not in-memory).
- Emails (invites, resets) in Phase 1 go through a `Mailer` interface with a **console/outbox backend**; a real ESP plugs in during Phase 3 (see Q3).

## 4. Endpoints

**Platform (staff console)** — prefix `/platform`

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/login`, `/auth/2fa/verify`, `/auth/refresh`, `/auth/logout`, `GET /auth/me` |
| Tenants | `GET/POST /tenants`, `GET/PATCH /tenants/{id}`, `POST /tenants/{id}/suspend`, `/reactivate`, `/resend-owner-invite` |
| Modules | `GET/PUT /tenants/{id}/modules` |
| Staff | `GET/POST /staff`, `PATCH /staff/{id}` |
| Audit | `GET /audit` |

**Tenant app** — prefix `/api/v1`

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/login`, `/auth/2fa/verify`, `/auth/refresh`, `/auth/logout`, `/auth/logout-all`, `/auth/password/change`, `/auth/password/forgot`, `/auth/password/reset`, `/auth/invite/accept`, `/auth/2fa/setup`, `/auth/2fa/enable`, `/auth/2fa/disable`, `GET /auth/me` |
| Users | `GET/POST /users` (POST = invite), `GET/PATCH /users/{id}`, `POST /users/{id}/disable`, `/enable`, `/temporary-password` |
| Roles | `GET /permissions`, `GET/POST /roles`, `GET/PATCH/DELETE /roles/{id}` |
| Teams | `GET/POST /teams`, `GET/PATCH/DELETE /teams/{id}`, `PUT /teams/{id}/members` |
| Settings | `GET/PATCH /settings` (labels, timezone, branding), `GET /modules` (read-only) |
| Audit | `GET /audit` |

Public routes (no auth), enforced by a tripwire test: `/health`, login, 2FA verify, refresh, forgot, reset, invite accept.

## 5. Screens (Phase 1B — built after the UI discussion)

- **Staff console:** login + 2FA · tenants list (search, status) · create tenant (name, slug, industry pack, owner email) · tenant detail (modules on/off, suspend, resend invite) · staff accounts · audit
- **Tenant app:** login + 2FA · accept invite · forgot/reset password · forced password change · users · roles and permissions · teams tree · settings (labels, timezone, branding) · audit

## 6. Tests (all on real Postgres, connected as `versnq_app`)

- **Isolation:** tenant A cannot read/write tenant B through any endpoint; direct SQL as `versnq_app` with tenant A context returns zero B rows; no context returns zero rows; cross-tenant IDs → 404.
- **Visibility matrix:** each default role × own / team / other-team / other-tenant record.
- **Auth:** token type swap rejected; refresh rotation and reuse detection; single-use expiring invite/reset links; sessions revoked on password change; temporary password blocks routes; 2FA required for Owner/Admin/staff.
- **Anti-escalation:** cannot change own role; last Owner cannot be removed or demoted; cannot grant permissions you do not have.
- **Audit + events:** every write produces an audit row (no secrets inside) and its event in the same transaction.
- **Tripwire:** every route authenticated unless on the public list; staff and tenant guards never mixed.

## 7. Build slices (each = one detailed plan, built and verified in order)

| Slice | Covers roadmap | Delivers |
| --- | --- | --- |
| 1-A | 1.2, 1.3, 1.1 | DB roles + RLS framework, tenants, provisioning, platform staff auth |
| 1-B | 1.4, 1.5 | Tenant user auth: login, sessions, invites, reset, temporary password, 2FA |
| 1-C | 1.6, 1.7 | Roles, permissions, custom roles, teams, visibility scopes |
| 1-D | 1.8–1.13 | Settings + labels, feature flags, audit log, events outbox, route tripwire, OpenAPI |
| 1-E | 1.14–1.17 | UI decisions, Next.js, staff console, tenant app screens |

## 8. Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| Q1 | Can one email belong to several tenants (e.g. an agency person working for two clients)? | Yes: email unique **per tenant**; the workspace is chosen at login |
| Q2 | How does a user pick their workspace: subdomain (`acme.versnq.in`) or a workspace field on one login page? | Workspace field now (no DNS work); subdomains later if wanted |
| Q3 | Invites/resets need email. Use a console/outbox mailer in Phase 1 and pick the ESP in Phase 3, or pick the ESP now? | Console/outbox now; ESP in Phase 3 |
| Q4 | Should Versnq staff be able to "log in as" a tenant user for support? | Not in Phase 1. Later only with tenant consent + full audit |
| Q5 | Keep the Finance role while Money is parked? | Yes, seeded with read-only audit access; gains money permissions when unparked |
| Q6 | New dependencies | Approve: `PyJWT` (tokens), `argon2-cffi` (password hashing), `pyotp` (2FA), `cryptography` (encrypting 2FA secrets), `email-validator` (email fields) |
| Q7 | Docker change: the app currently connects as the Postgres superuser, which **bypasses RLS**. Phase 1 switches the app to `versnq_app` and migrations to `versnq_owner` | Approve (required for RLS to mean anything) |

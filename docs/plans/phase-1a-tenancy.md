# Phase 1-A — Tenancy, RLS and Platform Staff Implementation Plan

> **Execution:** inline in this session, task by task. Tick roadmap items only after their tests pass.

**Goal:** Versnq staff can log in to the platform API and create a client company in one step (company + settings + default roles + invited Owner), with every tenant table locked by Postgres row-level security.

**Architecture:** Migrations run as `versnq_owner`; the app runs as `versnq_app` (no RLS bypass). Each tenant-scoped transaction sets `app.tenant_id`; RLS policies compare against it. Platform tables have no `tenant_id` and are reachable only through `/platform` routes guarded by staff tokens.

**Tech Stack:** Phase 0 stack + `PyJWT`, `argon2-cffi`, `email-validator` (approved, Decision log #13).

**Spec:** `docs/plans/phase-1-foundation-proposal.md` (approved) · spec Decision log #6, #7, #12, #13.

## Global Constraints

- Every tenant table: `tenant_id uuid not null`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy `tenant_id = current_setting('app.tenant_id', true)::uuid` for USING and WITH CHECK.
- No code path uses BYPASSRLS or the `postgres` superuser.
- Cross-tenant or unknown IDs → **404**. Login failures → one generic message.
- Slugs: lowercase `a-z0-9-`, 3–30 chars, start with a letter, unique; reserved: `www, app, api, admin, platform, mail, static, assets`.
- Access token 15 min; refresh token 30 days, opaque, stored as sha256, rotated on every use; reusing a rotated refresh token revokes every session of that account.
- Secrets only from env: `JWT_SECRET`, `BASE_DOMAIN`, DB URLs.
- Staff 2FA arrives in slice 1-B; until then staff login is password-only (dev only).

## Review Focus

1. Tests passing only because they run as a superuser → every isolation test runs as `versnq_app`, and a test asserts `versnq_app` has `rolbypassrls = false` and owns no tables (Task 1).
2. Provisioning fails halfway (e.g. duplicate owner email or bad pack) → nothing is left behind: no tenant, no roles, no user (Task 6).
3. Slug edge cases: uppercase, spaces, reserved words, duplicates, 2 or 31 chars → 422 with a clear field error (Task 6).
4. Stolen refresh token used after the real user refreshed → all that staff member's sessions revoked (Task 5).
5. A tenant row inserted with a different tenant's ID while context is set → rejected by WITH CHECK, not silently stored (Task 3).

---

### Task 1: Database roles

Roadmap: 1.3 (part)

**Files:** Modify `docker/postgres/init/01-test-db.sql` → rename `01-roles-and-dbs.sql`; `.env.example`; `app/core/config.py`; `migrations/env.py`; `tests/conftest.py`. Create `tests/core/test_db_roles.py`.

**Interfaces — Produces:** `Settings.migration_database_url`, `Settings.test_migration_database_url` (owner role); `DATABASE_URL` / `TEST_DATABASE_URL` now use `versnq_app`.

- [ ] **Step 1: Failing tests:** `test_app_role_cannot_bypass_rls` (`SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user` → false), `test_app_role_owns_no_tables` (count of `pg_tables` owned by `current_user` in `public` = 0), `test_app_role_is_not_superuser`.
- [ ] **Step 2:** Run → FAIL (app currently connects as superuser `versnq`).
- [ ] **Step 3:** Init script creates roles `versnq_owner` (LOGIN, owns both DBs) and `versnq_app` (LOGIN, NOSUPERUSER, NOBYPASSRLS), default privileges so `versnq_app` gets SELECT/INSERT/UPDATE/DELETE on tables `versnq_owner` creates. Migrations use the owner URL. Recreate the local volume: `docker compose down -v && make up` (dev DB is empty, nothing lost).
- [ ] **Step 4:** Run full suite → all PASS (including Phase 0 tests).
- [ ] **Step 5:** Commit `feat(db): separate owner and app roles; app cannot bypass RLS`.

### Task 2: Tenant context and RLS helpers

Roadmap: 1.3 (part)

**Files:** Create `app/core/tenancy.py`, `migrations/helpers.py`, `tests/core/test_tenancy.py`.

**Interfaces — Produces:**
- `async def tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]` — opens a transaction and runs `SELECT set_config('app.tenant_id', :tid, true)` first.
- `async def platform_session() -> AsyncIterator[AsyncSession]` — transaction with no tenant set.
- `def enable_tenant_rls(table: str) -> None` (migration helper: enable + force RLS + create policy `tenant_isolation`).
- `def disable_tenant_rls(table: str) -> None` (for downgrades).

- [ ] **Step 1: Failing tests:** `test_tenant_session_sets_context` (`current_setting('app.tenant_id')` equals the UUID inside, and is empty in a new transaction afterwards — proves `is_local`), `test_platform_session_has_no_tenant` (setting is empty/NULL).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(core): tenant session context and RLS migration helpers`.

### Task 3: Tenants, settings, roles and users tables

Roadmap: 1.2, 1.3

**Files:** Create `app/platform/models.py` (`Tenant`), `app/modules/settings/models.py` (`TenantSettings`), `app/modules/roles/models.py` (`Role`), `app/modules/users/models.py` (`User` — columns from proposal §2; auth columns used in 1-B), `migrations/versions/0002_tenancy.py`, `tests/core/test_rls_isolation.py`, `tests/factories.py`.

**Interfaces — Produces:** ORM models above; `tenant_settings`, `roles`, `users` call `enable_tenant_rls`. `users` unique `(tenant_id, lower(email))`. Factory `async def make_tenant(slug: str) -> UUID` (inserts via owner connection, test-only).

- [ ] **Step 1: Failing tests** (all as `versnq_app`):
  - `test_context_a_sees_only_a_rows` — tenants A and B each have a role; inside `tenant_session(A)` selecting roles returns only A's.
  - `test_no_context_sees_zero_rows` — `platform_session()` selecting roles returns 0 rows.
  - `test_insert_with_other_tenant_id_rejected` — inside A's session, inserting a role with `tenant_id = B` raises an RLS violation.
  - `test_update_cannot_move_row_to_other_tenant` — updating A's role `tenant_id` to B raises.
  - `test_every_tenant_table_has_forced_rls` — query `pg_class` for every table with a `tenant_id` column → `relrowsecurity` and `relforcerowsecurity` are true. (Tripwire for future tables.)
- [ ] **Step 2–4:** FAIL → migration 0002 + models → PASS. Migration test from Phase 0 still passes (update expected head revision).
- [ ] **Step 5:** Commit `feat(tenancy): tenants, settings, roles and users with forced RLS`.

### Task 4: Industry packs

Roadmap: 1.8 (part)

**Files:** Create `app/platform/packs/generic.json`, `app/platform/packs/edtech.json`, `app/platform/packs/__init__.py`, `tests/platform/test_packs.py`.

**Interfaces — Produces:** `def load_pack(key: str) -> IndustryPack` (pydantic: `labels: dict[str, Label]` with `singular`/`plural` for `lead, contact, deal, customer, pipeline`); `def available_packs() -> list[str]`; unknown key → `UnknownPackError`.

- [ ] **Step 1: Failing tests:** `test_edtech_lead_label_is_student` (`singular == "Student"`, `plural == "Students"`), `test_generic_lead_label_is_lead`, `test_unknown_pack_raises`, `test_every_pack_defines_every_label_key`.
- [ ] **Step 2–4:** FAIL → JSON files + loader → PASS.
- [ ] **Step 5:** Commit `feat(platform): industry packs as seed data (generic, edtech)`.

### Task 5: Security primitives and platform staff auth

Roadmap: 1.1

**Files:** Create `app/core/security.py`, `app/platform/staff/{models,service,router,schemas}.py`, `migrations/versions/0003_platform_staff.py` (`platform_staff`, `platform_staff_sessions`), `app/platform/cli.py` (`create-staff`), Makefile target `create-staff`, `tests/core/test_security.py`, `tests/platform/test_staff_auth.py`.

**Interfaces — Produces:**
- `hash_password(plain: str) -> str`, `verify_password(plain: str, hashed: str) -> bool` (argon2).
- `create_access_token(sub: UUID, typ: Literal["staff","user"], tenant_id: UUID | None) -> str`; `decode_access_token(token: str, expected_typ: str) -> TokenClaims` (raises `InvalidToken`).
- `new_refresh_token() -> tuple[str, str]` (plain, sha256 hash).
- Dependency `current_staff` (Bearer token, `typ == "staff"`).
- Routes: `POST /platform/auth/login`, `/platform/auth/refresh`, `/platform/auth/logout`, `GET /platform/auth/me`.

- [ ] **Step 1: Failing tests:**
  - security: `test_password_roundtrip`, `test_wrong_password_fails`, `test_token_with_wrong_typ_rejected`, `test_expired_token_rejected`.
  - staff auth: `test_staff_login_returns_tokens`, `test_wrong_password_and_unknown_email_same_401_message`, `test_inactive_staff_cannot_login`, `test_refresh_rotates_token`, `test_reused_refresh_token_revokes_all_sessions`, `test_logout_revokes_session`, `test_user_typ_token_rejected_on_platform_routes`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Manual: `make create-staff` creates a staff account; login via `/docs` works.
- [ ] **Step 6:** Commit `feat(platform): staff accounts, login, refresh rotation and logout`.

### Task 6: Tenant provisioning and management

Roadmap: 1.2, 1.10 (staff audit part)

**Files:** Create `app/platform/tenants/{service,router,schemas,slugs}.py`, `app/core/mailer.py` (`Mailer` protocol + `ConsoleMailer` that stores messages in memory/log), `app/platform/audit.py` + `platform_audit_log` in `migrations/versions/0004_platform_audit.py`, `tests/platform/test_slugs.py`, `tests/platform/test_provisioning.py`, `tests/platform/test_tenant_routes.py`.

**Interfaces — Produces:**
- `def validate_slug(slug: str) -> str` (raises `InvalidSlug` with reason).
- `async def provision_tenant(data: TenantCreate, staff_id: UUID) -> Tenant` — one transaction: tenant row → `tenant_session(new_id)` → settings from pack → 5 system roles (Owner, Admin, Sales Manager, Sales User, Finance with scopes all/all/team/own/own) → Owner user `status=invited` → invite token (72 h, hashed) → mail via `Mailer` → platform audit row.
- Routes: `GET/POST /platform/tenants`, `GET/PATCH /platform/tenants/{id}`, `POST /platform/tenants/{id}/suspend`, `/reactivate`, `/resend-owner-invite`, `GET /platform/audit`.

- [ ] **Step 1: Failing tests:**
  - slugs: `test_valid_slug_accepted`, parametrised `test_invalid_slugs_rejected` for `"Acme"`, `"ac me"`, `"ab"`, 31 chars, `"1acme"`, `"admin"`, `"www"`.
  - provisioning: `test_provision_creates_tenant_settings_roles_and_invited_owner`, `test_owner_invite_email_sent_with_link_to_slug_subdomain` (link starts with `https://{slug}.{BASE_DOMAIN}/`), `test_duplicate_slug_rejected_409`, `test_failure_midway_leaves_nothing` (force the mailer to raise → tenant count unchanged), `test_edtech_pack_labels_applied`.
  - routes: `test_suspend_and_reactivate_change_status`, `test_every_staff_write_creates_platform_audit_row`, `test_tenant_routes_require_staff_token`, `test_unknown_tenant_id_404`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Full suite + `make lint` green; tick roadmap 1.1, 1.2, 1.3; commit `feat(platform): one-step tenant provisioning, suspend, platform audit`.
- [ ] **Step 6:** Show Suyog: create a tenant via `/docs`, see the invite in the console log. Wait for review before slice 1-B.

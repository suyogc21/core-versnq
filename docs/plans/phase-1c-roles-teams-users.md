# Phase 1-C — Roles, Permissions, Teams and User Management

> **Execution:** inline, test-first. Approved by Suyog 2026-11-05 ("yes, go ahead"). Roadmap 1.6, 1.7, last test of 1.3, and the tenant audit log from 1.10 (moved forward).

**Goal:** Admins manage their people: invite, edit, disable, temporary password, roles (incl. custom) and teams of any depth; every endpoint checks a permission and record visibility (own / team / all) is computed in one place.

## Rules

- **Permissions** are codes (`users.read`, `users.manage`, `roles.manage`, `teams.manage`, `settings.manage`, `audit.read`; Phase 2 adds lead codes). Deny by default. Owner implicitly has every code, now and in future.
- **Default grants:** Owner all · Admin all · Sales Manager `users.read` · Sales User none · Finance `audit.read`.
- **Scope** on the role: `own` = only me · `team` = me + members of every team I manage and all teams below them · `all` = everyone in the tenant. One function, `visible_user_ids`, used by every list (users now, leads in Phase 2).
- **Anti-escalation:** nobody changes their own role or disables themselves; only an Owner manages Owners or assigns the Owner role; you cannot grant a permission you do not have (role edits and role assignment); the last active Owner cannot be demoted or disabled.
- **Roles:** the Owner role is read-only; system roles cannot be deleted or renamed; custom roles can be deleted only when nobody has them.
- **Teams:** a user may belong to several teams; `is_manager` per membership; a team cannot be moved under itself or its own sub-team; a team with sub-teams cannot be deleted.
- Disabling a user or setting a temporary password revokes all their sessions.
- Every write records a tenant **audit_log** row (append-only; no passwords or tokens inside).
- Another tenant's IDs always answer 404.

## Tasks

| # | Builds | Key tests |
| --- | --- | --- |
| 1 | Migration 0007: `permissions` catalogue, `role_permissions`, `teams`, `team_members`, `audit_log` (all tenant tables RLS; audit append-only); provisioning seeds default grants; backfill existing tenants | owner has every catalogue code · defaults per role · audit cannot be updated |
| 2 | `require(code)` dependency, effective permissions on the current user | sales user → 403 on users list · unknown code denied |
| 3 | Roles API + permission catalogue | create custom role · cannot grant what you lack · Owner role read-only · system role not deletable · role in use not deletable · unknown code 422 |
| 4 | Teams API + `visible_user_ids` | manager sees own + sub-teams, not siblings or parents · cycle 422 · delete with children 409 · other-tenant member 422 |
| 5 | Users API: list/get (visibility), invite, edit, role change, disable/enable, temporary password, resend invite | own-role change 403 · admin cannot touch owner · last owner 409 · disable revokes sessions · temporary password restricts · duplicate email 409 · other-tenant id 404 · every write audited |

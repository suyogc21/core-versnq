# Phase 1-B — User Authentication Implementation Plan

> **Execution:** inline, test-first. Approved by Suyog 2026-11-05 ("Build slice 1-B now"). Roadmap 1.4, 1.5 + open items of 1.1–1.3.

**Goal:** People of a client company log in on `<slug>.<BASE_DOMAIN>`, accept invites, reset passwords and use 2FA; staff get 2FA too; brute force is rate-limited.

**Architecture:** The tenant comes from the web address (Host header), never from the request body. Tenant routes run in `tenant_session(tenant)`. A user token is only valid on its own tenant's address. Restrictions (must change password, must set up 2FA) are checked from the database on every request, not stored in the token.

**New dependencies (approved, Decision log #13):** `pyotp`, `cryptography`. New env: `TOTP_ENCRYPTION_KEY` (Fernet key).

## Rules

- Unknown workspace → 404. Suspended workspace → 403 on login and on every request.
- Owner and Admin (role keys `owner`, `admin`) and all staff must use 2FA. Until they set it up, only `me`, `logout`, `2fa/setup`, `2fa/enable` (and `password/change`) work; everything else → 403.
- `must_change_password` → only `me`, `logout`, `password/change` work.
- With 2FA on, login returns a 5-minute challenge token; `2fa/verify` with a valid code returns the real tokens.
- Invite 72 h, reset 60 min, both single use; a new reset link invalidates older ones; forgot-password always answers 202.
- Password reset or change → every session of that user revoked.
- Refresh tokens: same rotation + reuse detection as staff; cookie `user_refresh`, path `/api/v1/auth`.
- Rate limits (Redis): login 10 per IP per minute; 5 failed logins per account per 15 minutes; 2FA verify 5 per challenge; forgot-password 5 per IP per hour → 429.
- Passwords: 10–200 characters.

## Tasks

| # | Builds | Tests |
| --- | --- | --- |
| 1 | Workspace resolution from Host; `user_sessions` table (RLS) | unknown slug 404 · suspended 403 · reserved/odd hosts 404 · port ignored |
| 2 | Login, refresh, logout, logout-all, me | login ok · same 401 for wrong password / unknown email / invited / disabled user · email case-insensitive · rotation · reuse revokes all · logout-all · **token of tenant A rejected on tenant B's address** · staff token rejected on tenant routes · user of A cannot log in on B |
| 3 | Invite accept, forgot, reset, change password, temporary-password gate | accept sets password + activates · expired/used/other-tenant token rejected · forgot answers 202 for unknown email and sends nothing · reset revokes sessions · new reset link kills old one · change needs current password · `must_change_password` blocks other routes |
| 4 | 2FA for users and staff (TOTP, secret encrypted at rest) | setup → enable with valid code · wrong code rejected · login with 2FA returns challenge, verify returns tokens · owner without 2FA blocked from non-setup routes · sales user without 2FA not blocked · staff without 2FA blocked from tenant management · secret not stored in plain text |
| 5 | Rate limits | 6th failed login on one account → 429 · 11th login from one IP in a minute → 429 · forgot-password limit |

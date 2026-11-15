# Go-live safety: before the first paying customer

Written 2026-11-15 for Suyog (roadmap G.2–G.3, the parked "security and go-live" row of `OWNER-TODO.md`). No new features: this protects customers' data and tells us when something breaks. Each item is approved before it is built.

## Where the server stands today (checked Nov 15)

| Area | Today | Risk |
|---|---|---|
| HTTPS | Every Core address has a certificate; renewal timer on | — |
| Open ports | Only 22 (SSH), 80, 443 are reachable; the database, Redis and Core's apps listen on the server only | — |
| Firewall (`ufw`) | **Off** | Low today (nothing else is exposed), but one wrong future setting would be open to the internet |
| HSTS (browsers always use HTTPS) | **Missing** | A first visit over plain http could be intercepted |
| Backups | Nightly at 02:30 into `/opt/core-backups`, 14 days | **They live on the same server**: a lost server loses the backups too |
| Restore | Done by hand once | Never tested on a schedule |
| Error alerts | **None**: errors are only in the logs | We find out when a customer tells us |
| Container logs | **No size limit** (24 MB now) | Grows until the disk fills |
| Disk encryption | Not encrypted (a normal VPS disk) | Passwords and keys inside the database are already encrypted by Core; the rest is plain on disk |
| Lost phone (2FA) | People with the authenticator app who lose their phone can't sign in | A customer's owner locked out |

## The plan

### G-1 Backups off the server (encrypted) — parked: Suyog's Raspberry Pi
- Every night after the backup, the files are **encrypted on the server** (a public key; the private key stays with you, never on the server) and copied to a second place, 30 days kept there.
- A monthly **restore test**: the newest copy is restored into a scratch database on the server, checked (companies, leads, invoices counted), then removed; the result is emailed to you.
- Tools: `age` (encryption) and `rclone` (copying), installed on the server only (no change to Core's code or dependencies).

### G-2 Error alerts — built Nov 15 (ALERT_EMAIL on the server; the outside uptime check is on Suyog's list)
- An unexpected error in the backend or the worker (the "500" kind) **emails Versnq staff** from `support@versnq.in`: what failed, when, which company (never passwords, tokens or message bodies). At most one email per kind of error per hour, plus a daily count.
- An outside **uptime check** every minute on `/health` (a free service), so a down server is noticed even when it can't send email.

### G-3 Server hardening — done Nov 15 (firewall on, HSTS live, log caps on the next deploy)
- **HSTS** on every Core address (browsers then refuse plain http).
- **Container logs capped** (10 MB × 5 files per service).
- **Firewall on**: allow only SSH, HTTP, HTTPS (matches what is open today, so AMS, n8n and the website are unaffected).
- Disk encryption: **not possible on this VPS without rebuilding it**; recorded as a known gap. Secrets in the database stay encrypted, and backups are encrypted (G-1).

### G-4 Lost phone (2FA recovery, roadmap G.2) — built Nov 15
- When someone turns on the authenticator app, they get **10 one-time backup codes** (shown once, can be printed); a code works in place of the app code once.
- An **Owner or Admin can reset** a team member's authenticator (that person then signs in with the emailed code and can set the app up again). Audited.
- **Versnq staff can reset a company Owner's** authenticator from the staff console. Audited in the staff audit log.
- Schema (migration 0032): `user_recovery_codes` (user, code hash, used_at) and the same for staff; no other change.

### Tests
- Backup: the encrypted copy can be decrypted with the private key and restored (run on the server; result in the log and by email).
- Alerts: an error in a route and in a worker job each send one email; a second within the hour doesn't; nothing secret is in it.
- Recovery codes: shown once, stored hashed, each works once, wrong ones are rate-limited, other companies can't use them; resets need the right role and are audited.

## Not in this plan (later, roadmap S.1–S.5)
Login history, idle sign-out per company, IP allowlist, failed-sign-in alert emails, India DPDP export / erasure / breach runbook.

## Decided (Nov 15, Suyog)

1. **Backups (G-1): parked.** Suyog is setting up a Raspberry Pi as the backup destination; nothing is done on backups until he says so.
2. Error alerts: **Core emails staff** (no new service or dependency), plus an outside uptime check.
3. **Firewall on**, allowing only SSH, HTTP and HTTPS.
4. Lost phone: **backup codes, Owner/Admin reset, staff reset for Owners** (migration 0032).

Build order: G-3 (server hardening), G-2 (alerts), G-4 (lost phone).

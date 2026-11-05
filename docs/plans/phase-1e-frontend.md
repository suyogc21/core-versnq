# Phase 1-E — Frontend (Staff Console + Client App)

Status: **approved 2026-11-05** (dependencies approved; addresses per Decision log #20). Roadmap 1.14–1.17 + Gate 1. Decision log #19.

## Two apps

| App | Folder | Address (prod / dev) | Talks to |
| --- | --- | --- | --- |
| Staff console | `frontend-admin/` | `admincore.versnq.in` / `admincore.localhost:3001` | `/platform/*` |
| Client app | `frontend/` | `<slug>.core.versnq.in` / `<slug>.localhost:3000` | `/api/v1/*` |

Both: Next.js 16.2.6, React 19.2.4, TypeScript, Tailwind 4, shadcn/ui (`base-nova`, `@base-ui/react`), lucide icons — the same versions as AMS.

## How the browser reaches the API

- **Same origin.** The browser calls `/api/v1/...` (or `/platform/...`) on its own address; the Next app forwards to FastAPI in dev, nginx does it in prod. Refresh cookies stay httpOnly + SameSite=strict and never cross sites.
- **Backend change:** the workspace is read from `X-Forwarded-Host` only when `TRUST_PROXY_HEADERS=true` (set in dev and behind nginx, which overwrites the header). Otherwise the `Host` header, as today. Dev uses `BASE_DOMAIN=localhost`.
- Access token kept in memory only (never localStorage); on page load or a 401 the app calls `/auth/refresh` once, then retries.
- Typed API client generated from the committed `docs/api/openapi.json`; a check fails when they drift.

## Look and feel

- Linear/Attio style: neutral greys, generous whitespace, one accent colour, left sidebar, command-style search later.
- **Client theming:** the workspace's `primary_color` replaces the accent at runtime; text on the accent is chosen black or white by contrast so any client colour stays readable.
- Every label shown ("Lead", "Student") comes from `GET /api/v1/settings`.
- Light and dark mode.

## Screens

**Staff console:** login → 2FA (enter code, or first-time setup with QR) · companies list (search, status) · create company (name, slug, pack, timezone, country, owner) · company detail (rename, suspend/reactivate, resend owner invite, module switches) · staff accounts (list, add, deactivate) · platform audit.

**Client app:** login → 2FA / 2FA setup when required · accept invite · forgot / reset password · forced password change · home (placeholder until Phase 2) · users (list by visibility, invite, edit role, disable/enable, temporary password, resend invite) · roles (list, create, edit permissions, delete) · teams (tree, members, managers) · settings (labels, timezone, country, branding) · audit log.

Screens and buttons appear only when the user's permissions allow; the backend still enforces every rule.

## Backend gaps closed in this slice

- `GET/POST /platform/staff`, `PATCH /platform/staff/{id}` (staff-only, audited; a new staff member gets a temporary password and must set up 2FA).
- `GET /api/v1/audit` (permission `audit.read`, newest first, filter by entity).
- `X-Forwarded-Host` support behind `TRUST_PROXY_HEADERS`.

## New dependencies (need approval)

| Package | Why | Alternative |
| --- | --- | --- |
| `openapi-typescript` (dev) + `openapi-fetch` | Typed API client generated from our spec | Hand-written fetch calls (types drift) |
| `@tanstack/react-query` | Loading/caching/refetch of server data | Hand-rolled `useEffect` fetching |
| `react-hook-form` + `zod` + `@hookform/resolvers` | Forms with validation messages | Plain controlled inputs |
| `qrcode.react` | QR code for 2FA setup | Show the secret as text only |
| `@playwright/test` (dev) | End-to-end test of the Gate 1 flow in a real browser | Manual testing only |

## Tests

- `make fe-check`: typecheck + lint + API client up to date, for both apps.
- Playwright end-to-end (Gate 1, roadmap 1.17): staff creates a company → owner accepts invite, sets password, sets up 2FA → owner invites a Sales User → the Sales User logs in and sees no Users/Roles/Settings admin screens and gets 403 if forced. Runs against a separate `versnq_e2e` database.
- Backend tests for the three new endpoints, as usual.

## Order

1. Backend gaps (staff accounts, audit read, forwarded host) — test-first.
2. Shared foundations per app: Next.js + shadcn setup, theme, API client, auth (token, refresh, 2FA), layout.
3. Staff console screens.
4. Client app screens.
5. Playwright Gate 1 flow → Gate 1 review with Suyog.

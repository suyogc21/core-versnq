# Phase 1-D — Settings, Modules, Events, Route Safety Net, API Spec

> **Execution:** inline, test-first. Approved by Suyog 2026-11-05 ("lovely lets do this"). Roadmap 1.8–1.13. Completes the Phase 1 backend.

## Rules

- **Settings (1.8):** `PATCH /api/v1/settings` (permission `settings.manage`) edits labels (only the known keys: lead, contact, deal, customer, pipeline — singular + plural), timezone (IANA), locale, default country (ISO 3166 alpha-2) and branding (`primary_color` hex, `logo_url` https). Audited.
- **Modules (1.9):** catalogue `crm` (core, always on), `email`, `whatsapp`, `sequences`, `inbox`, `api` (on by default), `money`, `ace` (off by default — Money parked, ACE is an add-on). Staff switch them per tenant (`GET/PUT /platform/tenants/{id}/modules`, platform-audited); tenants read them (`GET /api/v1/modules`). A route behind a switched-off module answers **404**; a switched-off module emits **no events**. A module added later uses its default until a tenant row exists.
- **Events (1.11):** outbox table `events` (tenant RLS). Catalogue = the spec's 20 event types, each mapped to a module. `emit()` writes in the caller's transaction (rollback → no event), rejects unknown types, skips switched-off modules. Delivery (webhooks) is Phase 4.
- **Audit (1.10):** settings and module changes join the existing audits.
- **Route safety net (1.12):** a test walks every route: each needs a login dependency unless on an explicit public list; `/api/v1` routes never accept staff auth and `/platform` routes never accept user auth.
- **API spec (1.13):** stable operation IDs (`<tag>-<function>`); `make openapi` writes `docs/api/openapi.json`; a test fails when the committed spec is out of date.

## Tests

| Item | Tests |
| --- | --- |
| 1.8 | edit labels/timezone/branding · unknown label key 422 · bad timezone/colour/country 422 · sales user 403 · labels of A unchanged when B edits · audited |
| 1.9 | defaults (money/ace off, crm on) · staff toggle + audit · crm cannot be switched off · module route 404 when off, 200 when on · tenant can read modules |
| 1.11 | event written in same transaction · rollback leaves no event · unknown type rejected · switched-off module emits nothing · events isolated by RLS (tripwire covers) · catalogue matches spec list |
| 1.12 | no unlisted public route · no staff/user guard mix |
| 1.13 | committed spec equals generated spec · operation IDs unique |

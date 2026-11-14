# Outreach: campaigns like Smartlead, inside Core, with ACE as the brain

Written 2026-11-14 for Suyog. Decision log #44. Nothing here is built yet; each step gets its own approval before code.

## The goal

A company connects **as many inboxes as it needs** (10, 50…), runs cold campaigns that **rotate across them**, and every reply lands in one place. **ACE** reads each reply, decides the intent from **the company's own categories**, and the company's **rules** act on it: an interested person becomes a lead in the CRM, ACE drafts the answer, someone approves it in **Slack** (or in Core), and it goes out from the same inbox, in the same thread.

```
inboxes (pool) ─► campaign ─► rotating sends ─► reply ─► ACE: intent ─► rules ─► lead / draft ─► Slack approve ─► sent
```

**Rule: only what is 100% is shown or sold.** Until a step is finished it stays switched off (H1).

## Who does what

| Part | Lives in | Why |
|---|---|---|
| Inboxes, sending, rotation, limits, tracking, unsubscribe, suppression, reply sync | **Core** | Core already has the plumbing (connect, send, sync, tracking, unsubscribe); one place, no duplicate |
| Cold contacts and campaigns | **Core** ("Outreach"), kept **apart from leads** | The CRM stays clean; a contact becomes a lead only on a positive intent |
| Reply categories and rules (if intent X then …) | **Core** (set up by the company; Core runs the actions) | Rules work and are visible in the CRM even when ACE is off |
| Reading replies → intent, summary, drafted answer | **ACE** | The AI brain; reaches Core only through the API and webhooks |
| Slack: drafts with Approve / Edit / Reject | **ACE** (its own Slack app) | Every customer gets it without setup; no n8n inside ACE (#42) |
| Customer's own automations | The customer's n8n / Zapier on Core's webhooks | Optional, theirs |

This replaces Decision #4 (campaigns in ACE's own database) and settles ACE's D4 (outbound sender = Core).

## Steps

| Step | What | Depends on |
|---|---|---|
| **H1** | Hide what isn't 100%: company WhatsApp number until it's live with Meta, copy-in addresses until inbound mail is live | — |
| **O1** | **Mailbox pool**: any number of inboxes per company; bulk connect; limits, spacing and health per inbox; auto-pause; sequences send from the pool | — |
| O2 | Campaigns: cold contact lists (CSV), steps with variants, rotation across the pool, sending windows, tracking on/off, own tracking domain, master inbox, convert to lead | O1 |
| O3 | Reply intelligence hooks: the company's reply categories, rules (category → actions), drafts stored in Core with approve/edit/reject in the inbox; the API ACE uses | O2, ACE |
| O4 | Slack approval (in ACE) | O3 |
| O5 | One-click Google / Microsoft connect (OAuth). Outlook needs it; Google's review takes weeks and costs money, so it should be started early | Suyog's Google/Microsoft app registrations |

Warm-up: a partner tool beside Core at first. Building our own warm-up network is a separate product.

---

## H1: hide what isn't 100% (detailed)

- **Company WhatsApp number:** the Settings card, the lead's "Company WhatsApp" button, WhatsApp steps in sequences and the WhatsApp payment reminder show only when `WHATSAPP_SENDER=meta`. In test mode they stay visible to Versnq staff only (for demos), never to customers.
- **Copy-in addresses:** shown only when `INBOUND_EMAIL_LIVE=true`.
- The overview page and the sales line list only built features.
- No schema change. Tests: the screens and endpoints answer accordingly in each mode.

## O1: the mailbox pool (detailed, for approval)

### What changes for people

- **Settings → Inboxes → Sending inboxes**: the company's pool. An admin connects inboxes **one by one or in bulk** (a CSV: address, sender name, username, app password, provider). Each is checked (IMAP and SMTP) before it's saved.
- Each inbox has a **sender name**, an **owner** (the person whose replies they are; optional), a **daily limit** (default 30), a **minimum gap** between sends (default 6 minutes), a **signature**, and on/off.
- A **health table**: status, sent today / limit, replies and bounces in the last 7 days, last sync, last error. An inbox whose bounces pass **5% of its last 50 sends** is **paused automatically**, and admins are told.
- A rep's own mailbox ("My mailbox") keeps working as today, and can also be added to the pool.
- **Sequences send from the pool**: from the lead owner's inbox in the pool if there is one, otherwise the least-used healthy inbox, always within each inbox's limit and gap. The single company mailbox (Settings → Money) stays only for invoices and receipts.
- Replies from **every** inbox are pulled in (already how sync works).

### Schema (migration 0029, for approval)

`mailboxes` (today: one per user):
- `user_id` becomes **optional** (an inbox may belong to no one, e.g. `sales@`), and the "one per user" rule becomes "one **personal** mailbox per user".
- new: `personal` (bool: this is the user's "My mailbox"), `in_pool` (bool: may send sequences / campaigns), `from_name`, `signature`, `daily_limit` (int, default 30), `min_gap_minutes` (int, default 6), `last_sent_at`, `paused_reason`.
- `status` gains `paused`.
- permission `mailboxes.manage` (exists) covers the pool.
- existing rows: `personal = true`, `in_pool = false` (nothing changes until an admin adds them).

No new table: sends are counted from `messages` (`mailbox_id`, already there), so "sent today" and bounce rates are always exact.

### Endpoints

- `GET/POST /mailboxes` (pool list, connect one), `POST /mailboxes/import` (CSV, each row checked, a report per row), `PATCH /mailboxes/{id}` (limits, owner, name, signature, on/off, pool), `POST /mailboxes/{id}/check`, `POST /mailboxes/{id}/resume`, `DELETE /mailboxes/{id}`.
- `GET /mailboxes/health` (the table).
- Refusals carry codes (`mailbox_limit_reached`, `mailbox_paused`, `no_sending_inbox`).

### Tests

- 10+ inboxes connect, import reports bad rows without saving them, another company never sees them.
- Picking an inbox: owner's first, then least used; never over the daily limit or inside the gap; paused / error inboxes skipped; none left → the step waits (not skipped).
- Auto-pause at the bounce threshold and admins notified; resume.
- A sequence over 3 inboxes spreads its sends and stays inside every limit.
- Existing personal mailboxes behave exactly as before.

### Open questions

1. Default daily limit 30 and gap 6 minutes per inbox (Smartlead-like starting values)? Raise per inbox when warmed up.
2. Should reps see the pool's health, or only admins and managers? (Proposed: admins and managers.)

---

## O3: the contract with ACE (agreed Nov 14, from `../ACE/docs/plans/ace-plan.md` "Contract with Core")

ACE's proposed names are **accepted** unless a change is listed. Everything here is Planned (O2/O3) until built.

### Events

| Event | Step | `data` (plus `actor_user_id`, `actor_type`, built) |
|---|---|---|
| `message.received` / `message.sent` | built; fields O2 | built fields, plus `contact_id`, `campaign_id`, `mailbox_id` (null when not from the pool). **`lead_id` is null** for a cold contact who isn't a lead yet. `auto_submitted: bool` (from `Auto-Submitted`, `X-Autoreply`, `Precedence: auto_reply/bulk`) |
| `reply.classified` | O3 | `message_id, conversation_id, contact_id, lead_id, category, confidence, by (ace \| person), classification_id` |
| `draft.requested` | O3 | `request_id, message_id, conversation_id, contact_id, lead_id, category, rule_id, instructions` (optional text from the rule) |
| `draft.created` | O3 | `draft_id, conversation_id, request_id, created_by` |
| `draft.approved` / `draft.rejected` | O3 | `draft_id, conversation_id, decided_by_user_id, via (core \| slack), body_changed`, `message_id` (approved), `reason` (rejected) |
| `draft.superseded` | O3 | `draft_id, conversation_id, newer_message_id` |
| `contact.converted` | O2 | `contact_id, lead_id` |
| `reply_categories.changed` | O3 | none |

### Endpoints

| Call | Step | Shape |
|---|---|---|
| `GET /conversations/{id}` | built + O2 | adds `contact` and `campaign` (id, name, step sent) on campaign threads. **API keys never mark a conversation read**; anyone may pass `?mark_read=false` |
| `GET /contacts/{id}` | O2 | `id, name, email, company, title, variables, status, campaign_ids, lead_id` |
| `GET /campaigns/{id}` | O2 | `id, name, description` (the offer, written by the company for ACE) |
| `GET /reply-categories` | O3 | `[{key, name, description, needs_human, active, auto_send_allowed, position}]`, `updated_at`. **Exactly one** category has `needs_human = true`; its key is fixed: `needs_human`. The others are the company's own |
| `PUT /messages/{id}/classification` | O3 | `{category, confidence (0–100), summary (≤ 500), reasons (≤ 5, ≤ 200 each), language, prompt_version}` → `{classification_id, rules_run, draft_requested}`. Rules run **once per message**: the same body again changes nothing; a different category from ACE re-runs the rules only while no person has classified it; after a person did, refused with `classified_by_person` |
| `POST /conversations/{id}/drafts` | O3 | `{request_id, reply_to_message_id, body (plain text, no signature), reasons, language}` → `{draft_id, status}`. Same `request_id` → the same draft. Core adds the sending inbox's signature when it sends. Refusals: `draft_superseded`, `conversation_closed`, and the built ones (`email_opted_out`, `email_suppressed`, …) |
| `GET /drafts/{id}` | O3 | `{id, status (pending \| approved \| rejected \| superseded \| sent), body, decided_by_user_id, conversation_id}` |
| `POST /drafts/{id}/approve` | O3 | `{on_behalf_of_user_id?, body?}` → `{status, message_id}` |
| `POST /drafts/{id}/reject` | O3 | `{on_behalf_of_user_id?, reason?}` → `{status}` |

Refusal codes for approve / reject: `draft_already_decided`, `draft_superseded`, `user_cannot_approve`, `user_inactive`.

### Acting for a person (Slack)

- New permission **`drafts.approve_for_users`**, granted only to the role made for ACE's key (never to people).
- `on_behalf_of_user_id` is accepted **only** on approve and reject, and **only** from a caller holding that permission. Core then checks **that person's** rights: active, `inbox.reply`, and able to see the conversation. The trail reads "Approved by Riya via Slack (ACE)"; the event's `decided_by_user_id` is Riya, `actor_user_id` is ACE.
- One change from ACE's proposal: `via` is set by Core (`slack` when `on_behalf_of_user_id` is used, `core` otherwise), not sent by ACE.

### Draft lifecycle (Core)

`pending` → `approved` → `sent` (or back to the inbox with the error), `pending` → `rejected`, `pending` → `superseded` (a newer reply from the person arrived before a decision; event emitted). One pending draft per conversation at a time.

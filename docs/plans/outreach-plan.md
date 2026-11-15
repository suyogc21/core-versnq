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
| **H1 ✅** | Hide what isn't 100% (built Nov 14): company WhatsApp number until it's live with Meta, copy-in addresses until inbound mail is live | — |
| **O1 ✅** | **Mailbox pool** (built Nov 14): any number of inboxes per company; bulk connect; limits, spacing and health per inbox; auto-pause; sequences send from the pool | — |
| O2 | Campaigns (plan below, for approval): cold contact lists (CSV), steps with variants, rotation across the pool, sending windows, tracking on/off, master inbox, convert to lead. Own tracking domain moves to O2b | O1 |
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

**Built (Nov 14):** `GET/POST /sending-inboxes` (list with health; connect one), `POST /sending-inboxes/import` (CSV, each row signed in to, a report per row), `PATCH /sending-inboxes/{id}` (sender name, signature, owner, limits, new password), `POST /sending-inboxes/{id}/add` (a person's own mailbox joins the pool), `/check`, `/pause`, `/resume`, `DELETE /sending-inboxes/{id}`. Refusal code `mailbox_exists`. Bounce reports arriving in any inbox are matched to the email sent and recorded (hard bounces suppress the address); a pool inbox above 5% bounces over its last 50 sends (at least 20) is paused and owners/admins told. Defaults: 30 a day, 6-minute gap; health visible to admins and managers (API; screen for admins).

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

## O2: campaigns (detailed, for approval — written Nov 15)

### What changes for people

A new **Outreach** section in the sidebar (behind a module switch `outreach`, off until Versnq staff turn it on for a company, so H1's rule holds).

1. **Campaigns list**: name, status (draft / running / paused / finished), contacts, sent, replies, bounces, unsubscribes.
2. **A campaign** has five tabs:
   - **Contacts**: import a CSV. Map its columns to email, first name, last name, company, title, phone, website; any other column becomes a variable usable in emails (`{{city}}`, `{{pain_point}}`…). Before saving, a report: added, duplicates in the file, bad emails, already unsubscribed or bounced (skipped), **already a lead or customer in the CRM (skipped)**. Up to 20,000 rows per file. Contacts can also be added to another campaign from the list.
   - **Sequence**: steps, each with a wait ("3 days after the previous step") and **1–5 variants** (A/B/C… subject and body). Contacts are split evenly across variants. A step with an empty subject is sent **in the same thread** ("Re: …"). Preview any step as any contact; a missing variable is flagged before launch (with an optional fallback, `{{first_name|there}}`).
   - **Inboxes and schedule**: which sending inboxes (all of the pool, or chosen ones), sending days and hours in a chosen time zone, a campaign daily cap. Each inbox's own daily limit and gap (O1) always apply on top. **A contact keeps the same inbox for the whole campaign**, so follow-ups stay in one thread and replies come back to the same inbox.
   - **Settings**: open tracking and click tracking (both **off by default**: better inbox placement for cold email), the campaign's **description** (the offer, used by ACE in O3), owner.
   - **Results**: per step and per variant: sent, opened (if tracked), replied, bounced, unsubscribed; per inbox: sent and bounces.
3. **Launch / pause / resume**. Launch checks: at least one step, every variable filled or with a fallback, at least one healthy inbox, unsubscribe link present (added automatically to every email, plus the one-click `List-Unsubscribe` header).
4. **Outreach inbox** (the "master inbox"): every reply to every campaign, newest first; filters by campaign, inbox, status (new / replied / converted / not interested), auto-replies hidden by default. Reply from the same inbox, in the same thread. Buttons: **Convert to lead**, **Not interested** (stops that contact), **Unsubscribe**.
5. **Convert to lead**: makes a lead from the contact (fields and variables copied into the lead's fields where they match; the rest into a note), routed by the company's lead routing rules like any new lead, source "Outreach: <campaign>". The conversation with its full history moves onto the lead, so it shows on the lead's timeline and in the normal inbox. The contact stops in every campaign. Event `contact.converted`.

What happens on its own:
- **A reply stops that contact** in that campaign (not their colleagues). **Auto-replies** (out of office, `Auto-Submitted`, `X-Autoreply`, `Precedence: auto_reply/bulk`) are stored and marked, and **do not stop** the campaign.
- **A bounce** marks the contact bounced and suppresses the address (O1 already matches bounce reports). **An unsubscribe** suppresses the address for the whole company and stops every campaign for them.
- Contacts who are leads never get campaign emails (checked again at each send, not only at import).

### Schema (migration 0030, for approval)

New tables (all with `tenant_id`, forced row security like every other table):

- `contacts`: email (unique per company, lower-case), first_name, last_name, company, title, phone, website, `variables` (JSON, the extra CSV columns), status (`active` / `unsubscribed` / `bounced` / `converted`), `lead_id` (set on convert), source, created_by, timestamps.
- `campaigns`: name, description, status (`draft` / `running` / `paused` / `finished`), owner_user_id, `mailbox_ids` (empty = the whole pool), `schedule` (JSON: time zone, days, start, end), daily_cap, track_opens, track_clicks, launched_at, created_by, timestamps.
- `campaign_steps`: campaign_id, position, wait_days, `variants` (JSON list: key, subject, body).
- `campaign_contacts` (a contact in a campaign): campaign_id, contact_id, status (`pending` / `active` / `replied` / `finished` / `stopped` / `bounced` / `unsubscribed`), position (next step), next_run_at, `variant` (fixed per contact), `mailbox_id` (sticky inbox), ended_reason, timestamps. Unique (campaign, contact).

Changes:
- `messages`: + `contact_id`, `campaign_id`, `campaign_step_id`, `variant`, `auto_submitted` (bool).
- `conversations`: `lead_id` becomes optional; + `contact_id`, `campaign_id`; a check that each conversation has a lead or a contact.
- Permissions: **`campaigns.manage`** (create, import, edit, launch, pause; default Owner, Admin, Sales Manager) and **`outreach.reply`** (the outreach inbox; default the same, plus Sales Users for campaigns they own).

No change to leads, sequences or the normal inbox: conversations without a lead appear only in the outreach inbox.

### Endpoints

- `GET/POST /campaigns`, `GET/PATCH/DELETE /campaigns/{id}` (delete only drafts), `POST /campaigns/{id}/launch | pause | resume`.
- `PUT /campaigns/{id}/steps` (the whole sequence at once), `POST /campaigns/{id}/preview` (a step as a contact).
- `POST /campaigns/{id}/contacts/import` (CSV + column mapping; `dry_run=true` gives the report without saving), `GET /campaigns/{id}/contacts` (with status, filters), `POST /campaigns/{id}/contacts` (add existing contacts), `POST /campaigns/{id}/contacts/{cid}/stop`.
- `GET /campaigns/{id}/stats`.
- `GET /contacts`, `GET /contacts/{id}` (the shape agreed with ACE), `POST /contacts/{id}/convert`, `POST /contacts/{id}/unsubscribe`.
- `GET /outreach/conversations` (the outreach inbox), and the existing conversation endpoints (read, reply) work for campaign conversations too.
- Events: `contact.converted`; `message.sent` / `message.received` gain `contact_id`, `campaign_id`, `mailbox_id`, `auto_submitted` (the O3 contract).

### Sending engine

A campaign runner in the existing worker, every minute: picks due contacts in running campaigns inside their sending window; for each, the contact's sticky inbox (or, on the first email, the least-used healthy inbox among the campaign's, owner's first) within its daily limit and gap and the campaign's cap; renders the variant with the contact's variables; adds the unsubscribe link and header and (if on) tracking; sends; sets the next step's time. Nothing to send → it waits, never skips. Follow-ups carry `In-Reply-To` / `References` of the previous email.

Reply matching (mailbox sync): an incoming email that answers a campaign email (`In-Reply-To` / `References`) or comes from a contact in a running campaign is stored on that contact's conversation; everything else in the mailbox is still ignored, as today.

### Tests

- Tenant isolation for every new table and endpoint; permissions for both new permissions.
- Import: the report counts, leads / suppressed / duplicates / bad emails skipped, variables kept, 20,000-row limit.
- Engine: steps run in order with their waits; only inside the sending window; variants split evenly; sticky inbox; inbox limits, gaps and the campaign cap never exceeded across 3 inboxes; waits instead of skipping; follow-ups thread; unsubscribe link and header present; tracking only when on.
- Replies stop only that contact; auto-replies don't; bounce and unsubscribe suppress and stop everywhere; a contact who became a lead is never emailed.
- Convert to lead: lead made and routed, conversation moved with its history, event sent, contact stopped everywhere.
- A browser test: import → launch → a reply in the outreach inbox → convert to lead.

### Not in O2

Own tracking domain per company (needs DNS and a certificate per company; O2b, after you see O2 working), reply categories and AI (O3), warm-up (partner tool), spintax, LinkedIn steps (out of scope), WhatsApp steps in campaigns.

### Decided (Nov 15, Suyog)

1. A CSV row already a lead or customer: **skipped**, listed in the report.
2. Outreach inbox: Owner, Admin and Sales Managers see every campaign; **Sales Users only campaigns they own**.
3. Open and click tracking **off by default**, on per campaign.
4. A reply stops **only that person**.

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

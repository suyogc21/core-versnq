# Versnq Core: the one tracker

**The goal (Nov 16, Suyog):** global, and level with LeadSquared and HubSpot; pricing comes later.
**The rule:** an item gets ✅ only when it is built, tested, live on the server, and a normal person can use it without help. Built but not live is 🟡. Not built is ⬜.

This file replaces the status parts of `OWNER-TODO.md` and `plans/ROADMAP.md`; plans and decisions stay in those files. It is updated on every change.

## Where we are

Each item has a size: S = 1, M = 2, L = 3.

| | Done | Left | Total | % done |
|---|---|---|---|---|
| **All of it (goal above)** | 46 | 64 | 110 | **42%** |
| The first version (no phones, apps, marketing or global) | 46 | 27 | 73 | **63%** |

**58% is left.** It's a rough count by size, not hours; most of what's left is the new scope: calls, apps, marketing and global.

## Done (46)

| Item | Size | |
|---|---|---|
| Foundation: companies, sign-in, roles, teams, settings, audit log | L | ✅ |
| Leads: capture, routing, duplicates, timeline, tasks, follow-ups | L | ✅ |
| Your own record types and links (Batch, Property…) | M | ✅ |
| Deals and pipelines | M | ✅ |
| Tags, saved views, scoring, automations | L | ✅ |
| Customers and document checklist | M | ✅ |
| Money: invoices, instalments, payments, balances, reminders | L | 🟡 payment links wait on keys |
| Dashboards | M | ✅ |
| Key accounts | S | ✅ |
| Page layouts and field access per role | M | ✅ |
| API keys and webhooks | M | ✅ |
| Email sequences | M | ✅ |
| Shared inbox, connected mailboxes, copy-in addresses | L | 🟡 copy-in waits on the email provider |
| WhatsApp company number | M | 🟡 waits on Meta |
| WhatsApp extension for reps' own WhatsApp | M | 🟡 waits on the Chrome Web Store |
| Cold campaigns across many inboxes (O2) | L | ✅ (switched off for real companies) |
| Reply categories, rules, drafts (O3) | M | ✅ |
| Go-live safety: alerts, firewall, HTTPS-only, log caps | M | ✅ |
| Optional 2FA, emailed codes, backup codes, resets | M | ✅ |
| ACE: sign in with Core, decline a draft (C13, C14) | S | ✅ |
| Core on the server | M | ✅ |

## Left (64)

### Go-live: mostly your accounts (10)
| Item | Size | Who | |
|---|---|---|---|
| Email provider for copy-in and company sending domains: **Postmark** (chosen Nov 16) | S | You (account), then me | ⬜ |
| Meta business verification (WhatsApp number) | S | You | ⬜ |
| Razorpay and Stripe keys | S | You | ⬜ |
| Off-server backups to the Raspberry Pi | M | You, then me | ⬜ parked |
| Outside uptime check on `/login` | S | You | ⬜ |
| ACE's console address | S | You | ⬜ |
| Publish the WhatsApp extension (unlisted) | S | You | ⬜ |
| One-click Gmail and Outlook mailbox sign-in (needs your Google and Microsoft app registrations) | M | You, then me | ⬜ |

### Phase 1: green ticks on what we have (9)
| Item | Size | |
|---|---|---|
| **Real forms: builder plus a hosted page to share or embed** (the old form "link" only accepted posts; opening it gave an error) | M | ✅ live Nov 16 (waiting for Suyog's own try) |
| Green-tick walk-through of every feature on the live server, fixing what fails | L | ⬜ |
| WhatsApp extras: photos and PDFs, templates with images and buttons | M | ⬜ |
| Several brands and sending domains in one company | M | ⬜ |

### Security (6)
| Item | Size | |
|---|---|---|
| Login history plus "sign out everyone" | S | ⬜ |
| Sign-out after idle time, per company | S | ⬜ |
| IP allowlist, per company | S | ⬜ |
| Email after repeated failed sign-ins | S | ⬜ |
| Data protection: export everything, full erasure, breach runbook (DPDP and GDPR) | M | ⬜ |

### Phase 2: phone calls (7): decided Nov 16 (plan: `plans/calls-plan.md`)
| Item | Size | |
|---|---|---|
| Click-to-call with the company's own Twilio (C3; Exotel later) | L | ⬜ next |
| **C1 call pipeline:** every call on the timeline, recordings (30 days), missed-call tasks, Outcome in one tap, Calls list, Settings → Calls | M | ✅ live Nov 16 (the phone app that feeds it is C4) |
| ACE analyses calls (Core side built in C1: `call.recorded`, `PUT /calls/{id}/analysis`) | M | ⬜ ACE session |

### Phase 3: phone app (5): decided Nov 16 (installable web app now, Android app next)
| Item | Size | |
|---|---|---|
| Installable app (PWA): home-screen icon, offline page, phone notifications (C2) | M | ✅ live Nov 16 (waiting for your own try) |
| Native iOS and Android app | L | ⬜ |

### Phase 4: marketing (13)
| Item | Size | |
|---|---|---|
| Landing pages | L | ⬜ |
| Email newsletters to your own audience | M | ⬜ |
| Facebook and Google lead ads straight in | M | ⬜ |
| A/B tests | S | ⬜ |
| Custom reports | L | ⬜ |
| SMS | M | ⬜ |

### Phase 5: global (12)
| Item | Size | |
|---|---|---|
| GDPR (Europe) | M | ⬜ |
| VAT and sales-tax setups for other countries | M | ⬜ |
| The app in other languages | L | ⬜ |
| Choice of data region (EU, US) | L | ⬜ |
| Import from HubSpot and LeadSquared | M | ⬜ |

### Later (2)
| Item | Size | |
|---|---|---|
| WhatsApp Business app and API on one number (needs Meta Tech Provider) | M | ⬜ |

## Email: what Core sends, and through what

| Mail | Goes through | Status |
|---|---|---|
| Sign-in codes, invites, resets, error alerts | **Zoho SMTP** (set on the server) | ✅ working |
| Campaigns, sequences, replies from the inbox | **Each company's own mailboxes** (Gmail, Zoho, any server) | ✅ no outside provider needed |
| Copy-in addresses (receiving) and company sending domains | **Postmark** (chosen Nov 16) | ⬜ needs your Postmark account, then I build receiving |
| Later, at scale: our own high-volume sending | Amazon SES | ⏸ when we grow (Suyog, Nov 16) |

## Change log
| Date | Change |
|---|---|
| 2026-11-16 | Tracker created; goal reset to global and level with LeadSquared and HubSpot |
| 2026-11-16 | Real forms built (builder, hosted page /f/<id>, embed); email provider: Postmark |
| 2026-11-16 | Calls and phone app in scope; C1 call pipeline built |

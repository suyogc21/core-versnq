# Versnq Core: the one tracker

**The goal (Nov 16, Suyog):** global, and level with LeadSquared and HubSpot; pricing comes later.
**The rule:** an item gets ✅ only when it is built, tested, live on the server, and a normal person can use it without help. Built but not live is 🟡. Not built is ⬜.

This file replaces the status parts of `OWNER-TODO.md` and `plans/ROADMAP.md`; plans and decisions stay in those files. It is updated on every change.

## Where we are

Each item has a size: S = 1, M = 2, L = 3.

| | Points | Share |
|---|---|---|
| ✅ Live and usable | 45 | **39%** |
| 🟡 Built, waiting on an account, key or your try | 38 | 33% |
| ⬜ Not built | 33 | 28% |
| **Total (goal above)** | 116 | |

Recounted Nov 16 by the rule above: 🟡 doesn't count as done. The earlier "46 done" counted the 🟡 rows in the Done table as done. It's a rough count by size, not hours; most of what's left is the new scope: calls, apps, marketing and global.

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
| WhatsApp extras: photos and PDFs, templates with images and buttons | M | 🟡 built Nov 16 (batch 3); waits on Meta verification |
| Several brands and sending domains in one company | M | 🟡 built Nov 16 (batch 4) |

### Security (6)
| Item | Size | |
|---|---|---|
| Login history plus "sign out everyone" | S | 🟡 built Nov 16 (batch 1); live after the next deploy |
| Sign-out after idle time, per company | S | 🟡 built Nov 16 (batch 1) |
| IP allowlist, per company | S | 🟡 built Nov 16 (batch 1) |
| Email after repeated failed sign-ins | S | 🟡 built Nov 16 (batch 1) |
| Data protection: export everything, full erasure, breach runbook (DPDP and GDPR) | M | 🟡 built Nov 16 (batch 1; runbook in `security/breach-runbook.md`) |

### Phase 2: phone calls (7): decided Nov 16 (plan: `plans/calls-plan.md`)
| Item | Size | |
|---|---|---|
| Click-to-call and incoming calls with the company's own Twilio (C3; Exotel later) | L | ✅ live Nov 16; the first real call needs a Twilio account (a trial is fine) |
| **C1 call pipeline:** every call on the timeline, recordings (30 days), missed-call tasks, Outcome in one tap, Calls list, Settings → Calls | M | ✅ live Nov 16 (the phone app that feeds it is C4) |
| ACE analyses calls (Core side built in C1: `call.recorded`, `PUT /calls/{id}/analysis`; the timeline shows intent, next step and red flags) | M | 🟡 ACE built C5 on fakes Nov 16; needs the Sarvam/Deepgram + Anthropic keys and ACE hosted |

### Phase 3: phone app (5): decided Nov 16 (installable web app now, Android app next)
| Item | Size | |
|---|---|---|
| Installable app (PWA): home-screen icon, offline page, phone notifications (C2) | M | ✅ live Nov 16 (waiting for your own try) |
| Android app (plan: `plans/android-app-plan.md`): shell, call tracking (C4.2), recordings from the phone recorder (C4.3), caller popup and download link (C4.4), back button; built Nov 16; iOS later | L | 🟡 built; needs the deploy, then a try on a real phone |

### Phase 4: marketing (13)
| Item | Size | |
|---|---|---|
| Landing pages | L | 🟡 built Nov 16 (batch 5a): builder, /p/<page>, visits, forms on the page |
| Email newsletters to your own audience | M | 🟡 built Nov 16 (batch 5b): sends from the company mailbox (capped); Postmark later |
| Facebook and Google lead ads straight in | M | 🟡 built Nov 16 (batch 5d) on test events; needs a Meta app and a Google Ads account to try live |
| A/B tests | S | 🟡 built Nov 16 (batch 5a, landing pages; email sequences already had them) |
| Custom reports | L | 🟡 built Nov 16 (batch 5c) |
| SMS | M | 🟡 built Nov 16 (batch 5d): MSG91 (India, DLT ids), Twilio, a test sender; SMS steps in sequences; needs a provider account |

### Phase 5: global (12)
| Item | Size | |
|---|---|---|
| GDPR (Europe) | M | 🟡 built Nov 16 (batch 1 + 6): export, a person's data, erasure, breach runbook, DPA template; the DPA needs a lawyer's read |
| VAT and sales-tax setups for other countries | M | 🟡 built Nov 16 (batch 6): presets for the Gulf, UK, 10 EU countries, SG, AU, CA, NZ; US is a placeholder (state taxes) |
| The app in other languages | L | 🟡 built Nov 16 (batch 6): Arabic (right to left) and Hindi for the menu, page titles, Settings and My account; the rest of each screen still English; needs a native speaker's read |
| Choice of data region (EU, US) | L | ⬜ |
| Import from HubSpot and LeadSquared | M | 🟡 built Nov 16 (batch 2); check one real export file from each |
| Calls and WhatsApp into any CRM: Custom CRM (any CRM, Zapier / Make) and LeadSquared; the "Calls + WhatsApp" plan switch | L | 🟡 built Nov 16 (plan `plans/crm-connectors-plan.md`); needs a deploy and a real LeadSquared account to try |
| More CRMs on the same connector: HubSpot, Zoho, Salesforce, Pipedrive, Freshsales | L | 🟡 HubSpot and Zoho built Nov 17 (each needs a real account to try); Salesforce, Pipedrive, Freshsales next |

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
| 2026-11-16 | C2 installable app + phone notifications live; C3 Twilio calling built; Android app: download link first (Runo answers) |
| 2026-11-16 | C3 Twilio calling live (migration 0037) |
| 2026-11-16 | ACE lead summary in Core (0038, not deployed); Twilio dual-channel; Android C4.1 shell; ACE C5 built on fakes |
| 2026-11-16 | Finishing plan batches 1–4 built: security, imports, WhatsApp extras, brands (migrations 0040–0042) |
| 2026-11-16 | Android app C4.2–C4.4 built (call tracking, recordings, caller popup, download link) |
| 2026-11-16 | Batches 5a–5d (landing pages, A/B, newsletters, custom reports, lead ads, SMS; migrations 0043–0046) and batch 6 part 1 (tax presets, a person's data) merged and tested (676 tests); unknown calls never become leads by themselves. Not deployed yet |
| 2026-11-16 | Arabic and Hindi (partly translated), right-to-left layout; 14 browser tests green |
| 2026-11-16 | Connect any CRM: Custom CRM + LeadSquared, the Calls + WhatsApp switch (migration 0047); 683 tests. Goal grew by 6 points (any-CRM work) |
| 2026-11-17 | Old-phone fix (Android 9 / Chrome 101) live; app 0.5.1 signed and downloadable; call notes (summary + private recording link) to the CRM; HubSpot connector (migrations 0048–0049); 688 tests |

# Finishing Core: everything that needs no purchase (plan)

Written 2026-11-16 for Suyog. **Approved Nov 16: all 7 batches and their database changes.**
Decisions:
- Languages: Arabic (right-to-left) and Hindi first. Suyog left the choice to me.
- Newsletters: send through Postmark's broadcast stream once it's bought; until then small lists
  go through company mailboxes with a daily cap.
- Walk-through: in a test company on the live server, deleted at the end.
Deploys still need Suyog's OK each time.

**The rule (Suyog, Nov 16):** finish everything that costs nothing. Anything that needs a paid
account is built and tested against a fake, then marked 🟡 "waits on your purchase". At the end
you get one shopping list.

## Order
| # | Batch | Points | Days (rough) | Needs a purchase to go live? |
|---|---|---|---|---|
| 1 | Security | 6 | 2 | No |
| 2 | Imports from HubSpot and LeadSquared | 2 | 1 | No |
| 3 | WhatsApp extras: photos, PDFs, rich templates | 2 | 1.5 | Meta verification (free, your time) |
| 4 | Several brands in one company | 2 | 2 | No |
| 5 | Marketing: landing pages, newsletters, A/B tests, custom reports, lead ads, SMS | 13 | 8 | Lead ads need your Meta and Google apps; SMS needs a provider (paid) |
| 6 | Global: GDPR, tax setups, languages | 8 | 4 | No; a second data region needs a second server (paid, later) |
| 7 | Green-tick walk-through of everything on the live server | 3 | 2 | No |

About 20 working days in all. The walk-through comes last so it covers everything built before it.

## 1. Security
| Item | What you get | Built on |
|---|---|---|
| Login history plus "sign out everyone" | My account and Settings → Security: every sign-in with time, place (from the IP address) and device; admins sign out one person or everyone at once | `user_sessions` (exists) |
| Idle sign-out per company | Settings → Security: "sign out after N minutes without activity" (off by default) | tenant settings |
| IP allowlist per company | Settings → Security: only these addresses may sign in; owners can't lock themselves out (their own address is checked first) | tenant settings |
| Email after repeated failed sign-ins | After 5 failed tries in 15 minutes, the person and the company's admins get an email (no password in it) | Redis counter |
| Data protection (India's DPDP Act and GDPR) | **Export everything:** a company admin downloads all their data (leads, deals, customers, money, timeline, files) as one zip, built by the worker. **Erase a person:** a lead's personal data is wiped and their files are deleted; money records keep only what tax law needs, with the name anonymised. **Breach runbook:** a written step-by-step for us | worker + storage |

**Database changes:** `data_exports` (one row per export: who, when, status, file), plus
`leads.erased_at`.

## 2. Imports from HubSpot and LeadSquared
Core's CSV import exists. I add **ready-made column matches** for HubSpot's and LeadSquared's
export files, so their columns (lifecycle stage, owner email, lead source…) land in the right
fields without matching by hand. Owners are matched by email, stages by name (and created if
missing). I'll use their public export formats, and you check one real export file before it's
called done.

**Database changes:** none.

## 3. WhatsApp extras (company number)
- **Photos and PDFs** in and out, in the inbox and on the timeline: received media is saved
  on our server, and Meta's links expire.
- **Templates with an image, video or document header, and buttons** (quick replies, call,
  website).

Built to Meta's documented Cloud API and tested against a fake. 🟡 until Meta verifies you.

**Database changes:** `messages.media` (the file and its type).

## 4. Several brands in one company
One company (say an education group) runs brands with their own name, logo, sending
mailboxes, WhatsApp number, invoice header and form look.
- A lead, deal and invoice belong to a brand.
- Lists filter by brand.
- Reps can be limited to some brands.

**Database changes:** `brands`; a `brand_id` on leads, deals, invoices, forms, mailboxes and
WhatsApp numbers; `user_brands`.

## 5. Marketing
| Item | What you get | Note |
|---|---|---|
| Landing pages | A simple page builder (heading, text, image, video, a form, a button), hosted at the company's address, plus the visitor counts and lead counts each page brings in | Built on the forms we have |
| Newsletters | Lists (from saved views or tags), a simple email editor, scheduling, opens and clicks, unsubscribes honoured | **Question 2 below:** sending volume |
| A/B tests | Two subject lines or bodies in a sequence step or newsletter; the better one wins after a test share | |
| Custom reports | Pick what to count (leads, deals, calls, payments…), filter, group, and show it as a table or chart; save and share with roles | |
| Facebook and Google lead ads | Leads from ad forms arrive in Core in seconds, with the ad and campaign | 🟡 needs your Meta and Google app registrations (free) |
| SMS | Send from the lead, in sequences and as reminders, with opt-outs honoured; providers behind one switch (MSG91 for India, Twilio for elsewhere) | 🟡 needs a provider account (paid); built against a fake |

**Database changes:** `landing_pages`, `newsletters` and `newsletter_sends`, `ab_variants`,
`saved_reports`, `ad_sources`, `sms_messages`.

## 6. Global
| Item | What you get |
|---|---|
| GDPR | Consent with when, how and the wording shown (forms get an optional consent box); export and erase from batch 1; a data-processing agreement template; a cookie-free note for hosted forms |
| Tax setups | Ready-made tax presets for India (GST, already there), UAE and Saudi VAT, UK VAT, EU VAT (standard rates per country) and US sales tax (you type the rate); invoices show the right label and number for each |
| Languages | Core's screens in more languages, with Arabic shown right-to-left. **Question 1 below:** which first |
| Data region | **Design only now:** a second server in the EU or US, with each company placed in one. It needs that server bought, so it's on the shopping list |

**Database changes:** `consents`, plus tax presets as seed data.

## 7. The green-tick walk-through
- I go through every feature in Core on the live server, in a separate test company
  ("walkthrough"), deleted at the end.
- Everything that fails gets fixed, and every passing feature gets its ✅ with a date.
- You get the checklist with the results.

## What stays on your shopping list (not built here)
- Twilio, Postmark, Meta verification, Razorpay and Stripe keys, the Anthropic and
  speech-to-text keys.
- An SMS provider.
- A Firebase project (Android notifications).
- The Chrome Web Store fee ($5).
- A Play Store account ($25).
- A second server for a data region.

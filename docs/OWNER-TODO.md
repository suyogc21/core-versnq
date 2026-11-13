# Versnq Core — what's left, and who does it

Updated 2026-11-13. For Suyog. Plain list. "Built" means coded and tested; "live" means real customers can use it.

## 1. Where Core stands

**Built and tested (500+ automated tests, browser walks on desktop and phone):**
- Leads, routing, timeline, tasks, follow-ups
- Deals and pipelines, customers and document checklist, key accounts
- Money: invoices, instalments, payment links, reminders, balances, dashboards
- Page layouts and field access per role
- API keys and webhooks
- Email sequences, the shared inbox, connected mailboxes (Gmail / Google Workspace / Zoho / any mail server) and copy-in addresses
- WhatsApp: the company number (official API) and the Chrome extension for reps' own WhatsApp

**Built but not live yet.** These wait on your accounts; the code is ready:

| Feature | Live once |
|---|---|
| Real email sending and receiving | Amazon SES + DNS records on versnq.in |
| WhatsApp company number | Meta Business verification, then the real keys entered |
| Payment links | Razorpay / Stripe keys |
| Everything, for customers | A server |
| Chrome extension for customers | Published unlisted on the Chrome Web Store |

**Not built yet in Core:**

| What | Waiting on |
|---|---|
| 10c — WhatsApp Coexistence (Business app + API on one number, phone chats included) | Versnq approved as a Meta Tech Provider |
| 9b-4 — One-click Google / Microsoft mailbox sign-in (needed for Outlook users) | Your Google and Microsoft app registrations |
| Security and go-live: 2FA recovery, nightly backups, the two small quirks, log clean-up, faster paging and exports for very big lists, putting Core on the server | Parked until the end, by your choice |
| Small WhatsApp extras: sending photos/PDFs from the company number, templates with header images or buttons | Nothing; can be done any time |
| Core additions ACE needs: "message arrived" events, AI draft approval in the inbox, AI summary on the lead, red flags, an "ACE off" switch per chat | Built when ACE is built (see `docs/ace/ACE-and-Core.md` §9) |
| Telephony (click-to-call, call recording) | Your decision; out of scope until then |

## 2. Your list (accounts, decisions, checks)

Ordered by how long each one takes to come back, longest first. Start the top ones now.

| # | What | Why | Suggestion |
|---|---|---|---|
| 1 | **Meta Business verification** for Versnq Technologies | WhatsApp company number goes live | Needs company documents (incorporation, GST) and versnq.in showing the same company details. Takes days to weeks. |
| 2 | **Apply to be a Meta Tech Provider** (Meta app with WhatsApp, app review) | Coexistence (10c): customers keep the WhatsApp Business app, and phone chats reach Core | Start right after #1. Follow Meta's official WhatsApp Business Platform docs. |
| 3 | **Ask Meta or a Meta partner: is Coexistence available for Indian numbers?** | Decides whether 10c works for Indian customers | Get it in writing. If not available, we revisit (WA-AKG stays parked until then). |
| 4 | **Amazon SES account + DNS records on versnq.in** (sending and receiving) | Real email: sequences, replies, copy-in addresses | Use the Mumbai region. Ask SES for production access early, because the sandbox only sends to verified addresses. |
| 5 | **Server** (where Core runs) | Go-live | Share the details when chosen; I'll plan the deploy and backups with it. |
| 6 | **Razorpay / Stripe test keys** | Try payment links end to end | Test keys first, live keys at go-live. |
| 7 | **Google developer account** (one-time fee) | Publish the WhatsApp extension unlisted for customers | Not urgent until the first customer. |
| 8 | **Google OAuth app + Microsoft app registration** | One-click mailbox sign-in (9b-4); Outlook users need it | Google's security review for Gmail access takes weeks and is paid. Start before go-live if Outlook/Gmail sign-in matters to early customers. |
| 9 | **Try the extension on your real WhatsApp Web** | It was tested on a stand-in page only | `make extension`, then load `extension/dist` in Chrome (steps in `extension/README.md`). Tell me what you see. |
| 10 | **Decide: pricing tiers** | Open in the spec | — |
| 11 | **Decide: target-niche list** | Open in the spec | The spec's best fit: high lead volume, considered purchase, WhatsApp-heavy, instalments. |
| 12 | **Decide: telephony** — yes or no, and when | Calls and recordings are not built | If yes, I'll compare Indian providers (Exotel, Knowlarity, MyOperator) first. |
| 13 | **ACE decisions** D1–D6 | Before ACE is planned | See `docs/ace/ACE-and-Core.md` §10. |
| 14 | **`! git push`** | Your machine has 36 commits GitHub doesn't | Do it now. |

## 3. Rules we keep

- Say only what is built and tested. Everything else is "planned".
- Client data is never sold or shared.
- Secrets come from the environment only; `.env` is never committed.
- Schema changes and new dependencies need your approval first.

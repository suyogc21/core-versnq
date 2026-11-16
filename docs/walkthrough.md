# Green-tick walk-through (finishing plan, batch 7)

Run on the live server in a test company "walkthrough", which is deleted at the end. Each line
gets ✅ with the date, or ❌ with what failed. Something that waits on a purchase is marked 🟡
and tested as far as possible without it (test modes, fakes).

| # | Area | Check | Result |
|---|---|---|---|
| 1 | Sign-in | Invite → set password → emailed code → My Day; wrong password ×5 → paused and alert email; 2FA app on/off; backup code; forgot password | |
| 2 | Security | Sign-in history; sign out a device; sign out everyone (immediate); idle sign-out; IP allowlist refuses another address and can't lock the admin out | |
| 3 | Settings | Company (labels, time zone, currency), users, teams, roles and field access, brands, audit log | |
| 4 | Leads | Add by hand, duplicate warning, routing to an owner, stage moves, follow-up required, tags, saved views, score | |
| 5 | Timeline | Note, call log with Outcome, task, follow-up; every change appears with who and when | |
| 6 | Forms | Builder → hosted page /f/… → submit → lead with consent and source; embed on a page | |
| 7 | Landing pages | Build → publish /p/… → visit counted → form makes a lead with the page as its source | |
| 8 | Imports | CSV import; HubSpot and LeadSquared files detected and pre-matched; failed rows downloadable | |
| 9 | Deals | Pipeline, stages, won/lost, amounts per currency | |
| 10 | Customers | Convert, document checklist, reminders | |
| 11 | Money | Invoice with tax (country presets), installments, record a payment, receipt, balance, reminders, money dashboard; payment links 🟡 keys | |
| 12 | Email | Connected mailbox, sequence with A/B step, reply stops it, unsubscribe honoured, inbox | |
| 13 | Newsletters | List from a saved view, test send, send (company mailbox, capped), opens and clicks, unsubscribe; Postmark 🟡 | |
| 14 | Outreach | Campaign across inboxes (test company only), reply categories, drafts | |
| 15 | WhatsApp | Templates with header and buttons, photos and PDFs, 24-hour rule, STOP; 🟡 Meta | |
| 16 | Calls | Reported call on the timeline with recording, missed-call task, Calls list, settings; Twilio 🟡 account | |
| 17 | Phone app | Install from the download link, sign in, call tracking, recorder folder, caller popup | |
| 18 | Reports | Custom report (rep vs admin counts), save, share, CSV | |
| 19 | Lead ads and SMS | Webhook test events (fakes); 🟡 apps and provider | |
| 20 | Developers | API key, webhooks signed and retried, API log | |
| 21 | ACE in Core | Sign in with Core link, ACE summary panel, call analysis display; 🟡 ACE hosted | |
| 22 | Data protection | Export everything (zip, no secrets), download a person's data, erase a person | |
| 23 | Languages | Switch to Arabic (right to left) and Hindi; main screens translated | |
| 24 | Phone layout | Every screen above at phone width: menu, back button, no sideways scroll | |

# Data breach runbook (Versnq Core)

Written 2026-11-16. Use this when personal data may have been seen, taken, changed or lost by
someone who shouldn't have it. Speed matters more than perfection: start step 1 at once.

## 1. Contain (first hour)
- **A company's account was misused:** Settings → Security → **Sign out everyone** (takes
  effect at once). Ask the affected people to change their passwords and turn on two-factor.
  If an IP range is the problem, add the company's own addresses to the IP allowlist.
- **An API key, phone key or extension leaked:** revoke it (Settings → Developers, Settings →
  Calls → Phones with the app, Settings → Connected inboxes). It stops working at once.
- **The server itself:** take the affected service off the internet (nginx), keep the machine
  running so evidence isn't lost, and make a backup copy of the logs and database.
- Rotate every secret that may be exposed: `JWT_SECRET` (signs everyone out), the encryption
  key for connected-account secrets, SMTP, Twilio and payment keys.

## 2. Find out what happened (first day)
- Settings → Security → Sign-ins (who signed in from where), Settings → Audit log (who changed
  what), Developers → API log (what keys read), the server's nginx and app logs.
- Write down: what data, whose (which companies, how many people), from when to when, how.

## 3. Tell the right people
| Who | When | How |
|---|---|---|
| The affected companies (our customers) | As soon as the facts are known, within 24 hours | Email the owner; what happened, what data, what we did, what they should do |
| India: Data Protection Board (DPDP Act 2023) and the affected people | Without delay, as the DPDP Rules require | Through the Board's process; check the current rules at the time |
| EU/UK people affected (GDPR) | Within 72 hours of learning of it, to the supervisory authority; the people themselves when the risk is high | The authority's online form |
| CERT-In (India) | Within 6 hours of noticing certain cyber incidents | incident@cert-in.org.in; check the current CERT-In directions |

Our customers are the data controllers for their leads; we are their processor. Tell them
first and help them meet their own duties.

## 4. Fix and learn
- Fix the cause; add a test that would have caught it.
- Write a short report: timeline, cause, impact, what changed. Keep it with the audit trail.

## Tools Core has for this
- Sign out one person or everyone, at once.
- Sign-in history (180 days) and the audit log.
- IP allowlist and idle sign-out per company.
- Export everything (a company's own copy) and erase a person (requests from individuals).
- Revoke API keys, phone keys and extensions.

The legal deadlines above are a summary. They must be checked against the current law when a
breach happens; this file isn't legal advice.

# Calls and the phone app: how we build them

## The short version
**Is it doable?** Yes. I checked each step against the code and against what Android and Twilio allow.

| Step | Doable now? | What I can finish in auto mode |
|---|---|---|
| C1 Call pipeline in Core | Yes, fully | All of it: database, endpoints, timeline with player, missed-call tasks, 30-day recording cleanup, tests, deploy |
| C2 Installable web app | Yes | Install icon and offline page. Phone notifications need one new library (`pywebpush`), so I'll ask first |
| C3 Twilio calling | Yes, built and tested against Twilio's documented webhooks | The live test needs your Twilio test account |
| C4 Android app (SIM calls, own dialer, recording folder) | Yes, the Runo model works on phones whose own recorder works | **Not today:** it needs new tools (React Native + Android) approved, your phone to test on, and Google Play's call-log rules confirmed |
| C5 ACE call summaries | Yes | Core's side is in C1; the rest is the ACE session's work |

**What we gain:**
- Companies use the SIMs and numbers they already have. They pay for no extra calling service, which is the edge HubSpot doesn't have.
- Every call is on the lead automatically, with a recording and ACE's summary. Reps don't type, and managers hear every call.
- Calls, WhatsApp and email all land on one timeline next to money (invoices, payments).
- Cloud calling (Twilio) stays an option, for companies that want it.

**Order in auto mode:** C1 → C2 (no push until you OK the library) → C3. Then I stop for the C4 tools and your phone.

## Context
Suyog has decided Core gets calling and a phone app; what's open is how to build them. Two ways in, both feeding the same place:
1. **Cloud calling through the company's own Twilio account** (they own the account; Core never owns phone lines).
2. **The rep's own SIM calls through our Android app**: calls made from the rep's normal phone are logged, the recording is uploaded, ACE analyses it, and the summary lands on the lead (the Runo model). Many companies already own their numbers and SIMs, so this saves them an extra service; cloud calling stays an option.

We are not copying anyone. For reference only, from the vendors' own pages, checked Nov 16:
- **LeadSquared:**
  - No calling of its own: connectors to Exotel, Ozonetel and others for click-to-call, call logs, popups and recording links.
  - Its **Android** app tracks and records phone calls and SMS, works offline and has caller popups.
  - AI call analysis (Invorto).
- **HubSpot:**
  - Built-in calling on Twilio-powered numbers, or bring your own Twilio account.
  - Transcription on Pro; call analysis on Enterprise.
  - Its Android app prompts to log calls.

## What Core has today (checked in the code)
- **Calls:**
  - Calls are logged by hand only (`backend/app/modules/crm/work.py`): an Outcome is required, plus the next follow-up.
  - The Call button only opens `tel:` (`frontend/components/crm/lead-record.tsx`).
  - There are no fields for duration, direction or recordings.
- **Events:** `call.recorded` and `call.analyzed` are in the event list (`core/events.py`), but nothing emits them yet. ACE already expects to own transcription and analysis (`docs/ace/ACE-and-Core.md`, "call ingest, planned C6").
- **Finding a lead by phone number:** this already exists and can be reused.
  - `engage/whatsapp.py` `_lead_for()`: open leads first, then the most recent.
  - `engage/extension.py` `lookup()`: only leads the rep can see.
  - Numbers are stored in international format (`crm/identities.py`).
- **File storage** (`core/storage.py`): it only accepts PDFs, images and Office files, up to 10 MB, and each file must belong to a lead. **Audio needs its own kind of file.**
- **Phone readiness:** no installable web app (no manifest, service worker, icons or push). Notifications show only inside the app. The browser microphone is blocked by `Permissions-Policy` in `frontend/next.config.ts`.
- **Incoming provider messages:** the payment-gateway webhook (`money/router.py`) is the pattern to copy (signature check, rate limit, repeats ignored), plus an entry in `tests/core/test_routes_tripwire.py`.
- **Project rule:** `CLAUDE.md` lists "telephony, native mobile apps" as out of scope. **This line changes first**, now that you've decided.

## The design: one call pipeline, many sources
Every call, from the app, Twilio, or later Exotel, goes through the same steps in Core:

1. **A call arrives:** number, direction, start time, duration, status (answered, missed, no answer), rep, and the recording (if there is one).
2. Core **finds the lead by number**, reusing the lookup above.
   - If the number is unknown, Core makes a new lead or not, as the company chooses (default: make it, source "Phone").
3. Core **logs the call on the timeline** automatically, with direction, duration, a player for the recording, and the rep.
   - The existing one-step rules still apply: the rep picks the Outcome and the next follow-up in one tap.
   - A **missed call** becomes a "call back" task for the lead's owner.
4. Core stores the recording (a new audio file kind: mp3, m4a, aac, amr, wav, ogg; up to 50 MB; counts against the company's storage quota; **kept 30 days by default**, changeable per company; a nightly job removes older ones and the call entry stays) and sends the event **`call.recorded`**.
5. **ACE** turns the recording into text, writes the summary, intent, next step and red flags, then sends them back, and Core shows them on the call (**`call.analyzed`**). Speech-to-text lives in ACE, so Core has no new AI dependency.

### Rules
- Recording is **on or off per company**. When it's on, Core shows the reminder "tell the caller the call is recorded". The company is responsible for following the law in its country.
- A rep sees and plays only the calls of leads they can see, using the existing visibility rules. Recordings are never public links.

## Build order

### Step C1: the call pipeline in Core (the base for everything)
- **New table `calls`:**
  - lead
  - rep
  - direction
  - status
  - from and to numbers
  - start time and seconds
  - source (app, twilio, exotel)
  - the provider's call id, unique per source, so repeats are ignored
  - the recording file
  - the timeline activity
  - the summary, and when it was analysed
- Recordings become a new audio file kind in `core/storage.py`.
- Company settings: record calls on or off, make leads from unknown numbers, how long recordings are kept.
- **Endpoints:**
  - `POST /api/v1/calls`: the app or a provider reports a call.
  - `PUT /calls/{id}/recording`: upload the recording.
  - `GET /calls/{id}/recording`: play it, with visibility checked.
  - `PUT /calls/{id}/analysis`: ACE sends the summary.
- **Screens:** calls on the timeline with a player and the summary, and a calls list with filters (missed, by rep).
- **Events:** `call.logged` (new), `call.recorded`, `call.analyzed`.
- Migration 0035. Needs your approval.

### Step C2: installable web app (fast, alongside C1)
- Manifest, app icons, a service worker (opens quickly, shows a "you're offline" page) and an "Add to home screen" prompt.
- **Phone notifications (web push)** for a new lead, a missed call, or a task due.
  - Needs one new library (`pywebpush`) and keys on the server. Your approval is needed for the library.
- Works on Android and on iPhone (when added to the home screen).

### Step C3: cloud calling with the company's own Twilio
- In Settings, the company enters its Twilio account details and its numbers. They're stored encrypted, the same way WhatsApp keys are.
- **Click-to-call:** Twilio rings the rep's own phone first, then connects the lead, so no browser microphone is needed. This needs a "my phone number" field on each rep. A calling-from-the-browser option comes later.
- **Incoming calls:**
  - A call to the company's Twilio number rings the lead's owner, falling back to the company's main number.
  - An unanswered call gets a voicemail message and a missed-call task.
- Twilio reports the call's progress and the recording to Core (signature checked) and it goes through the pipeline.
- Plain HTTP calls to Twilio, so no new library. If Twilio's own library turns out to be needed, I'll ask first.

### Step C4: Android app: the rep's own SIM calls (the Runo model, as Suyog described it)
**How Runo does it (from Suyog, Nov 16):**
- After install, the app asks the rep to allow access to the **recording folder**.
- Companies use phones whose own recorder works (e.g. older Samsungs).
- Runo has **its own dialer**. When a call ends, it picks the recording up from that folder and has it transcribed.
- The admin can see every recording for **30 days**.

**Ours, the same way:**
- **Our own dialer in the app:** the rep calls from the app, or sets it as the phone's calling app. That way every call is ours to log, and we know exactly which call a recording belongs to (number + time).
- **Recording folder:**
  - At setup, the rep picks the folder the phone's own recorder saves to, using Android's folder picker. The app shows where it usually is on Samsung and other common phones.
  - After each call, the app takes the newest recording in that folder whose time matches the call, and uploads it through C1.
- **After each call:** a prompt for the Outcome and the next follow-up (the existing one-step rules). ACE then adds the summary (C5).
- **Recordings kept for 30 days** by default; the company can change it. Admins and managers can play any call they can see; reps play their own.
- **Also in the app:**
  - sign-in with the rep's Core account;
  - leads, tasks and the inbox in a phone layout;
  - push notifications;
  - a caller popup on incoming calls ("Asha Rao, lead, Data Science, owner Ravi").
- **To confirm before building** (I won't guess):
  - Google Play's rules for apps that act as the phone's calling app and read the call log: being the default calling app is the allowed case, and it needs Google's approval of a permissions form;
  - or companies get the app directly instead (a download link, or managed Google Play for company phones);
  - Android's battery and background limits;
  - which phones' recorders work, and where each saves.

  Your Runo test (on your phone, later) answers the last one.
- **Technology** (your approval needed, since it brings new tools):
  - React Native, sharing TypeScript and the API types with the web app;
  - a small native Android part for the call log and the recordings.
- **iPhone:** Apple doesn't let apps read the call log or recordings. iPhone users get the same app without SIM tracking, and use Twilio calling (C3) instead.

**Decided Nov 16 (Suyog, answers about Runo; Google policy checked):**
- Runo is **not** the default dialer. It starts calls from its own button, yet **logs every call** (it reads the call history). The recording comes from the **phone's own recorder** (older handsets).
- **Our app can't record calls itself:**
  - Android 10+ blocks call audio for ordinary apps.
  - Google Play has banned accessibility-based call recording since May 11, 2022.
  - The phone's built-in recorder is not affected.

  So the SIM route uses the phone's recorder. Phones without one use cloud calling (C3), which records on the provider's side and works on any phone, iPhone included. A company can mix both.
- **Call history** (`READ_CALL_LOG`): Google Play allows it for the default phone app, otherwise only by a case-by-case exception.
- **Distribution, decided:**
  - a **download link first** for pilot companies (no Play review);
  - Google Play later, as the calling app or with the exception, applied for in parallel.
  - Still to confirm on a real phone: Android's extra prompts for apps installed from a link.

### Step C5: ACE analyses calls (in the ACE project)
- ACE listens for `call.recorded`, fetches the recording, turns it into text, writes the summary, then sends it back with `PUT /calls/{id}/analysis`.
- Same pattern as drafts (C13 and C14). The speech-to-text service is ACE's decision (D7).

### Later
- Exotel for Indian cloud calling, using the same C3 pattern.
- Calling from the browser.
- A power dialer (call lists).
- An iOS app in the App Store.

## Where this sits in the tracker (`docs/TRACKER.md`)
1. **Now:**
   - Your own try of the forms.
   - The green-tick walk-through of every feature on the live server (Phase 1).
2. **Then:** C1 + C2 together → C3 → (your Runo test) → C4 → C5 with the ACE session.
3. **After that:** marketing, global and security from the tracker, in the order you choose.
4. **Your accounts, in parallel:**
   - A Twilio account (a test account is fine for C3).
   - Postmark (copy-in).
   - Meta verification.
   - Stripe and Razorpay keys.
5. **SES:** kept for later, when we're big enough to need high-volume sending of our own.

## Approvals needed (as each step starts, not all now)
- The `CLAUDE.md` scope line: telephony and the phone app move from out of scope to in.
- Migration 0035 (calls), with the C1 plan.
- New tools:
  - `pywebpush` (C2);
  - React Native plus the Android tooling (C4);
  - the Twilio library, only if plain HTTP isn't enough (C3).

## How each step is checked
- **C1:**
  - Backend tests: a reported call matches the right lead, repeats are ignored, a missed call makes a task, an unknown number follows the company's setting.
  - A recording can only be played by people who can see the lead, and another company's calls are invisible.
  - The analysis shows on the call.
  - A browser test: report a call through the API, see it on the timeline with a player.
- **C2:** a browser test checks the manifest and service worker. A push test runs against a test key. Then a real install on your phone.
- **C3:** tests use Twilio's documented webhook examples, with the signature check, repeats and recordings. Then a real call with your Twilio test account.
- **C4:** tests on a real Android phone (yours) with its built-in recorder on. The calls show on the lead within a minute.
- **For every step:** all tests green, then deploy with your OK, then your own try, then ✅ in the tracker.

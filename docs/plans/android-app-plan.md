# Android app (step C4): plan

Status: **C4.1–C4.4 built Nov 16** (approved by Suyog). Waiting for a try on a real phone. Push inside the app needs Firebase (later).
Parent plan: `calls-plan.md`. Decisions so far: Runo model (the phone's own recorder folder), a download link first and Google Play later.

## What the app is
It's a native Android app, installed from a download link and later from Google Play. It has two parts:

1. **The screens: the same Core app the rep already uses.** The app opens the company's own Core address (for example `versnq.core.versnq.in`) inside a native shell. Leads, tasks, inbox, calls, money and settings are the exact same screens, look and logins as the web. Every change to the web shows up in the app at once, with no second copy to keep in step.
2. **The phone part: a small native Android piece** that the web can't do:
   - **Dialer:** a Call button in the app places a normal SIM call.
   - **Call tracking:** when any call ends, the app reads that call from the phone's call log (number, in or out, start time, seconds, answered or missed) and reports it to Core with `POST /api/v1/calls`.
   - **Recordings:** once, at setup, the rep picks the folder the phone's own recorder saves to, using Android's folder picker. After each call, the app finds the recording whose time matches and uploads it with `PUT /calls/{id}/recording`. Core keeps it 30 days, and ACE summarises it (C5).
   - **Caller popup:** on an incoming call it shows who's calling ("Asha Rao, lead, owner Ravi"), using the existing phone lookup.
   - **Upload queue:** if the internet is off, calls and recordings wait and go up later. A call is never lost.
   - **Notifications:** the push we built in C2.

Everything talks to **the APIs Core already has** (C1 calls, C2 push, sign-in). Only one new endpoint is expected: a short "call me at this time" lookup for the caller popup, if the existing lookup isn't enough. I'll confirm that while building.

## Why this way (and not a fully separate app)
| Option | Look | Work | Risk |
|---|---|---|---|
| **A. Native shell around our web app plus a small native phone part (Capacitor)**, recommended | Identical, because it's the same screens | Small: only the phone part is new | Play Store may question a "website in a box". The phone features answer that, and it doesn't matter for a download link |
| B. Separate React Native app (the earlier plan) | Has to be redrawn to match, then kept matching | Large: every screen built twice | The two drift apart over time |
| C. Installable web app only (C2, live now) | Identical | None | It can't read the call log or the recorder folder, so there's no SIM tracking |

**This changes my earlier suggestion (React Native).** For "the same look as our app", A is simpler and stays in step by itself. It also gives an iPhone app later almost for free (without SIM tracking, which Apple doesn't allow).

## Where the code lives: the same repo, its own folder
- **A new folder `mobile/` in this Core repo**, next to `frontend/` and `extension/` (the Chrome extension already lives this way).
- It's independent: it builds on its own into an `.apk`, has its own version number, and never touches Core's database. It only calls the public API, the same as any other client.
- Why not a new repo:
  - The API and the app change together in one commit.
  - The tests run together.
  - The API types (`docs/api/openapi.json`) are shared, so they can't drift.

  If we ever hand the app to another team, it can be split out later.

## Signing in, and which company
- **First launch:** the rep types the company address, or scans a QR code from Settings → Phone app. Then they see the normal login screen, with 2FA as on the web.
- A rep with more than one company can switch, the same as on the web.

## Setup on the rep's phone (about 2 minutes, guided)
1. Install from the download link (Android asks to allow "install from this source" once).
2. Sign in.
3. Allow: phone and call log, notifications, and "show over other apps" (for the caller popup).
4. Pick the recorder folder. The app shows where it usually is on Samsung, Xiaomi, OnePlus and others, and checks that it can see a recent recording.
5. Turn off battery saving for the app. Some phones (Xiaomi, Oppo, Vivo) stop background apps, so the app shows the right screen for each.
6. A test call: the app checks the call appeared in Core with its recording.

Settings → Phone app in Core shows the admin each rep's status: app version, last call reported, whether recordings are working.

## Rules
- Recording stays on or off per company (C1 setting). When it's off, the app doesn't upload recordings.
- **Which calls are logged:** a call is reported only if the number belongs to a lead, or the company has "make leads from unknown numbers" on (C1 rule). The rep's personal calls to numbers that aren't leads are never sent. *(Open question 2 below.)*
- Recordings are never public. They're only played inside Core, for people who can see the lead.

## Steps
| Step | What | Check |
|---|---|---|
| C4.1 | Shell app: company address, login, all screens, push, Call button, download page + `.apk` on our server | Installs on your phone; same look as the web; a notification arrives |
| C4.2 | Call tracking from the call log, plus the upload queue | 10 test calls (in, out, missed, offline) all show on the lead within a minute |
| C4.3 | Recorder folder picker plus matching and upload | The recording plays on the lead; tested on your phone's recorder |
| C4.4 | Caller popup, plus Settings → Phone app status for admins | The popup shows the lead's name on an incoming call |
| Later | Google Play: the permissions form for the call log, store listing | Needs a Play developer account ($25 one-off) |

## What I need from you
1. **Approval of the approach:** option A (Capacitor shell plus a native Android part), in the `mobile/` folder of this repo.
2. **Approval of the new tools:**
   - Capacitor (open source, MIT) with its Android platform;
   - Android Studio and the Android SDK plus Java on this Mac, to build the `.apk`.
3. **An Android phone** for testing, with its built-in call recorder turned on. Tell me the brand and model.
4. **The signing key:** I'll create it on this Mac. It's kept outside git and backed up by you. Losing it means reps must reinstall.

## Open questions
1. Should the download link be public (`versnq.in/app`) or only shown to signed-in users in Core? I suggest only inside Core.
2. Calls to numbers that aren't leads: never send them (suggested, for privacy), or follow the company setting?
3. Is it fine to run only on Android 8 and later? That covers almost every phone in use.

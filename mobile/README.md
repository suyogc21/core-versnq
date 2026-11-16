# Versnq Core for Android

The Core web app in a native shell, plus the phone part (calls plan, step C4; plan:
`docs/plans/android-app-plan.md`).

- **Screens:** the company's own Core address (`https://<company>.core.versnq.in`), opened in
  the app, so the look and logins are the web's. The rep types the company once
  (`www/index.html`); `MainActivity` remembers it and opens it on every launch.
- **Native bridge:** Capacitor injects it only into that one address. Other links open outside
  the app. `versnq-core://reset` forgets the company.
- **The phone part:** call log, recorder folder, caller popup. Coming in C4.2–C4.4.
- **Build:** on GitHub (`.github/workflows/android.yml`). Every push to `mobile/` produces an
  `.apk` under the run's artifacts. Nothing has to be installed locally.
- **Capacitor** is pinned at 8.6.0 (approved by Suyog, Nov 16). Ask before adding any other
  dependency.

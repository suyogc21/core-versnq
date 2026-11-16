# Real forms: a builder and a hosted page (Tracker, Phase 1)

Written 2026-11-16 for Suyog. Nothing is built until you approve.

## The problem
Settings → Lead capture gives a "Form link", but it is only the address a website's form sends to. Opening it shows an error (Suyog hit this on Nov 15). There is no form you can share, and no way to build one without writing HTML.

## What we build
1. **Form builder** in Settings → Lead capture, for each form:
   - **Fields:** choose from the lead's fields (name, phone, email, company, custom fields), set label, required, order, and for choice fields the options.
   - **Consent:** a checkbox with the company's wording; WhatsApp and email opt-ins are kept as proof.
   - **After sending:** a thank-you message, or a redirect to your own page.
   - **Look:** title, short intro, button text, the company's logo and colour from branding settings.
2. **Hosted page** at `https://<company>.core.versnq.in/f/<form-id>`:
   - It works on phones, so you can share it on WhatsApp, Instagram or in ads.
   - It has spam protection (the existing hidden trap field and rate limits) and records where the lead came from (UTM tags and the page).
3. **Embed on a website:**
   - one line (`<iframe>`) for the hosted page, **or**
   - the existing "send to this address" code, for developers who style their own form.
4. **Fix the misleading label:** the posting address is renamed "Address for developers". The hosted page link becomes the main thing to copy, with an **Open** and a **Test** button.
5. Every submission goes through the existing path: duplicates checked, routing rules, timeline, `lead.created`.

## Schema (migration 0034)
`capture_sources` gets:
- `public_id`: short and random, used in the page link. The secret key stays secret.
- `form`: JSON holding the fields, consent, thank-you or redirect, and look.
- `hosted`: on or off.

No new tables. One new public endpoint: `GET /api/v1/forms/<public_id>` (what the page shows) and `POST` (the submission). The existing `/capture/<key>` stays as it is.

## Tests
- A form built with required fields refuses an empty submission, and a good one makes the lead with the right source, stage and consent.
- Duplicates follow the company's rule.
- A switched-off form shows "This form is closed".
- Another company's form id shows nothing.
- Rate limits and the spam trap work.
- Browser test: build a form, open the link on a phone-sized screen, send it, and see the lead in Leads.

## Decided (Nov 16, Suyog)
Approved. **No "Powered by Versnq"** on hosted forms; they show only the company's own branding.

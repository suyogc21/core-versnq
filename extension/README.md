# Versnq Core for WhatsApp (Chrome extension)

Step 10a, Decision log #41. Each rep keeps using their own WhatsApp. In WhatsApp Web, a side
panel shows the Versnq Core lead for the open chat, and chats with known leads are saved on the
lead's timeline and in the shared inbox. **It never sends anything by itself**: saved replies are
put into WhatsApp's message box and the rep presses Send. Group chats are never read. Messages of
people who are not leads never leave the computer.

## Build and try it

```sh
make extension            # compiles src/ into extension/dist (uses the frontend's TypeScript)
```

Chrome → `chrome://extensions` → turn on Developer mode → **Load unpacked** → choose
`extension/dist`. Open WhatsApp Web, click the Versnq icon to open the panel. In Versnq Core:
My account → WhatsApp extension → **Connect the extension**, then type the workspace address
and the code into the panel. Chrome asks once to allow that workspace address.

Works in Chrome, Edge and Brave (Manifest V3). No libraries.

## Files

| File | What it does |
| --- | --- |
| `src/reader.ts` | **Everything that reads WhatsApp Web.** When WhatsApp changes its page, fix this file only. |
| `src/content.ts` | Runs in WhatsApp Web: watches the open chat, puts saved replies into the message box. |
| `src/background.ts` | Holds the sign-in, asks Core "is this a lead?", sends a lead's messages (once each). |
| `src/panel.ts`, `src/panel.html` | The side panel. Built with textContent only. |

## Core endpoints it uses

`POST /api/v1/extension/connect` (one-time code → token), then with `Authorization: Bearer vq_ext_…`
(refused anywhere else in Core): `GET /lookup`, `GET /search`, `POST /link`, `POST /leads`,
`POST /messages`, `POST /leads/{id}/note`, `PUT /leads/{id}/follow-up`, `GET /replies`,
`GET /me`, `POST /disconnect` — all under `/api/v1/extension/`.

## Publishing

For customers it goes on the Chrome Web Store as **unlisted** (only people with the link can
install it). That needs a Google developer account (one-time fee) and a review of a few days.

## Known limits

- It reads only what WhatsApp Web shows on that computer. A chat done on the phone is saved when
  it is opened in WhatsApp Web ("Sync this chat").
- WhatsApp can change WhatsApp Web at any time; the reader may then need an update. Settings →
  Connected inboxes shows each rep's last activity, so a break is noticed.
- Photos, documents and voice notes are saved as "[photo]", "[document]", "[voice note]" for now.
- When WhatsApp Web shows no number for a chat, the rep links it to a lead once ("Link to lead").

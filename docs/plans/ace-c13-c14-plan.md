# ACE asks C13 and C14: built Nov 16 (contract in docs/ace/ACE-and-Core.md §14)

Written 2026-11-16 for Suyog. Both requests come from the ACE session. Nothing is built until you approve. One migration (0033) covers both.

## C13 Sign in with Core (for ACE's own console)

**Why:** a person opens ACE's console from Core without a second password; ACE knows who they are and which company.

- In Core, a person who may use ACE clicks **Open ACE**. Core makes a **one-time code** (kept in Redis, about 2 minutes, works once) and sends the browser to ACE's console with it.
- ACE swaps the code for the person: `POST /api/v1/ace/console-login {code}`, called with **that same company's** ACE API key. The key needs a new permission, **`ace.console_login`** (granted only to keys, never to people).
- Core answers with the person's id, name, email, role and the company. The answer contains no Core token, so ACE cannot act as the person in Core.
- Refusals: `code_invalid`, `code_expired`, `code_used`, `user_inactive`, `not_allowed` (a code from another company, or a key without the permission).
- Each sign-in is written to the company's audit log.
- **Starting at ACE instead** (someone types ACE's console address, or their session there ran out): ACE sends the browser to Core's page `/ace/open`. If they aren't signed in to Core, they sign in there as usual (password, plus the emailed code or the app), and Core then sends them back to ACE with a fresh one-time code. ACE never sees or stores a password, and there is no separate ACE account. Someone who uses only ACE still has a normal Core account: the Owner invites them and gives their role `ace.use`.
- Who sees **Open ACE**: only people with `ace.use` (new permission; Owner and Admin by default, Owners can give it to other roles). The ACE console address is one setting for all companies (an environment variable), not per company.

## C14 ACE declines to draft

**Why:** sometimes ACE should not write a reply (it doesn't know the answer, or the reply needs a person). Today the request just waits forever.

- `POST /api/v1/draft-requests/{request_id}/decline {reason}`: the reason is at most 500 characters, plain text.
- Core records it on the request, and the conversation shows **"ACE didn't draft this: <reason>"** to the people who can reply.
- Event **`draft.declined`** `{request_id, conversation_id, message_id, reason}`.
- Refusals: `unknown_request`, `request_already_answered` (a draft was made or it was declined), `request_superseded` (a newer reply came in). Sending the same decline twice is fine and answers the same.

## Schema (migration 0033)
- `draft_requests`: two new columns, `declined_at` and `decline_reason`.
- Permissions: `ace.console_login` (for keys) and `ace.use` (for people; Owner and Admin by default).
- The one-time codes live in Redis only, not in the database.

## Tests
- C13: a code works once, expires, and is refused by another company's key or a key without the permission. An inactive person is refused, and the sign-in is audited.
- C14: a decline is recorded, the event is sent, the three refusals work, and a repeated decline is fine. Sales Users see the note only on conversations they can see.

## Decided (Nov 16, Suyog)
Both approved, provided the sign-in also works when someone starts at ACE (covered above). By default, **Open ACE** is for Owner and Admin.

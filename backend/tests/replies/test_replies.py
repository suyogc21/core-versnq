"""Step O3 (the contract with ACE): the company's reply categories (exactly one Needs a human),
sorting by ACE or a person (a person wins), rules once per message, both inboxes, drafts (one
waiting per conversation, same request_id → same draft, out of date when they write again),
approve / reject in Core or for a person from Slack (that person's rights checked), the trail,
events, GET /conversations/{id} for campaign threads without marking read, another company sees
nothing."""

import uuid
from email.message import EmailMessage
from email.utils import make_msgid

from sqlalchemy import func, select

from app.core.events_model import Event
from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead, Suppression
from app.modules.engage import inbox as IB
from app.modules.engage.models import ConversationNote, ConversationRead, Message
from app.modules.outreach import engine as OE
from app.modules.outreach.models import CampaignContact, Contact
from app.modules.users.models import User
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_custom_role, make_workspace, switch_on
from tests.outreach.test_campaigns import (
    STEPS,
    _campaign,
    _inbox,
    _launch,
    _people,
    _reply_to,
    _sent,
)

ACE_PERMS = ("inbox.reply", "outreach.reply", "leads.create", "leads.edit",
             "drafts.approve_for_users")  # fmt: skip


async def _ace(c, admin, tenant_id) -> dict:
    role = await make_custom_role(tenant_id, f"ACE {uuid.uuid4().hex[:4]}", "all", ACE_PERMS)
    r = await c.post("/api/v1/integrations/keys", json={"name": "ACE", "role_id": str(role)},
                     headers=admin)  # fmt: skip
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['key']}"}


async def _campaign_reply(tenant_id, c, admin, owner_user_id=None):
    await _inbox(c, admin, f"x{uuid.uuid4().hex[:4]}@send.example")
    extra = {"owner_user_id": str(owner_user_id)} if owner_user_id else {}
    cid = await _campaign(c, admin, _people(1), steps=STEPS[:1], **extra)
    await _launch(c, admin, cid)
    await OE.run_due(tenant_id)
    sent = (await _sent(tenant_id, cid))[0]
    reply = await _reply_to(tenant_id, sent)
    return cid, sent, reply


async def _events(tenant_id, type_):
    async with tenant_session(tenant_id) as db:
        rows = await db.scalars(
            select(Event).where(Event.type == type_).order_by(Event.occurred_at)
        )
        return [e.payload for e in rows.all()]


def _cls(c, msg_id, h, category, **extra):
    return c.put(f"/api/v1/messages/{msg_id}/classification",
                 json={"category": category, **extra}, headers=h)  # fmt: skip


# ---------- categories ----------
async def test_every_company_starts_with_the_default_categories(ws):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    r = (await c.get("/api/v1/reply-categories", headers=rep)).json()
    keys = [x["key"] for x in r["categories"]]
    assert keys[:2] == ["interested", "meeting"] and keys[-1] == "needs_human"
    assert [x["key"] for x in r["categories"] if x["needs_human"]] == ["needs_human"]
    interested = r["categories"][0]
    assert [x["action"] for x in interested["rules"]] == ["convert", "draft", "notify"]


async def test_admins_change_the_list_but_needs_a_human_stays(ws):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    cats = (await c.get("/api/v1/reply-categories", headers=admin)).json()["categories"]
    keep = [x for x in cats if x["key"] in ("interested", "needs_human")]
    keep.insert(1, {"key": "pricing", "name": "Asks about price", "rules": [{"action": "draft",
                "instructions": "Share the price list"}]})  # fmt: skip
    url = "/api/v1/reply-categories"

    assert (await c.put(url, json={"categories": keep}, headers=rep)).status_code == 403
    r = await c.put(url, json={"categories": keep}, headers=admin)
    without = await c.put(url, json={"categories": keep[:2]}, headers=admin)

    assert r.status_code == 200, r.text
    assert [x["key"] for x in r.json()["categories"]] == ["interested", "pricing", "needs_human"]
    assert without.status_code == 422 and without.json()["code"] == "needs_human_required"
    assert await _events(tenant_id, "reply_categories.changed")


# ---------- sorting and rules ----------
async def test_ace_sorts_a_campaign_reply_and_the_rules_run_once(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, sent, reply = await _campaign_reply(tenant_id, c, admin)

    r = await _cls(c, reply.id, ace, "interested", confidence=92, summary="Wants a demo",
                   reasons=["asks for a demo"], prompt_version="v1")  # fmt: skip
    again = await _cls(c, reply.id, ace, "interested", confidence=92)

    assert r.status_code == 200, r.text
    assert r.json()["rules_run"] == ["convert", "draft", "notify"] and r.json()["draft_requested"]
    assert again.json()["rules_run"] == [] and not again.json()["draft_requested"]
    async with tenant_session(tenant_id) as db:
        contact = await db.get(Contact, sent.contact_id)
        assert contact.status == "converted" and contact.lead_id
        assert await db.scalar(select(func.count()).select_from(Lead)) == 1
    [classified] = await _events(tenant_id, "reply.classified")
    assert classified["category"] == "interested" and classified["by"] == "ace"
    [req] = await _events(tenant_id, "draft.requested")
    assert (
        req["message_id"] == str(reply.id) and req["request_id"] and req["category"] == "interested"
    )


async def test_a_persons_choice_wins_over_ace(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, _, reply = await _campaign_reply(tenant_id, c, admin)

    first = await _cls(c, reply.id, ace, "not_now")
    changed = await _cls(c, reply.id, ace, "question")  # ACE changes its mind: rules again
    by_hand = await _cls(c, reply.id, admin, "not_interested")
    refused = await _cls(c, reply.id, ace, "interested")

    assert first.json()["rules_run"] == ["stop"]
    assert changed.json()["rules_run"] == ["draft"]
    assert by_hand.json()["rules_run"] == ["stop"]
    assert refused.status_code == 409 and refused.json()["code"] == "classified_by_person"


async def test_lead_replies_in_the_normal_inbox_are_sorted_too(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"],
            identities=[{"type": "email", "value": "meera@client.example"}])).json()  # fmt: skip
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "meera@client.example", "us@company.example", "Stop"
    m["Message-ID"] = make_msgid(domain="client.example")
    m.set_content("Please remove me from your list")
    async with tenant_session(tenant_id) as db:
        msg = await IB.ingest(db, tenant_id, m.as_bytes())

    r = await _cls(c, msg.id, ace, "unsubscribe")

    assert r.json()["rules_run"] == ["unsubscribe"]
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(Suppression.id).where(
            Suppression.value_normalized == "meera@client.example"))  # fmt: skip
        assert (await db.get(Lead, uuid.UUID(lead["id"]))).email_consent == "opted_out"


# ---------- drafts ----------
async def _drafted(tenant_id, c, admin, ace, owner_user_id=None):
    cid, sent, reply = await _campaign_reply(tenant_id, c, admin, owner_user_id)
    await _cls(c, reply.id, ace, "question")
    [req] = await _events(tenant_id, "draft.requested")
    body = {
        "request_id": req["request_id"],
        "reply_to_message_id": str(reply.id),
        "body": "Good question: it takes a day to set up.",
        "reasons": ["answers setup time"],
    }
    r = await c.post(
        f"/api/v1/conversations/{reply.conversation_id}/drafts", json=body, headers=ace
    )
    assert r.status_code == 200, r.text
    return cid, sent, reply, r.json(), body  # fmt: skip


async def test_ace_drafts_once_per_request_and_a_person_approves_it(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, sent, reply, draft, body = await _drafted(tenant_id, c, admin, ace)

    same = await c.post(f"/api/v1/conversations/{reply.conversation_id}/drafts", json=body,
                        headers=ace)  # fmt: skip
    shown = (await c.get(f"/api/v1/conversations/{reply.conversation_id}/sorting",
                         headers=admin)).json()  # fmt: skip
    ok = await c.post(f"/api/v1/drafts/{draft['id']}/approve", json={}, headers=admin)

    assert same.json()["id"] == draft["id"] and draft["status"] == "pending"
    assert shown["draft"]["id"] == draft["id"]
    assert shown["sortings"][0]["category"] == "question"
    assert ok.status_code == 200, ok.text
    async with tenant_session(tenant_id) as db:
        out = await db.get(Message, uuid.UUID(ok.json()["message_id"]))
        assert out.direction == "out" and out.mailbox_id == sent.mailbox_id
        assert out.in_reply_to == reply.message_id_header and out.body.startswith("Good question")
    got = (await c.get(f"/api/v1/drafts/{draft['id']}", headers=ace)).json()
    assert got["status"] == "sent" and got["via"] == "core"
    [approved] = await _events(tenant_id, "draft.approved")
    assert approved["via"] == "core" and approved["body_changed"] is False
    assert [e["draft_id"] for e in await _events(tenant_id, "draft.created")] == [draft["id"]]


async def test_a_new_reply_makes_the_waiting_draft_out_of_date(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, sent, reply, draft, body = await _drafted(tenant_id, c, admin, ace)

    await _reply_to(tenant_id, sent, "Also, what about pricing?")
    late = await c.post(f"/api/v1/drafts/{draft['id']}/approve", json={}, headers=admin)
    stale = await c.post(f"/api/v1/conversations/{reply.conversation_id}/drafts",
                         json={**body, "request_id": None}, headers=ace)  # fmt: skip

    assert late.status_code == 422 and late.json()["code"] == "draft_superseded"
    assert stale.status_code == 422 and stale.json()["code"] == "draft_superseded"
    [ev] = await _events(tenant_id, "draft.superseded")
    assert ev["draft_id"] == draft["id"]


async def test_reject_then_nobody_can_decide_again(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    *_, draft, _ = await _drafted(tenant_id, c, admin, ace)

    no = await c.post(f"/api/v1/drafts/{draft['id']}/reject", json={"reason": "wrong tone"},
                      headers=admin)  # fmt: skip
    late = await c.post(f"/api/v1/drafts/{draft['id']}/approve", json={}, headers=admin)

    assert no.json()["status"] == "rejected"
    assert late.status_code == 422 and late.json()["code"] == "draft_already_decided"
    [ev] = await _events(tenant_id, "draft.rejected")
    assert ev["reason"] == "wrong tone"


async def test_slack_approval_acts_for_the_person_with_their_own_rights(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    riya_id, riya = await login_as(tenant_id, "sales_user")
    other_id, _ = await login_as(tenant_id, "sales_user")
    _, sent, reply, draft, _ = await _drafted(tenant_id, c, admin, ace, owner_user_id=riya_id)
    url = f"/api/v1/drafts/{draft['id']}/approve"

    by_admin = await c.post(url, json={"on_behalf_of_user_id": str(riya_id)}, headers=admin)
    stranger = await c.post(url, json={"on_behalf_of_user_id": str(other_id)}, headers=ace)
    async with tenant_session(tenant_id) as db:
        (await db.get(User, other_id)).status = "disabled"
    disabled = await c.post(url, json={"on_behalf_of_user_id": str(other_id)}, headers=ace)
    ok = await c.post(url, json={"on_behalf_of_user_id": str(riya_id),
                                 "body": "Edited: one day to set up."}, headers=ace)  # fmt: skip

    assert by_admin.status_code == 403  # only ACE's key acts for people
    assert stranger.status_code == 422 and stranger.json()["code"] == "user_cannot_approve"
    assert disabled.status_code == 422 and disabled.json()["code"] == "user_inactive"
    assert ok.status_code == 200, ok.text
    [ev] = await _events(tenant_id, "draft.approved")
    assert ev["via"] == "slack" and ev["decided_by_user_id"] == str(riya_id)
    assert ev["body_changed"] is True
    async with tenant_session(tenant_id) as db:
        out = await db.get(Message, uuid.UUID(ok.json()["message_id"]))
        assert out.sent_by_user_id == riya_id and out.body.startswith("Edited:")
        notes = (await db.scalars(select(ConversationNote.body).where(
            ConversationNote.conversation_id == reply.conversation_id))).all()  # fmt: skip
    assert any("via Slack (ACE)" in n for n in notes)


async def test_a_lead_draft_is_sent_from_the_crm(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, sources = await setup_ids(c, admin)
    await new_lead(c, admin, sources["Website"],
                   identities=[{"type": "email", "value": "dev@client.example"}])  # fmt: skip
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "dev@client.example", "us@company.example", "Pricing?"
    m["Message-ID"] = make_msgid(domain="client.example")
    m.set_content("How much is it?")
    async with tenant_session(tenant_id) as db:
        msg = await IB.ingest(db, tenant_id, m.as_bytes())
    await _cls(c, msg.id, ace, "question")
    [req] = await _events(tenant_id, "draft.requested")
    d = (await c.post(f"/api/v1/conversations/{msg.conversation_id}/drafts", json={
        "request_id": req["request_id"], "reply_to_message_id": str(msg.id),
        "body": "It starts at 999 a month."}, headers=ace)).json()  # fmt: skip

    ok = await c.post(f"/api/v1/drafts/{d['id']}/approve", json={}, headers=admin)

    assert ok.status_code == 200, ok.text
    async with tenant_session(tenant_id) as db:
        out = await db.get(Message, uuid.UUID(ok.json()["message_id"]))
    assert out.lead_id == msg.lead_id and out.subject == "Re: Pricing?"


# ---------- reading, isolation ----------
async def test_ace_reads_a_campaign_thread_without_marking_it_read(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    cid, sent, reply = await _campaign_reply(tenant_id, c, admin)

    r = await c.get(f"/api/v1/conversations/{reply.conversation_id}", headers=ace)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lead"] is None and body["contact"]["email"] == sent.to_address
    assert body["campaign"]["id"] == cid and body["campaign"]["step_sent"] == 1
    async with tenant_session(tenant_id) as db:
        assert await db.scalar(select(func.count()).select_from(ConversationRead)) == 0
    hidden = await c.get(f"/api/v1/conversations/{reply.conversation_id}?mark_read=false",
                         headers=admin)  # fmt: skip
    assert hidden.status_code == 200


async def test_another_company_cannot_touch_sortings_or_drafts(ws, client_for):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    *_, reply, draft, _ = await _drafted(tenant_id, c, admin, ace)
    other_id, other_slug = await make_workspace()
    await switch_on(other_id, "outreach")
    _, other_admin = await login_as(other_id, "admin")
    oc = client_for(other_slug)

    assert (await _cls(oc, reply.id, other_admin, "interested")).status_code == 404
    assert (await oc.get(f"/api/v1/drafts/{draft['id']}", headers=other_admin)).status_code == 404
    assert (await oc.post(f"/api/v1/drafts/{draft['id']}/approve", json={},
                          headers=other_admin)).status_code == 404  # fmt: skip
    async with tenant_session(other_id) as db:
        assert await db.scalar(select(func.count()).select_from(CampaignContact)) == 0

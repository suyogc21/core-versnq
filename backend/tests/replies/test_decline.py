"""C14 (docs/plans/ace-c13-c14-plan.md): ACE declines to draft, with a reason. Recorded on the
request, a note on the conversation, draft.declined; declining twice answers the same; refused
when unknown (or another company's), already answered, or out of date."""

import uuid

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.engage.models import ConversationNote
from app.modules.replies.models import DraftRequest
from tests.factories import login_as, make_workspace, switch_on
from tests.outreach.test_campaigns import _reply_to
from tests.replies.test_replies import _ace, _campaign_reply, _cls, _drafted, _events


def _decline(c, request_id, h, reason="I don't know the price for that plan."):
    return c.post(f"/api/v1/draft-requests/{request_id}/decline", json={"reason": reason},
                  headers=h)  # fmt: skip


async def _requested(tenant_id, c, admin, ace):
    _, sent, reply = await _campaign_reply(tenant_id, c, admin)
    await _cls(c, reply.id, ace, "question")
    req = (await _events(tenant_id, "draft.requested"))[-1]  # the newest request
    return sent, reply, req["request_id"]


async def test_ace_declines_and_the_people_answering_see_why(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, reply, request_id = await _requested(tenant_id, c, admin, ace)

    r = await _decline(c, request_id, ace)
    again = await _decline(c, request_id, ace, "a different reason")
    body = {"request_id": request_id, "reply_to_message_id": str(reply.id), "body": "Hi"}
    draft_after = await c.post(f"/api/v1/conversations/{reply.conversation_id}/drafts",
                               json=body, headers=ace)  # fmt: skip

    assert r.status_code == 200, r.text
    assert r.json()["reason"] == "I don't know the price for that plan."
    assert again.status_code == 200 and again.json()["reason"] == r.json()["reason"]
    assert draft_after.status_code == 422
    assert draft_after.json()["code"] == "request_already_answered"
    [ev] = await _events(tenant_id, "draft.declined")
    ev.pop("_actor")
    reason = "I don't know the price for that plan."
    assert ev == {"request_id": request_id, "conversation_id": str(reply.conversation_id),
                  "message_id": str(reply.id), "reason": reason}  # fmt: skip
    async with tenant_session(tenant_id) as db:
        req = await db.get(DraftRequest, uuid.UUID(request_id))
        notes = (await db.scalars(select(ConversationNote.body).where(
            ConversationNote.conversation_id == reply.conversation_id))).all()  # fmt: skip
    assert req.declined_at is not None
    assert "ACE didn't draft this: I don't know the price for that plan." in notes


async def test_decline_is_refused_when_answered_out_of_date_or_unknown(ws):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    *_, body = await _drafted(tenant_id, c, admin, ace)
    answered = await _decline(c, body["request_id"], ace)

    sent, _, request_id = await _requested(tenant_id, c, admin, ace)
    await _reply_to(tenant_id, sent, "Also, what about pricing?")
    late = await _decline(c, request_id, ace)
    unknown = await _decline(c, uuid.uuid4(), ace)
    empty = await _decline(c, request_id, ace, "")

    assert answered.status_code == 422 and answered.json()["code"] == "request_already_answered"
    assert late.status_code == 422 and late.json()["code"] == "request_superseded"
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_request"
    assert empty.status_code == 422
    assert await _events(tenant_id, "draft.declined") == []


async def test_another_company_and_people_without_the_thread_cannot_decline(ws, client_for):
    tenant_id, c, admin = ws
    ace = await _ace(c, admin, tenant_id)
    _, _, request_id = await _requested(tenant_id, c, admin, ace)
    other_id, other_slug = await make_workspace()
    await switch_on(other_id, "outreach")
    _, other_admin = await login_as(other_id, "admin")
    _, finance = await login_as(tenant_id, "finance")

    other = await _decline(client_for(other_slug), request_id, other_admin)
    no_rights = await _decline(c, request_id, finance)

    assert other.status_code == 422 and other.json()["code"] == "unknown_request"
    assert no_rights.status_code == 403
    assert await _events(tenant_id, "draft.declined") == []

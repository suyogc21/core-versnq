"""Batch 5a: A/B tests on sequence email steps. Each person gets the same variant every time
(from their enrolment), split by the step's share for B; messages record the variant; the step's
stats show both variants; a person can pick the winner, or it's picked by itself after N sends
(reply rate, then open rate); after a winner everyone gets it."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update

from app.core.tenancy import tenant_session
from app.modules.engage import engine as E
from app.modules.engage.models import Message
from tests.engage.test_sequences import _enrol, _lead, _messages, _run, _sequence, _template, ws  # noqa: F401
from tests.factories import login_as


def test_the_split_is_stable_and_roughly_follows_the_share():
    ab = {"split_b": 30}
    ids = [uuid.uuid4() for _ in range(2000)]
    first = [E.ab_variant(ab, i, 1) for i in ids]
    again = [E.ab_variant(ab, i, 1) for i in ids]
    assert first == again  # the same person always gets the same variant
    assert 0.25 < sum(first) / len(first) < 0.35
    assert E.ab_variant({**ab, "winner": "b"}, ids[0], 1) == 1
    assert E.ab_variant({**ab, "winner": "a"}, ids[0], 1) == 0


def test_the_better_variant_is_by_reply_rate_then_open_rate():
    base = {"sent": 10, "opened": 0, "clicked": 0, "replied": 0}
    assert E.better({0: {**base, "replied": 1}, 1: {**base, "replied": 3}}) == "b"
    assert E.better({0: {**base, "opened": 6}, 1: {**base, "opened": 2}}) == "a"
    assert E.better({0: base, 1: base}) == "a"


async def test_variants_are_sent_counted_and_a_winner_can_be_picked(ws):  # noqa: F811
    tenant_id, c, admin = ws
    t = await _template(c, admin, subject="Subject A")
    seq = await _sequence(c, admin, [
        {"kind": "email", "template_id": t["id"], "b_subject": "Subject B", "split_b": 50},
    ])  # fmt: skip
    assert seq["steps"][0]["config"]["ab"]["subject"] == "Subject B"
    leads = [await _lead(c, admin, email=f"p{i}@example.com") for i in range(12)]
    await _enrol(c, admin, seq, *leads)
    await _run(tenant_id)
    msgs = await _messages(tenant_id)
    by = {m.variant: m.subject for m in msgs}
    assert len(msgs) == 12 and by == {0: "Subject A", 1: "Subject B"}
    async with tenant_session(tenant_id) as db:  # B's people replied more
        await db.execute(
            update(Message).where(Message.variant == 1).values(replied_at=datetime.now(UTC))
        )
    stats = (await c.get(f"/api/v1/sequences/{seq['id']}/stats", headers=admin)).json()
    step = stats["steps"][0]
    counts = {v["variant"]: v["sent"] for v in step["variants"]}
    assert counts["a"] + counts["b"] == 12 and counts["a"] and counts["b"]
    assert step["leading"] == "b" and step["winner"] is None

    _, rep = await login_as(tenant_id, "sales_user")
    by_rep = await c.post(f"/api/v1/sequences/{seq['id']}/steps/1/winner",
                          json={"winner": "b"}, headers=rep)  # fmt: skip
    picked = await c.post(f"/api/v1/sequences/{seq['id']}/steps/1/winner",
                          json={"winner": "b"}, headers=admin)  # fmt: skip
    no_test = await c.post(f"/api/v1/sequences/{seq['id']}/steps/2/winner",
                           json={"winner": "a"}, headers=admin)  # fmt: skip
    assert by_rep.status_code == 403 and picked.json()["steps"][0]["winner"] == "b"
    assert no_test.status_code == 404

    late = await _lead(c, admin, email="late@example.com")
    await _enrol(c, admin, seq, late)
    await _run(tenant_id)
    newest = (await _messages(tenant_id))[-1]
    assert newest.subject == "Subject B" and newest.variant == 1


async def test_the_winner_is_picked_by_itself_after_enough_sends(ws):  # noqa: F811
    tenant_id, c, admin = ws
    t = await _template(c, admin, subject="Subject A")
    seq = await _sequence(c, admin, [
        {"kind": "email", "template_id": t["id"], "b_subject": "Subject B", "auto_pick_after": 10},
    ])  # fmt: skip
    leads = [await _lead(c, admin, email=f"q{i}@example.com") for i in range(12)]
    await _enrol(c, admin, seq, *leads)
    await _run(tenant_id)
    stats = (await c.get(f"/api/v1/sequences/{seq['id']}/stats", headers=admin)).json()
    assert stats["steps"][0]["winner"] == "a"  # level after 10 sends: A, the template, wins
    msgs = await _messages(tenant_id)
    assert {m.variant for m in msgs[10:]} == {0}  # everyone after the pick got the winner


async def test_a_step_without_variant_b_is_not_a_test(ws):  # noqa: F811
    tenant_id, c, admin = ws
    t = await _template(c, admin)
    seq = await _sequence(c, admin, [{"kind": "email", "template_id": t["id"]}])
    lead = await _lead(c, admin)
    await _enrol(c, admin, seq, lead)
    await _run(tenant_id)
    stats = (await c.get(f"/api/v1/sequences/{seq['id']}/stats", headers=admin)).json()
    assert "ab" not in seq["steps"][0]["config"] and stats["steps"][0]["variants"] == []
    assert (await _messages(tenant_id))[0].variant is None

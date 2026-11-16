"""ACE's lead summary (ACE step 1): only ACE's key writes it; it shows on the lead without a
timeline line or a version bump (so it never clashes with a rep editing the lead); the same
summary twice is a no-op; a change emits lead.summary_changed (an ACE event)."""

from sqlalchemy import func, select

from app.core.events_model import Event
from app.core.tenancy import tenant_session
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import switch_on
from tests.integrations.test_integrations import _key, bearer, ws  # noqa: F401


async def test_ace_summary_shows_on_the_lead_and_repeats_are_no_ops(ws):  # noqa: F811
    tenant_id, c, admin = ws
    await switch_on(tenant_id, "ace")
    key = await _key(c, admin, tenant_id, name="ACE")
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"])).json()
    url = f"/api/v1/leads/{lead['id']}/ace-summary"
    body = {"summary": "Wants the weekend batch; price is the worry.", "next_step": "Send EMI plan"}

    acts = f"/api/v1/leads/{lead['id']}/activities"
    before = (await c.get(acts, headers=admin)).json()
    first = await c.put(url, json=body, headers=bearer(key))
    again = await c.put(url, json=body, headers=bearer(key))
    by_person = await c.put(url, json=body, headers=admin)
    after = (await c.get(f"/api/v1/leads/{lead['id']}", headers=admin)).json()

    assert first.status_code == 200 and first.json()["changed"] is True
    assert again.json()["changed"] is False
    assert by_person.status_code == 403 and by_person.json()["code"] == "integration_only"
    assert after["ace_summary"] == body["summary"] and after["ace_next_step"] == "Send EMI plan"
    assert after["ace_summary_at"] and after["version"] == lead["version"]
    assert (await c.get(acts, headers=admin)).json() == before  # no timeline line
    async with tenant_session(tenant_id) as db:
        n = await db.scalar(
            select(func.count()).select_from(Event).where(Event.type == "lead.summary_changed")
        )
    assert n == 1


async def test_ace_summary_respects_what_the_key_can_see(ws):  # noqa: F811
    tenant_id, c, admin = ws
    _, sources = await setup_ids(c, admin)
    lead = (await new_lead(c, admin, sources["Website"])).json()  # not the rep's lead
    rep_key = await _key(c, admin, tenant_id, role="sales_user")
    r = await c.put(f"/api/v1/leads/{lead['id']}/ace-summary", json={"summary": "x"},
                    headers=bearer(rep_key))  # fmt: skip
    assert r.status_code == 404

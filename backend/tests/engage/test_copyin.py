"""Step 9b-2 (Decision log #40): copy-in addresses — CC / BCC / auto-forward lands on the right
lead, unknown people only become leads when the company says so, exclusions, duplicates,
reset, permissions and isolation."""

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.tenancy import tenant_session
from app.modules.crm.models import Lead
from app.modules.engage import copyin as CI
from app.modules.engage.models import Message
from tests.crm.helpers import new_lead, setup_ids
from tests.factories import login_as, make_workspace, switch_on


@pytest.fixture(autouse=True)
def files_dir(tmp_path):
    s = get_settings()
    old = s.files_dir
    s.files_dir = str(tmp_path / "files")
    yield
    s.files_dir = old


@pytest.fixture
async def ws(client_for):
    tenant_id, slug = await make_workspace()
    await switch_on(tenant_id, "copy_in")
    _, admin = await login_as(tenant_id, "admin")
    return tenant_id, client_for(slug), admin


def _mail(frm, to, subject, cc=(), msg_id=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Message-ID"] = msg_id or f"<{uuid.uuid4().hex}@mail.example>"
    m.set_content(f"About {subject}")
    return m.as_bytes()


async def _lead(c, h, email):
    _, sources = await setup_ids(c, h)
    r = await new_lead(
        c, h, sources["Website"], first_name="Asha",
        identities=[{"type": "email", "value": email}],
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def _email_of(tenant_id, user_id):
    from app.modules.users.models import User

    async with tenant_session(tenant_id) as db:
        return (await db.get(User, user_id)).email


async def _msgs(tenant_id):
    async with tenant_session(tenant_id) as db:
        return (await db.scalars(select(Message).order_by(Message.created_at))).all()


async def test_addresses_are_per_user_and_per_company_and_can_be_reset(ws):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    mine = (await c.get("/api/v1/me/copy-in", headers=rep)).json()
    again = (await c.get("/api/v1/me/copy-in", headers=rep)).json()
    company = (await c.get("/api/v1/copy-in", headers=admin)).json()
    assert mine["address"] == again["address"] != company["address"]
    assert mine["address"].endswith("@" + get_settings().inbound_email_domain)
    assert mine["live"] is False and company["create_leads"] is False
    assert (await c.get("/api/v1/copy-in", headers=rep)).status_code == 403
    new = (await c.post("/api/v1/me/copy-in/reset", headers=rep)).json()
    assert new["address"] != mine["address"]
    assert await CI.receive(_mail("x@y.example", "a@b.example", "Hi"), [mine["address"]]) == []


async def test_cc_on_a_reps_email_and_a_leads_email_land_on_the_lead(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, "asha@client.example")
    addr = (await c.get("/api/v1/me/copy-in", headers=rep)).json()["address"]
    rep_email = await _email_of(tenant_id, rep_id)

    # the rep writes from Outlook on their phone and BCCs the address (not in the headers)
    out = await CI.receive(_mail(rep_email, "Asha <ASHA@client.example>", "Proposal"), [addr])
    assert out[0].stored and str(out[0].lead_id) == lead["id"]
    # Asha answers; the rep's mail app auto-forwards it
    back = await CI.receive(_mail("asha@client.example", rep_email, "Re: Proposal"), [addr])
    assert back[0].stored and back[0].conversation_id == out[0].conversation_id
    rows = await _msgs(tenant_id)
    assert [(m.direction, m.subject) for m in rows] == [("out", "Proposal"), ("in", "Re: Proposal")]
    assert rows[0].sent_by_user_id == rep_id and rows[0].mailbox_id is None
    # the same email arriving twice (CC'd to two copy-in addresses) is kept once
    company = (await c.get("/api/v1/copy-in", headers=admin)).json()["address"]
    raw = _mail("asha@client.example", rep_email, "Twice")
    await CI.receive(raw, [addr, company])
    assert len(await _msgs(tenant_id)) == 3


async def test_unknown_people_become_leads_only_when_turned_on(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    addr = (await c.get("/api/v1/me/copy-in", headers=rep)).json()["address"]
    raw = _mail("Ravi Kumar <ravi@newco.example>", "sales@us.example", "Enquiry")
    assert (await CI.receive(raw, [addr]))[0].stored is False
    assert await _msgs(tenant_id) == []

    bad = await c.put("/api/v1/copy-in", json={"create_leads": True}, headers=admin)
    assert bad.status_code == 422  # a source is needed
    _, sources = await setup_ids(c, admin)
    r = await c.put(
        "/api/v1/copy-in",
        json={"create_leads": True, "source_id": sources["Website"]},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["create_leads"] is True
    res = (await CI.receive(raw, [addr]))[0]
    assert res.stored and res.created_lead
    async with tenant_session(tenant_id) as db:
        lead = await db.get(Lead, res.lead_id)
        assert lead.first_name == "Ravi" and lead.owner_user_id == rep_id  # the address's owner


async def test_exclusions_colleagues_and_our_own_address_are_never_leads(ws):
    tenant_id, c, admin = ws
    rep_id, rep = await login_as(tenant_id, "sales_user")
    _, sources = await setup_ids(c, admin)
    await c.put(
        "/api/v1/copy-in",
        json={"create_leads": True, "source_id": sources["Website"]},
        headers=admin,
    )
    await c.put("/api/v1/mailboxes/exclusions", json={"items": ["@lawfirm.example"]}, headers=admin)
    addr = (await c.get("/api/v1/me/copy-in", headers=rep)).json()["address"]
    rep_email = await _email_of(tenant_id, rep_id)
    admin_email = await _email_of(
        tenant_id, (await c.get("/api/v1/auth/me", headers=admin)).json()["id"]
    )
    await CI.receive(_mail("partner@lawfirm.example", rep_email, "Confidential"), [addr])
    await CI.receive(_mail(rep_email, admin_email, "Internal", cc=[addr]), [addr])
    assert await _msgs(tenant_id) == []


async def test_the_test_endpoint_and_isolation(ws, client_for):
    tenant_id, c, admin = ws
    _, rep = await login_as(tenant_id, "sales_user")
    lead = await _lead(c, rep, "asha@client.example")
    addr = (await c.get("/api/v1/me/copy-in", headers=rep)).json()["address"]
    r = await c.post(
        "/api/v1/inbox/test-copy-in",
        params={"to": addr},
        content=_mail("asha@client.example", "rep@us.example", "Hello"),
        headers=admin | {"Content-Type": "message/rfc822"},
    )
    assert r.status_code == 200 and r.json()[0]["lead_id"] == lead["id"]
    assert (
        await c.post("/api/v1/inbox/test-copy-in", params={"to": addr}, content=b"x", headers=rep)
    ).status_code == 403

    # another company's slug with this company's token finds nothing
    other_id, other_slug = await make_workspace()
    await switch_on(other_id, "copy_in")
    token = addr.split("@")[0].rsplit("-", 1)[1]
    forged = f"{other_slug}-{token}@{get_settings().inbound_email_domain}"
    assert await CI.receive(_mail("asha@client.example", "x@y.example", "Forged"), [forged]) == []
    assert len(await _msgs(tenant_id)) == 1 and await _msgs(other_id) == []


async def test_copy_in_is_hidden_and_ignored_while_switched_off(ws):
    from app.core.modules import set_module

    tenant_id, c, admin = ws
    addr = (await c.get("/api/v1/copy-in", headers=admin)).json()["address"]
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "copy_in", False)
    for path in ("/api/v1/copy-in", "/api/v1/me/copy-in"):
        assert (await c.get(path, headers=admin)).status_code == 404
    assert await CI.receive(_mail("asha@client.example", "x@y.example", "Hi"), [addr]) == []

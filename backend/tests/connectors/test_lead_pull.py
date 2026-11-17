"""Each rep's leads come in from the connected LeadSquared by themselves (connectors/pull.py):
owners are matched by email, leads of people not in Core stay in LeadSquared, a person Core
already has is linked (never doubled), a lead reassigned in LeadSquared moves in Core, the first
pull carries on page by page, pulled leads come in quietly, and their calls go back to the same
LeadSquared lead without a lookup. Answers shaped like apidocs.leadsquared.com (Users.Get,
Leads.RecentlyModified)."""

import json

import httpx
import pytest
from sqlalchemy import select, update

from app.core.tenancy import tenant_session
from app.modules.connectors import base as B
from app.modules.connectors import pull as P
from app.modules.connectors import service as S
from app.modules.connectors.models import CrmConnection
from app.modules.crm.models import ExternalRef, Lead, Notification
from app.modules.users.models import User
from tests.connectors.test_crm_connectors import FakeCrm, _call, _lsq, _setup


class FakeLsq(FakeCrm):
    def __init__(self):
        super().__init__()
        self.users: list[dict] = []
        self.changed: list[dict] = []  # each {Attribute: Value}

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if self.busy or not path.endswith(("Users.Get", "Leads.RecentlyModified")):
            return super().handler(req)
        if path.endswith("Users.Get"):
            self.requests.append(req)
            return httpx.Response(200, json=self.users)
        if path.endswith("Leads.RecentlyModified"):
            self.requests.append(req)
            paging = json.loads(req.content)["Paging"]
            size, at = paging["PageSize"], (paging["PageIndex"] - 1) * paging["PageSize"]
            page = self.changed[at : at + size]
            leads = [{"LeadPropertyList": [{"Attribute": k, "Value": v} for k, v in x.items()]}
                     for x in page]  # fmt: skip
            return httpx.Response(200, json={"RecordCount": len(page), "Leads": leads})
        return super().handler(req)


@pytest.fixture
def lsq(monkeypatch):
    f = FakeLsq()
    monkeypatch.setattr(
        B, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(f.handler))
    )
    return f


async def _email(tenant_id, user_id) -> str:
    async with tenant_session(tenant_id) as db:
        return (await db.get(User, user_id)).email


async def _pulled(tenant_id) -> dict[str, Lead]:
    async with tenant_session(tenant_id) as db:
        rows = (await db.execute(
            select(ExternalRef.external_id, Lead).join(Lead, Lead.id == ExternalRef.lead_id)
            .where(ExternalRef.system == "leadsquared")
        )).all()  # fmt: skip
    return {pid: lead for pid, lead in rows}


async def test_each_reps_leads_come_in_linked_and_quietly(ws, lsq):
    tenant_id, c, admin, rep_id, rep, lead = await _setup(ws)
    email = await _email(tenant_id, rep_id)
    lsq.users = [
        {"ID": "u-rep", "EmailAddress": email.upper(), "StatusCode": 0},  # same email, any case
        {"ID": "u-gone", "EmailAddress": email, "StatusCode": 1},  # inactive there: not matched
        {"ID": "u-other", "EmailAddress": "someone@else.com", "StatusCode": 0},  # not in Core
    ]
    lsq.changed = [
        {"ProspectID": "p-1", "FirstName": "Ravi", "LastName": "Kumar",
         "Mobile": "+91-9123456780", "OwnerId": "u-rep"},
        {"ProspectID": "p-2", "FirstName": "Asha", "Phone": "9876543210", "OwnerId": "u-rep"},
        {"ProspectID": "p-3", "FirstName": "Not ours", "Phone": "9000000001", "OwnerId": "u-other"},
        {"ProspectID": "p-4", "FirstName": "No way to reach", "Phone": "12", "OwnerId": "u-rep"},
    ]  # fmt: skip
    off = await c.put("/api/v1/crm-connection", json=_lsq(), headers=admin)
    nothing = await P.pull_tenant(tenant_id)  # not turned on: LeadSquared isn't asked
    asked_before = len(lsq.to("Leads.RecentlyModified"))
    on = await c.put("/api/v1/crm-connection", json=_lsq(pull_leads=True), headers=admin)
    first = await P.pull_tenant(tenant_id)
    soon = await P.pull_tenant(tenant_id)  # within 5 minutes: no new pull
    pulled = await _pulled(tenant_id)
    got = await c.get("/api/v1/crm-connection", headers=admin)

    assert off.status_code == on.status_code == 200, on.text
    assert nothing == {"created": 0, "moved": 0, "linked": 0} and asked_before == 0
    assert first == {"created": 1, "moved": 0, "linked": 1}
    assert soon == {"created": 0, "moved": 0, "linked": 0}
    assert set(pulled) == {"p-1", "p-2"}  # p-3 belongs to someone not in Core; p-4 unreadable
    assert pulled["p-1"].owner_user_id == rep_id and pulled["p-1"].display_name == "Ravi Kumar"
    assert pulled["p-1"].primary_phone == "+919123456780"
    assert str(pulled["p-2"].id) == lead["id"]  # Core already had Asha: linked, not doubled
    async with tenant_session(tenant_id) as db:
        told = (await db.scalars(select(Notification).where(
            Notification.lead_id == pulled["p-1"].id))).all()  # fmt: skip
        assert await db.scalar(select(Lead.id).where(Lead.display_name == "Not ours")) is None
    assert told == []  # LeadSquared already told the rep
    status = got.json()
    assert status["pull_leads"] is True and status["pull"]["owners"] == 1
    assert status["pull"]["created"] == 1 and "s3cr3t" not in got.text


async def test_a_lead_reassigned_in_leadsquared_moves_in_core(ws, lsq):
    tenant_id, c, admin, rep_id, rep, _ = await _setup(ws)
    from tests.factories import login_as

    rep2_id, _ = await login_as(tenant_id, "sales_user")
    lsq.users = [
        {"ID": "u-1", "EmailAddress": await _email(tenant_id, rep_id), "StatusCode": 0},
        {"ID": "u-2", "EmailAddress": await _email(tenant_id, rep2_id), "StatusCode": 0},
    ]
    lsq.changed = [{"ProspectID": "p-9", "FirstName": "Meera", "Phone": "9111111111",
                    "OwnerId": "u-1"}]  # fmt: skip
    await c.put("/api/v1/crm-connection", json=_lsq(pull_leads=True), headers=admin)
    await P.pull_tenant(tenant_id)
    lsq.changed[0]["OwnerId"] = "u-2"
    moved = await P.pull_tenant(tenant_id, force=True)
    to_rep2 = (await _pulled(tenant_id))["p-9"]
    lsq.changed[0]["OwnerId"] = "u-left-the-company"
    await P.pull_tenant(tenant_id, force=True)
    nobody = (await _pulled(tenant_id))["p-9"]

    assert moved["moved"] == 1 and to_rep2.owner_user_id == rep2_id
    assert nobody.owner_user_id is None  # given to someone without Core: leaves the rep


async def test_a_big_first_pull_carries_on_page_by_page(ws, lsq, monkeypatch):
    monkeypatch.setattr(P, "PAGE", 2)
    monkeypatch.setattr(P, "MAX_PAGES", 1)
    tenant_id, c, admin, rep_id, rep, _ = await _setup(ws)
    lsq.users = [{"ID": "u-1", "EmailAddress": await _email(tenant_id, rep_id), "StatusCode": 0}]
    lsq.changed = [{"ProspectID": f"p-{i}", "FirstName": f"Lead {i}", "Phone": f"91000000{i:02d}",
                    "OwnerId": "u-1"} for i in range(5)]  # fmt: skip
    await c.put("/api/v1/crm-connection", json=_lsq(pull_leads=True), headers=admin)
    runs = [(await P.pull_tenant(tenant_id))["created"] for _ in range(4)]

    assert runs == [2, 2, 1, 0]  # one page a run, then done until the next 5 minutes
    assert len(await _pulled(tenant_id)) == 5
    pages = [json.loads(r.content)["Paging"]["PageIndex"] for r in lsq.to("RecentlyModified")]
    assert pages == [1, 2, 3]


async def test_a_pulled_leads_calls_go_to_the_same_leadsquared_lead(ws, lsq):
    tenant_id, c, admin, rep_id, rep, _ = await _setup(ws)
    lsq.users = [{"ID": "u-1", "EmailAddress": await _email(tenant_id, rep_id), "StatusCode": 0}]
    lsq.changed = [{"ProspectID": "p-77", "FirstName": "Kiran", "Mobile": "9222222222",
                    "OwnerId": "u-1"}]  # fmt: skip
    await c.put("/api/v1/crm-connection", json=_lsq(pull_leads=True), headers=admin)
    await P.pull_tenant(tenant_id)
    await _call(c, rep, number="92222 22222")
    await S.run_tenant(tenant_id)

    logged = [json.loads(r.content) for r in lsq.to("Telephony.svc/LogCall")]
    assert [b["LeadId"] for b in logged] == ["p-77"]
    assert lsq.to("RetrieveLeadByPhoneNumber") == []  # known from the pull: no lookup


async def test_a_failed_pull_keeps_its_place_and_shows_in_settings(ws, lsq):
    tenant_id, c, admin, rep_id, rep, _ = await _setup(ws)
    lsq.users = [{"ID": "u-1", "EmailAddress": await _email(tenant_id, rep_id), "StatusCode": 0}]
    await c.put("/api/v1/crm-connection", json=_lsq(pull_leads=True), headers=admin)
    lsq.busy = 1
    failed = await P.pull_tenant(tenant_id)
    async with tenant_session(tenant_id) as db:
        conn = await db.scalar(select(CrmConnection))
        state, error = conn.config["pull"], conn.last_error
        await db.execute(update(CrmConnection).values(last_error=None))
    again = await P.pull_tenant(tenant_id)  # the same window, at once (not 5 minutes later)
    async with tenant_session(tenant_id) as db:
        again_error = (await db.scalar(select(CrmConnection))).last_error

    assert failed["created"] == 0 and "too many" in error
    assert state.get("until") and state["page"] == 1
    assert again == {"created": 0, "moved": 0, "linked": 0}
    assert len(lsq.to("Leads.RecentlyModified")) == 1  # the busy answer was on Users.Get
    assert again_error is None

import pytest
from sqlalchemy import select

from app.core.tenancy import platform_session, tenant_session
from app.modules.audit.models import AuditLog
from app.modules.crm.models import Lead, LeadStage, Task
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import Team
from app.modules.users.models import User
from app.platform.demo import FIELD_STAFF, DemoRefused, _reset_dev_database, seed_demo
from app.platform.models import Tenant


async def _tenant(slug: str) -> Tenant:
    async with platform_session() as s:
        return (await s.scalars(select(Tenant).where(Tenant.slug == slug))).one()


async def test_demo_seed_creates_three_companies_and_is_idempotent():
    first = await seed_demo(prefix="t1-")
    second = await seed_demo(prefix="t1-")

    acme, bluewave, sunrise = [await _tenant(f"t1-{s}") for s in ("acme", "bluewave", "sunrise")]
    async with tenant_session(acme.id) as s:
        users = (await s.scalars(select(User))).all()
        teams = {t.name: t for t in (await s.scalars(select(Team))).all()}
        audit_count = len((await s.scalars(select(AuditLog))).all())
        leads = (await s.scalars(select(Lead))).all()
        open_follow_ups = {
            t.lead_id: t.due_at
            for t in (
                await s.scalars(select(Task).where(Task.status == "open", Task.is_follow_up))
            ).all()
        }
    async with tenant_session(bluewave.id) as s:
        labels = (await s.get(TenantSettings, bluewave.id)).labels
        blue_leads = (await s.scalars(select(Lead))).all()
        blue_won = await s.scalar(select(LeadStage.id).where(LeadStage.name == "Won"))

    assert first.created and not second.created
    assert len(users) == 14 + FIELD_STAFF  # core cast + invented field staff (list at scale)
    assert {u.status for u in users} == {"active", "invited", "disabled"}
    assert all(not a.email.endswith("@field.acme.demo") for a in first.accounts)
    assert teams["Pune Counsellors"].parent_team_id == teams["Admissions"].id
    assert audit_count >= 14
    assert labels["lead"]["singular"] == "Buyer enquiry"
    # CRM demo data: every open lead's follow-up date matches its open follow-up task.
    assert len(leads) == 300 and len(blue_leads) == 60
    assert sum(1 for x in leads if x.owner_user_id is None) == 8
    for lead in leads:
        assert lead.next_follow_up_at == open_follow_ups.get(lead.id)
        assert lead.is_open or lead.next_follow_up_at is None
    won = [x for x in blue_leads if x.stage_id == blue_won]
    assert won and all(x.custom_fields.get("booking_ref") for x in won)  # stage requirement met
    assert (acme.status, bluewave.status, sunrise.status) == ("active", "active", "suspended")
    assert len(first.password) >= 12
    assert {"Owner", "Admin", "Sales Manager", "Sales User", "Versnq staff"} <= {
        a.role for a in first.accounts
    }


async def test_demo_seed_refuses_in_production(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "prod")
    with pytest.raises(DemoRefused):
        await seed_demo(prefix="never-")
    with pytest.raises(DemoRefused):  # --server needs ALLOW_DEMO_DATA too
        await seed_demo(prefix="never-", server=True)


async def test_the_shared_server_gets_three_demo_companies_and_no_demo_staff(monkeypatch):
    from app.core.config import get_settings
    from app.platform.staff.models import PlatformStaff

    s = get_settings()
    monkeypatch.setattr(s, "environment", "prod")
    monkeypatch.setattr(s, "allow_demo_data", True)
    monkeypatch.setattr(s, "secrets_encryption_key", s.secrets_encryption_key or "x" * 44)
    async with platform_session() as db:  # the real staff member created first
        db.add(PlatformStaff(email="first@srv.example", name="First", password_hash="x"))
    result = await seed_demo(prefix="srv-", server=True)
    assert result.slugs == ["srv-acme", "srv-bluewave", "srv-brightlane"]
    assert not any("staff" in a.role.lower() for a in result.accounts)
    async with platform_session() as db:
        assert not await db.scalar(
            select(PlatformStaff.id).where(PlatformStaff.email.like("%srv-demo%"))
        )
        assert not await db.scalar(select(Tenant.id).where(Tenant.slug == "srv-sunrise"))
    assert (await _tenant("srv-brightlane")).status == "active"


def test_demo_reset_never_touches_a_database_other_than_dev():
    # Tests run against versnq_test, so the reset must refuse.
    with pytest.raises(DemoRefused):
        _reset_dev_database()


def test_credentials_file_lists_every_account(tmp_path):
    from app.platform.demo import Account, DemoResult, write_credentials_file

    result = DemoResult(
        created=True,
        password="pw-123456789",
        accounts=[Account("Acme Academy", "Owner", "Riya Sharma", "owner@acme.demo")],
    )
    text = write_credentials_file(result, "localhost", tmp_path / "creds.md").read_text()
    assert (
        "`pw-123456789`" in text
        and "| Acme Academy | Owner | Riya Sharma | owner@acme.demo |" in text
    )
    assert "http://acme.localhost:3000/login" in text

import pytest
from sqlalchemy import select

from app.core.tenancy import platform_session, tenant_session
from app.modules.audit.models import AuditLog
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import Team
from app.modules.users.models import User
from app.platform.demo import DemoRefused, _reset_dev_database, seed_demo
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
    async with tenant_session(bluewave.id) as s:
        labels = (await s.get(TenantSettings, bluewave.id)).labels

    assert first.created and not second.created
    assert len(users) == 14
    assert {u.status for u in users} == {"active", "invited", "disabled"}
    assert teams["Pune Counsellors"].parent_team_id == teams["Admissions"].id
    assert audit_count >= 14
    assert labels["lead"]["singular"] == "Buyer enquiry"
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


def test_demo_reset_never_touches_a_database_other_than_dev():
    # Tests run against versnq_test, so the reset must refuse.
    with pytest.raises(DemoRefused):
        _reset_dev_database()

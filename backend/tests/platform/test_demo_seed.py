import pytest
from sqlalchemy import select

from app.core.tenancy import platform_session, tenant_session
from app.modules.users.models import User
from app.platform.demo import DemoRefused, seed_demo
from app.platform.models import Tenant


async def test_demo_seed_creates_workspace_and_is_idempotent():
    first = await seed_demo(slug="demo-acme")
    second = await seed_demo(slug="demo-acme")

    async with platform_session() as s:
        tenant = (await s.scalars(select(Tenant).where(Tenant.slug == "demo-acme"))).one()
    async with tenant_session(tenant.id) as s:
        users = (await s.scalars(select(User))).all()

    assert first.created and not second.created
    assert {u.status for u in users} == {"active"} and len(users) == 4
    assert {a.role for a in first.accounts} == {
        "Owner",
        "Sales Manager",
        "Sales User",
        "Versnq staff",
    }
    assert all(len(a.password) >= 12 for a in first.accounts)


async def test_demo_seed_refuses_in_production(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "prod")
    with pytest.raises(DemoRefused):
        await seed_demo(slug="never")

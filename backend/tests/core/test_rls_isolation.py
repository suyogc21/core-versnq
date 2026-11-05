"""Row-level security on tenant tables, exercised as the runtime role (versnq_app)."""

import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.tenancy import platform_session, tenant_session
from app.modules.roles.models import Role
from app.modules.users.models import User
from tests.factories import make_role, make_tenant


async def test_context_a_sees_only_a_rows():
    a, b = await make_tenant(), await make_tenant()
    role_a = await make_role(a, "A role")
    await make_role(b, "B role")

    async with tenant_session(a) as s:
        ids = set((await s.scalars(select(Role.id))).all())

    assert role_a in ids
    async with tenant_session(a) as s:
        tenants_seen = set((await s.scalars(select(Role.tenant_id))).all())
    assert tenants_seen == {a}


async def test_no_context_sees_zero_rows():
    a = await make_tenant()
    await make_role(a, "A role")

    async with platform_session() as s:
        assert (await s.scalars(select(Role))).all() == []


async def test_insert_with_other_tenant_id_rejected():
    a, b = await make_tenant(), await make_tenant()

    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(a) as s:
            s.add(Role(tenant_id=b, name="sneaky", scope="all", is_system=False))
            await s.flush()


async def test_update_cannot_move_row_to_other_tenant():
    a, b = await make_tenant(), await make_tenant()
    role_a = await make_role(a, "A role")

    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(a) as s:
            await s.execute(update(Role).where(Role.id == role_a).values(tenant_id=b))


async def test_user_cannot_reference_other_tenants_role():
    a, b = await make_tenant(), await make_tenant()
    role_b = await make_role(b, "B role")

    with pytest.raises(IntegrityError):
        async with tenant_session(a) as s:
            s.add(User(tenant_id=a, email="x@a.com", name="X", role_id=role_b, status="invited"))
            await s.flush()


async def test_email_unique_per_tenant_case_insensitive():
    a = await make_tenant()
    role = await make_role(a, "R")
    async with tenant_session(a) as s:
        s.add(User(tenant_id=a, email="Priya@Acme.com", name="P", role_id=role, status="invited"))

    with pytest.raises(IntegrityError):
        async with tenant_session(a) as s:
            s.add(
                User(tenant_id=a, email="priya@acme.com", name="P2", role_id=role, status="invited")
            )
            await s.flush()


async def test_same_email_allowed_in_another_tenant():
    a, b = await make_tenant(), await make_tenant()
    ra, rb = await make_role(a, "R"), await make_role(b, "R")
    async with tenant_session(a) as s:
        s.add(User(tenant_id=a, email="consultant@x.com", name="C", role_id=ra, status="invited"))
    async with tenant_session(b) as s:
        s.add(User(tenant_id=b, email="consultant@x.com", name="C", role_id=rb, status="invited"))

    async with tenant_session(b) as s:
        assert len((await s.scalars(select(User.id))).all()) == 1


async def test_every_tenant_table_has_forced_rls():
    """Tripwire: any table with a tenant_id column must have RLS enabled and forced."""
    async with platform_session() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                    """
                )
            )
        ).all()

    assert rows, "expected at least one tenant table"
    unprotected = [r.relname for r in rows if not (r.relrowsecurity and r.relforcerowsecurity)]
    assert unprotected == []


async def test_unknown_tenant_context_sees_nothing():
    async with tenant_session(uuid.uuid4()) as s:
        assert (await s.scalars(select(Role))).all() == []

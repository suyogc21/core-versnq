"""Every table that holds company data must have forced row-level security."""

from sqlalchemy import text

from app.core.tenancy import platform_session

# Platform tables that legitimately carry tenant_id without RLS. Keep empty unless justified.
PLATFORM_ONLY: set[str] = set()


async def test_every_tenant_table_has_forced_rls():
    async with platform_session() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN information_schema.columns col
                      ON col.table_name = c.relname AND col.table_schema = n.nspname
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                      AND col.column_name = 'tenant_id'
                    """
                )
            )
        ).all()
    unprotected = [
        r.relname
        for r in rows
        if r.relname not in PLATFORM_ONLY and not (r.relrowsecurity and r.relforcerowsecurity)
    ]
    assert rows, "expected tenant tables"
    assert unprotected == []

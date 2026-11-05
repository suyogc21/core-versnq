"""Shared migration helpers. Every tenant table must call enable_tenant_rls()."""

import re

from alembic import op

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _checked(table: str) -> str:
    if not _IDENTIFIER.match(table):
        raise ValueError(f"Invalid table name: {table!r}")
    return table


def enable_tenant_rls(table: str) -> None:
    """Lock a table to the current tenant, including for the table owner."""
    t = _checked(table)
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {t} "
        "USING (tenant_id = app_current_tenant()) "
        "WITH CHECK (tenant_id = app_current_tenant())"
    )


def disable_tenant_rls(table: str) -> None:
    t = _checked(table)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
    op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")

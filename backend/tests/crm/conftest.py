import pytest

from tests.factories import login_as, make_workspace


@pytest.fixture
async def ws(client_for):
    """(tenant_id, client) for a fresh workspace (generic pack)."""
    tenant_id, slug = await make_workspace()
    return tenant_id, client_for(slug)


@pytest.fixture
async def admin(ws):
    tenant_id, c = ws
    _, headers = await login_as(tenant_id, "admin")
    return c, headers

import pytest

from tests.factories import make_workspace


@pytest.fixture
async def ws(client_for):
    """(tenant_id, client) for a fresh workspace."""
    tenant_id, slug = await make_workspace()
    return tenant_id, client_for(slug)

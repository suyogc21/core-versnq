"""Batch 6 (global): ready-made tax rates per country. A company adds a country's rates; ones it
already has (by name) are left alone; finance-settings permission is needed; rates stay editable."""

from app.core.modules import set_module
from app.core.tenancy import tenant_session
from tests.factories import login_as, make_workspace


async def test_adding_a_countrys_rates_skips_ones_the_company_has(client_for):
    tenant_id, slug = await make_workspace()
    async with tenant_session(tenant_id) as db:
        await set_module(db, tenant_id, "money", True)
    c = client_for(slug)
    _, admin = await login_as(tenant_id, "admin")
    _, rep = await login_as(tenant_id, "sales_user")

    presets = (await c.get("/api/v1/money/tax-presets", headers=admin)).json()
    uk = await c.post("/api/v1/money/tax-presets/GB", headers=admin)
    fr = await c.post("/api/v1/money/tax-presets/FR", headers=admin)
    nowhere = await c.post("/api/v1/money/tax-presets/ZZ", headers=admin)
    by_rep = await c.post("/api/v1/money/tax-presets/GB", headers=rep)

    by_country = {p["country"]: p for p in presets}
    assert by_country["SA"]["rates"][0]["parts"] == [{"name": "VAT", "rate_bp": 1500}]
    assert by_country["GB"]["tax_label"] == "VAT number"
    names = [r["name"] for r in fr.json()]
    assert uk.status_code == 200 and names.count("VAT 20%") == 1  # France didn't add it twice
    assert "Reverse charge (EU B2B)" in names and names.count("No tax") == 1
    assert nowhere.status_code == 404 and by_rep.status_code == 403

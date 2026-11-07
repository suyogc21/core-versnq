"""Every company starts with its industry pack's CRM setup; nothing is industry-coded."""

from sqlalchemy import select

from app.core.tenancy import tenant_session
from app.modules.auth.deps import effective_permissions
from app.modules.crm.models import ActivityType, CustomFieldDefinition, LeadSource, LeadStage
from app.modules.crm.setup import ensure_crm_setup, seed_crm
from app.modules.roles.models import Role
from app.platform.packs import load_pack
from tests.factories import make_tenant, make_workspace


async def _setup(tenant_id):
    async with tenant_session(tenant_id) as s:
        stages = (await s.scalars(select(LeadStage).order_by(LeadStage.position))).all()
        sources = (await s.scalars(select(LeadSource.name))).all()
        fields = (await s.scalars(select(CustomFieldDefinition))).all()
        types = {t.key: t for t in (await s.scalars(select(ActivityType))).all()}
    return stages, sources, fields, types


async def test_generic_company_gets_stages_sources_and_system_activity_types():
    tenant_id, _ = await make_workspace()
    stages, sources, fields, types = await _setup(tenant_id)

    assert [s.name for s in stages][:2] == ["New", "Contacted"]
    invalid = stages[-1]
    assert (invalid.name, invalid.is_open, invalid.is_unqualified, invalid.is_system) == (
        "Invalid",
        False,
        True,
        True,
    )
    assert "Website" in sources and fields == []
    call = types["call"]
    outcome = call.fields[0]
    assert outcome["key"] == "disposition" and outcome["required"] is True
    assert {"interested", "not_reachable"} <= {o["value"] for o in outcome["options"]}
    assert types["stage_changed"].is_loggable is False and types["note"].is_loggable is True


async def test_edtech_pack_brings_linked_unique_and_stage_required_fields():
    tenant_id = await make_tenant()
    async with tenant_session(tenant_id) as s:
        await seed_crm(s, tenant_id, load_pack("edtech"))
    stages, _, fields, types = await _setup(tenant_id)

    by_key = {f.key: f for f in fields}
    assert by_key["batch"].depends_on == "program_interest"
    assert all(o.get("parent") for o in by_key["batch"].options)
    assert by_key["application_number"].is_unique is True
    assert next(s for s in stages if s.name == "Application").required_fields == [
        "program_interest"
    ]
    assert "demo_class" in types


async def test_company_created_before_the_crm_is_seeded_on_first_use():
    tenant_id = await make_tenant()  # no CRM rows yet
    async with tenant_session(tenant_id) as s:
        await ensure_crm_setup(s, tenant_id)
        await ensure_crm_setup(s, tenant_id)  # second call changes nothing
    stages, *_ = await _setup(tenant_id)
    assert len([s for s in stages if s.name == "Invalid"]) == 1


async def test_default_lead_permissions_per_role():
    tenant_id, _ = await make_workspace()
    async with tenant_session(tenant_id) as s:
        roles = {r.key: r for r in (await s.scalars(select(Role))).all()}
        perms = {k: await effective_permissions(s, r) for k, r in roles.items()}

    assert {"leads.create", "leads.edit"} <= perms["sales_user"]
    assert "leads.assign" not in perms["sales_user"] and "leads.delete" not in perms["sales_user"]
    assert "leads.assign" in perms["sales_manager"] and "leads.delete" not in perms["sales_manager"]
    assert {"leads.delete", "crm.configure"} <= perms["admin"]
    assert not {c for c in perms["finance"] if c.startswith("leads.")}

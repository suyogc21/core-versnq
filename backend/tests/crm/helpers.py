import uuid

from app.core.tenancy import tenant_session
from app.modules.teams.models import Team, TeamMember


async def make_team(tenant_id, manager_id, member_ids, name=None) -> uuid.UUID:
    async with tenant_session(tenant_id) as s:
        team = Team(tenant_id=tenant_id, name=name or f"Team {uuid.uuid4().hex[:6]}")
        s.add(team)
        await s.flush()
        s.add(TeamMember(tenant_id=tenant_id, team_id=team.id, user_id=manager_id, is_manager=True))
        for m in member_ids:
            s.add(TeamMember(tenant_id=tenant_id, team_id=team.id, user_id=m, is_manager=False))
    return team.id


async def setup_ids(c, h):
    stages = {s["name"]: s for s in (await c.get("/api/v1/lead-stages", headers=h)).json()}
    sources = {s["name"]: s["id"] for s in (await c.get("/api/v1/lead-sources", headers=h)).json()}
    return stages, sources


async def new_lead(c, h, source_id, phone="98765 43210", **extra):
    body = {
        "first_name": "Rahul",
        "identities": [{"type": "phone", "value": phone}],
        "source_id": source_id,
    } | extra
    return await c.post("/api/v1/leads", json=body, headers=h)

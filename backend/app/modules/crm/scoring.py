"""Rule-based lead scoring (Decision log #27, A5).

score = fit + engagement
  fit:        points for each active fit rule whose condition holds ("source is Website +10")
  engagement: points per matching activity in the last N days ("each Interested call +15")
band: hot (>= hot_score), warm (>= warm_score), cold otherwise. ACE intent stays separate.

Recalculated whenever a lead changes or an activity is logged, and nightly (the window moves).
"""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import emit
from app.core.tenancy import platform_session, tenant_session
from app.modules.crm import conditions as C
from app.modules.crm import leads as L
from app.modules.crm.models import Activity, Lead, ScoreRule
from app.modules.settings.models import TenantSettings
from app.platform.models import Tenant


@dataclass
class Breakdown:
    fit: int = 0
    engagement: int = 0
    lines: list[dict] = field(default_factory=list)  # {kind, label, points}

    @property
    def total(self) -> int:
        return self.fit + self.engagement


async def _rules(db: AsyncSession) -> list[ScoreRule]:
    return list(
        (
            await db.scalars(
                select(ScoreRule).where(ScoreRule.is_active.is_(True)).order_by(ScoreRule.position)
            )
        ).all()
    )


async def _settings(db: AsyncSession, tenant_id: uuid.UUID) -> TenantSettings:
    return await db.get(TenantSettings, tenant_id)


def band(score: int, s: TenantSettings) -> str:
    if score >= s.hot_score:
        return "hot"
    return "warm" if score >= s.warm_score else "cold"


async def compute(db: AsyncSession, lead: Lead, rules=None, settings=None) -> Breakdown:
    rules = rules if rules is not None else await _rules(db)
    settings = settings or await _settings(db, lead.tenant_id)
    out = Breakdown()
    if not rules:
        return out
    facts = await C.lead_facts(db, lead)
    for r in rules:
        if r.kind == "fit" and C.match(r.condition, facts):
            out.fit += r.points
            out.lines.append({"kind": "fit", "rule_id": str(r.id), "points": r.points, "times": 1})
    engagement = [r for r in rules if r.kind == "engagement"]
    if engagement:
        since = L.now() - timedelta(days=settings.engagement_days)
        # The key is a literal, so SELECT and GROUP BY are the very same expression.
        disp = Activity.data.op("->>")(literal_column("'disposition'"))
        counts = (
            await db.execute(
                select(Activity.type_key, disp, func.count())
                .where(Activity.lead_id == lead.id, Activity.occurred_at >= since)
                .group_by(Activity.type_key, disp)
            )
        ).all()
        for r in engagement:
            n = sum(
                c
                for key, disp, c in counts
                if key == r.activity_type_key and (r.disposition is None or disp == r.disposition)
            )
            if n:
                out.engagement += n * r.points
                out.lines.append(
                    {"kind": "engagement", "rule_id": str(r.id), "points": n * r.points, "times": n}
                )
    return out


async def refresh(db: AsyncSession, lead: Lead, rules=None, settings=None) -> bool:
    """Store the lead's score and band. Returns True when anything changed."""
    settings = settings or await _settings(db, lead.tenant_id)
    b = await compute(db, lead, rules, settings)
    new = (b.fit, b.engagement, b.total, band(b.total, settings))
    old = (lead.fit_score, lead.engagement_score, lead.score, lead.score_band)
    if new == old:
        return False
    lead.fit_score, lead.engagement_score, lead.score, lead.score_band = new
    await L.refresh_calculated(db, lead, "lead")
    # A plain emit (not L.event) so this never loops back into scoring.
    await emit(
        db,
        lead.tenant_id,
        "lead.updated",
        {"lead_id": str(lead.id), "fields": ["score"], "score": b.total, "band": new[3]},
    )
    return True


async def rescore_tenant(tenant_id: uuid.UUID, batch: int = 500) -> int:
    """Every lead of one company (after a rule change, and nightly)."""
    changed, last = 0, None
    while True:
        async with tenant_session(tenant_id) as db:
            rules = await _rules(db)
            settings = await _settings(db, tenant_id)
            q = select(Lead).order_by(Lead.id).limit(batch)
            if last:
                q = q.where(Lead.id > last)
            leads = (await db.scalars(q)).all()
            for lead in leads:
                changed += await refresh(db, lead, rules, settings)
        if len(leads) < batch:
            return changed
        last = leads[-1].id


async def rescore_all() -> int:
    async with platform_session() as s:
        ids = (await s.scalars(select(Tenant.id).where(Tenant.status == "active"))).all()
    return sum([await rescore_tenant(t) for t in ids])

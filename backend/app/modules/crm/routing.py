"""Who gets a new lead (assignment rules), response-time rules (SLAs) and the leakage guard.

Assignment rules run top to bottom; the first rule whose conditions all match decides.
Strategies: round_robin (equal turns over chosen users or a team's members, skipping anyone
not active), user (one person), unassigned (leave it for a manager). No match = unassigned.

An SLA clock starts when a lead is created or enters a stage. It is met when the lead is
contacted (a call or other contact activity) before the deadline; otherwise it is missed once,
written on the timeline, and the rule's action runs (alert the manager, or reassign).

Leakage guard (per company, off by default): an open lead is leaking when it was never
contacted X hours after arriving, or its follow-up is more than X hours overdue. Each lead is
flagged once until someone works it again.
"""

import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import platform_session, tenant_session
from app.modules.crm import leads as L
from app.modules.crm.models import AssignmentRule, Lead, LeadSla, LeadStage, SlaRule, Task
from app.modules.crm.notify import managers_of, notify
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import TeamMember
from app.modules.users.models import User
from app.platform.models import Tenant

BUILTIN_CONDITION_FIELDS = {
    "source": lambda lead: str(lead.source_id),
    "kind": lambda lead: lead.kind,
    "origin": lambda lead: lead.origin,
    "created_via": lambda lead: lead.created_via,
    "preferred_language": lambda lead: lead.preferred_language,
    "city": lambda lead: lead.city,
    "region": lambda lead: lead.region,
    "country_code": lambda lead: lead.country_code,
}
OPS = ("in", "not_in", "empty", "not_empty")


def _values(lead: Lead, field: str) -> list[str]:
    if field in BUILTIN_CONDITION_FIELDS:
        raw = BUILTIN_CONDITION_FIELDS[field](lead)
    else:
        raw = (lead.custom_fields or {}).get(field)
    items = raw if isinstance(raw, list) else [raw]
    return [str(v).strip().lower() for v in items if v not in (None, "")]


def matches(conditions: list[dict], lead: Lead) -> bool:
    for c in conditions:
        have = _values(lead, c["field"])
        want = {str(v).strip().lower() for v in c.get("values", [])}
        op = c["op"]
        if op == "empty" and have:
            return False
        if op == "not_empty" and not have:
            return False
        if op == "in" and not (set(have) & want):
            return False
        if op == "not_in" and set(have) & want:
            return False
    return True


async def _pool(db: AsyncSession, rule: AssignmentRule) -> list[User]:
    if rule.team_id:
        users = (
            await db.scalars(
                select(User)
                .join(TeamMember, TeamMember.user_id == User.id)
                .where(TeamMember.team_id == rule.team_id, User.status == "active")
                .order_by(User.name, User.id)
            )
        ).all()
        return list(users)
    ids = [uuid.UUID(str(i)) for i in rule.user_ids]
    found = {
        u.id: u
        for u in (
            await db.scalars(select(User).where(User.id.in_(ids), User.status == "active"))
        ).all()
    }
    return [found[i] for i in ids if i in found]


async def pick_owner(
    db: AsyncSession, lead: Lead, exclude: set[uuid.UUID] | None = None
) -> User | None:
    exclude = exclude or set()
    rules = (
        await db.scalars(
            select(AssignmentRule)
            .where(AssignmentRule.is_active.is_(True))
            .order_by(AssignmentRule.position, AssignmentRule.created_at)
        )
    ).all()
    for rule in rules:
        if not matches(rule.conditions, lead):
            continue
        if rule.strategy == "unassigned":
            return None
        pool = [u for u in await _pool(db, rule) if u.id not in exclude]
        if not pool:
            continue  # nobody available here: try the next rule
        if rule.strategy == "user":
            return pool[0]
        # Lock the rule row so two leads arriving together never get the same turn.
        locked = await db.scalar(
            select(AssignmentRule)
            .where(AssignmentRule.id == rule.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        ids = [u.id for u in pool]
        last = locked.last_assigned_user_id
        if last in ids:
            chosen = pool[(ids.index(last) + 1) % len(pool)]
        else:
            # The last person left the pool: continue from where they were in the full list.
            everyone = [uuid.UUID(str(i)) for i in rule.user_ids] or ids
            start = everyone.index(last) + 1 if last in everyone else 0
            after = [i for i in everyone[start:] + everyone[:start] if i in ids]
            chosen = pool[ids.index(after[0])]
        locked.last_assigned_user_id = chosen.id
        return chosen
    return None


async def assign_by_rules(
    db: AsyncSession, lead: Lead, *, exclude: set[uuid.UUID] | None = None
) -> User | None:
    """Give the lead to whoever the rules pick (system action, on the timeline) and tell them."""
    owner = await pick_owner(db, lead, exclude)
    if owner is not None and owner.id != lead.owner_user_id:
        await L.change_owner(db, lead, owner, None)
        await notify(
            db,
            lead.tenant_id,
            [owner.id],
            "lead_assigned",
            f"New lead: {lead.display_name}",
            lead.id,
        )
    return owner


# ---------- SLAs ----------
async def start_slas(
    db: AsyncSession, lead: Lead, trigger: str, stage: LeadStage | None = None
) -> None:
    q = select(SlaRule).where(SlaRule.is_active.is_(True), SlaRule.trigger == trigger)
    if trigger == "stage_entered":
        q = q.where(SlaRule.stage_id == stage.id)
    for rule in (await db.scalars(q)).all():
        due = L.now() + timedelta(minutes=rule.within_minutes)
        sla = LeadSla(
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            rule_id=rule.id,
            started_at=L.now(),
            due_at=due,
        )
        if rule.create_task and lead.owner_user_id:
            task = Task(
                tenant_id=lead.tenant_id,
                lead_id=lead.id,
                title=(rule.task_title or f"{rule.name}: {lead.display_name}")[:200],
                due_at=due,
                owner_user_id=lead.owner_user_id,
                created_from="sla_rule",
                priority="high",
            )
            db.add(task)
            await db.flush()
            sla.task_id = task.id
        db.add(sla)
    await db.flush()


async def mark_contacted(db: AsyncSession, lead: Lead) -> None:
    """A contact activity meets every running SLA on the lead and clears the leakage flag."""
    pending = (
        await db.scalars(
            select(LeadSla).where(
                LeadSla.lead_id == lead.id, LeadSla.met_at.is_(None), LeadSla.breached_at.is_(None)
            )
        )
    ).all()
    for sla in pending:
        sla.met_at = L.now()
    lead.leak_alerted_at = None


async def _act(db: AsyncSession, lead: Lead, action: str, why: str) -> None:
    """Alert the manager, or hand the lead to the next person by the rules (alerting if nobody
    else is available)."""
    if action == "reassign":
        before = lead.owner_user_id
        owner = await assign_by_rules(db, lead, exclude={before} if before else None)
        if owner is not None:
            await notify(
                db,
                lead.tenant_id,
                await managers_of(db, lead),
                "lead_reassigned",
                f"{lead.display_name} was moved to {owner.name}: {why}",
                lead.id,
            )
            return
    if action in ("alert", "reassign"):
        recipients = await managers_of(db, lead)
        if lead.owner_user_id:
            recipients.append(lead.owner_user_id)
        await notify(
            db, lead.tenant_id, recipients, "lead_at_risk", f"{lead.display_name}: {why}", lead.id
        )


async def check_slas(db: AsyncSession) -> int:
    rows = (
        await db.execute(
            select(LeadSla, Lead, SlaRule)
            .join(Lead, Lead.id == LeadSla.lead_id)
            .join(SlaRule, SlaRule.id == LeadSla.rule_id)
            .where(
                LeadSla.met_at.is_(None),
                LeadSla.breached_at.is_(None),
                LeadSla.due_at <= L.now(),
            )
            .order_by(LeadSla.due_at)
            .limit(500)
            .with_for_update(of=LeadSla, skip_locked=True)
        )
    ).all()
    missed = 0
    for sla, lead, rule in rows:
        if not lead.is_open:
            sla.met_at = L.now()  # closed leads need no response
            continue
        if lead.last_contacted_at and lead.last_contacted_at >= sla.started_at:
            sla.met_at = lead.last_contacted_at
            continue
        sla.breached_at = L.now()
        missed += 1
        why = f"not contacted within {_duration(rule.within_minutes)} ({rule.name})"
        await L.log(
            db, lead, "sla_missed", why[0].upper() + why[1:], None, {"rule_id": str(rule.id)}
        )
        await _act(db, lead, rule.on_breach, why)
    return missed


def _duration(minutes: int) -> str:
    if minutes % 1440 == 0:
        n = minutes // 1440
        return f"{n} day{'s' * (n != 1)}"
    if minutes % 60 == 0:
        n = minutes // 60
        return f"{n} hour{'s' * (n != 1)}"
    return f"{minutes} minutes"


async def check_leakage(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    s = await db.get(TenantSettings, tenant_id)
    if not s or not s.leakage_hours:
        return 0
    cutoff = L.now() - timedelta(hours=s.leakage_hours)
    leads = (
        await db.scalars(
            select(Lead)
            .where(
                Lead.is_open.is_(True),
                Lead.leak_alerted_at.is_(None),
                or_(
                    and_(Lead.last_contacted_at.is_(None), Lead.created_at < cutoff),
                    Lead.next_follow_up_at < cutoff,
                ),
            )
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for lead in leads:
        lead.leak_alerted_at = L.now()
        never = lead.last_contacted_at is None and lead.created_at < cutoff
        why = (
            f"not contacted for {s.leakage_hours} hours"
            if never
            else f"follow-up overdue by more than {s.leakage_hours} hours"
        )
        await _act(db, lead, "reassign" if s.leakage_action == "reassign" else "alert", why)
    return len(leads)


async def run_checks() -> dict:
    """Every minute in the worker: SLA deadlines and the leakage guard, company by company."""
    async with platform_session() as s:
        tenant_ids = (await s.scalars(select(Tenant.id).where(Tenant.status == "active"))).all()
    missed = leaking = 0
    for tenant_id in tenant_ids:
        async with tenant_session(tenant_id) as db:
            missed += await check_slas(db)
            leaking += await check_leakage(db, tenant_id)
    return {"sla_missed": missed, "leaking": leaking}

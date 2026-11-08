"""Settings for routing: assignment rules and response-time (SLA) rules. Reading needs
crm.configure too, since rules name people and teams."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm import routing as R
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.leads import lead_fields
from app.modules.crm.models import AssignmentRule, LeadSource, LeadStage, SlaRule
from app.modules.teams.models import Team
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["routing"], dependencies=CRM)
Configurer = Annotated[CurrentUser, require("crm.configure")]


# ---------- assignment rules ----------
class Condition(BaseModel):
    field: str = Field(min_length=1, max_length=60)
    op: Literal["in", "not_in", "empty", "not_empty"]
    values: list[str] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _values_needed(self):
        if self.op in ("in", "not_in") and not self.values:
            raise ValueError("Pick at least one value")
        return self


class AssignmentRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    conditions: list[Condition] = Field(default=[], max_length=20)
    strategy: Literal["round_robin", "user", "unassigned"]
    user_ids: list[uuid.UUID] = Field(default=[], max_length=500)
    team_id: uuid.UUID | None = None
    is_active: bool = True


class AssignmentRulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    conditions: list[Condition] | None = Field(default=None, max_length=20)
    strategy: Literal["round_robin", "user", "unassigned"] | None = None
    user_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    team_id: uuid.UUID | None = None
    is_active: bool | None = None


class AssignmentRuleOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    position: int
    conditions: list[dict]
    strategy: str
    user_ids: list[uuid.UUID]
    team_id: uuid.UUID | None
    is_active: bool
    updated_at: datetime


class OrderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


async def _check_rule(db, rule: AssignmentRule) -> None:
    custom = await lead_fields(db)
    for c in rule.conditions:
        if c["field"] not in R.BUILTIN_CONDITION_FIELDS and c["field"] not in custom:
            raise Invalid(f"Unknown field: {c['field']}")
        if c["field"] == "source":
            try:
                ids = [uuid.UUID(v) for v in c["values"]]
            except ValueError:
                raise Invalid("Choose sources from the list") from None
            found = await db.scalar(
                select(func.count()).select_from(LeadSource).where(LeadSource.id.in_(ids))
            )
            if found != len(set(ids)):
                raise Invalid("Choose sources from the list")
    if rule.strategy == "unassigned":
        rule.user_ids, rule.team_id = [], None
        return
    if rule.strategy == "user" and (len(rule.user_ids) != 1 or rule.team_id):
        raise Invalid("Choose one person")
    if rule.strategy == "round_robin" and bool(rule.user_ids) == bool(rule.team_id):
        raise Invalid("Choose the people to take turns, or one team")
    if rule.team_id and await db.get(Team, rule.team_id) is None:
        raise Invalid("Choose a team from the list")
    if rule.user_ids:
        ids = [uuid.UUID(str(u)) for u in rule.user_ids]
        if len(set(ids)) != len(ids):
            raise Invalid("Each person can be listed once")
        found = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.id.in_(ids), User.status != "disabled")
        )
        if found != len(ids):
            raise Invalid("Choose people from your team who are not disabled")


@router.get("/assignment-rules", response_model=list[AssignmentRuleOut])
async def list_assignment_rules(db: CrmDb, actor: Configurer) -> list[AssignmentRule]:
    rows = await db.scalars(
        select(AssignmentRule).order_by(AssignmentRule.position, AssignmentRule.created_at)
    )
    return list(rows.all())


@router.post(
    "/assignment-rules", response_model=AssignmentRuleOut, status_code=status.HTTP_201_CREATED
)
async def create_assignment_rule(
    body: AssignmentRuleIn, db: CrmDb, actor: Configurer
) -> AssignmentRule:
    position = await db.scalar(select(func.coalesce(func.max(AssignmentRule.position), -1)))
    rule = AssignmentRule(
        tenant_id=actor.user.tenant_id,
        name=body.name.strip(),
        position=position + 1,
        conditions=[c.model_dump() for c in body.conditions],
        strategy=body.strategy,
        user_ids=[str(u) for u in body.user_ids],
        team_id=body.team_id,
        is_active=body.is_active,
    )
    await _check_rule(db, rule)
    db.add(rule)
    await db.flush()
    await audit(
        db, actor, "assignment_rule.created", "assignment_rule", rule.id, None, {"name": rule.name}
    )
    await db.refresh(rule)
    return rule


async def _rule(db, rule_id: uuid.UUID) -> AssignmentRule:
    rule = await db.get(AssignmentRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")
    return rule


@router.patch("/assignment-rules/{rule_id}", response_model=AssignmentRuleOut)
async def update_assignment_rule(
    rule_id: uuid.UUID, body: AssignmentRulePatch, db: CrmDb, actor: Configurer
) -> AssignmentRule:
    rule = await _rule(db, rule_id)
    changes = body.model_dump(exclude_unset=True)
    if "conditions" in changes:
        rule.conditions = [c.model_dump() for c in body.conditions or []]
    if "user_ids" in changes:
        rule.user_ids = [str(u) for u in body.user_ids or []]
    for key in ("name", "strategy", "team_id", "is_active"):
        if key in changes and (changes[key] is not None or key == "team_id"):
            setattr(rule, key, changes[key].strip() if key == "name" else changes[key])
    await _check_rule(db, rule)
    await audit(db, actor, "assignment_rule.updated", "assignment_rule", rule.id, None, changes)
    await db.flush()
    await db.refresh(rule)
    return rule


@router.delete("/assignment-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment_rule(rule_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    rule = await _rule(db, rule_id)
    await db.delete(rule)
    await audit(
        db, actor, "assignment_rule.deleted", "assignment_rule", rule_id, {"name": rule.name}
    )


@router.put("/assignment-rules/order", status_code=status.HTTP_204_NO_CONTENT)
async def order_assignment_rules(body: OrderIn, db: CrmDb, actor: Configurer) -> None:
    rules = {r.id: r for r in (await db.scalars(select(AssignmentRule))).all()}
    if set(body.ids) != set(rules) or len(body.ids) != len(rules):
        raise Invalid("Send every rule once")
    for i, rule_id in enumerate(body.ids):
        rules[rule_id].position = i


# ---------- SLA rules ----------
class SlaRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    trigger: Literal["lead_created", "stage_entered"]
    stage_id: uuid.UUID | None = None
    within_minutes: int = Field(ge=1, le=60 * 24 * 60)
    create_task: bool = True
    task_title: str | None = Field(default=None, max_length=200)
    on_breach: Literal["none", "alert", "reassign"] = "alert"
    is_active: bool = True


class SlaRulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    within_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 60)
    create_task: bool | None = None
    task_title: str | None = Field(default=None, max_length=200)
    on_breach: Literal["none", "alert", "reassign"] | None = None
    is_active: bool | None = None


class SlaRuleOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    trigger: str
    stage_id: uuid.UUID | None
    within_minutes: int
    create_task: bool
    task_title: str | None
    on_breach: str
    is_active: bool


@router.get("/sla-rules", response_model=list[SlaRuleOut])
async def list_sla_rules(db: CrmDb, actor: Configurer) -> list[SlaRule]:
    return list((await db.scalars(select(SlaRule).order_by(SlaRule.created_at))).all())


@router.post("/sla-rules", response_model=SlaRuleOut, status_code=status.HTTP_201_CREATED)
async def create_sla_rule(body: SlaRuleIn, db: CrmDb, actor: Configurer) -> SlaRule:
    if body.trigger == "stage_entered":
        stage = await db.get(LeadStage, body.stage_id) if body.stage_id else None
        if stage is None or not stage.is_open:
            raise Invalid("Choose an open stage")
    elif body.stage_id:
        raise Invalid("Only 'enters a stage' rules have a stage")
    rule = SlaRule(tenant_id=actor.user.tenant_id, **body.model_dump())
    rule.name = rule.name.strip()
    db.add(rule)
    await db.flush()
    await audit(db, actor, "sla_rule.created", "sla_rule", rule.id, None, {"name": rule.name})
    return rule


@router.patch("/sla-rules/{rule_id}", response_model=SlaRuleOut)
async def update_sla_rule(
    rule_id: uuid.UUID, body: SlaRulePatch, db: CrmDb, actor: Configurer
) -> SlaRule:
    rule = await db.get(SlaRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    for key, value in changes.items():
        if value is not None or key == "task_title":
            setattr(rule, key, value)
    await audit(db, actor, "sla_rule.updated", "sla_rule", rule.id, None, changes)
    return rule


@router.delete("/sla-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sla_rule(rule_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    rule = await db.get(SlaRule, rule_id)
    if rule is None:
        raise NotFound("Rule not found")
    await db.delete(rule)
    await audit(db, actor, "sla_rule.deleted", "sla_rule", rule_id, {"name": rule.name})

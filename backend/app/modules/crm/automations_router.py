"""Setting up automations (crm.configure), their run history, and a dry-run test."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import Invalid
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm import automation as A
from app.modules.crm import conditions as C
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import Automation, AutomationRun, Deal, Lead
from app.modules.crm.setup_router import OrderIn, _get, _next_position, _reorder

router = APIRouter(prefix="/api/v1/automations", tags=["automations"], dependencies=CRM)
Configurer = Annotated[CurrentUser, require("crm.configure")]


class AutomationOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    subject: str
    trigger: dict
    conditions: list[dict]
    actions: list[dict]
    is_active: bool
    position: int
    failures_in_row: int
    last_run_at: datetime | None
    runs_7d: int = 0
    failed_7d: int = 0
    created_at: datetime


class AutomationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    trigger: dict
    conditions: list[dict] = Field(default=[], max_length=A.MAX_CONDITIONS)
    actions: list[dict] = Field(max_length=A.MAX_ACTIONS)
    is_active: bool = True


class AutomationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    trigger: dict | None = None
    conditions: list[dict] | None = Field(default=None, max_length=A.MAX_CONDITIONS)
    actions: list[dict] | None = Field(default=None, max_length=A.MAX_ACTIONS)
    is_active: bool | None = None


class RunOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    lead_id: uuid.UUID | None
    deal_id: uuid.UUID | None
    subject_name: str | None = None
    status: str
    detail: list[dict]
    error: str | None
    created_at: datetime


async def _out(db, autos: list[Automation]) -> list[AutomationOut]:
    since = func.now() - func.make_interval(0, 0, 0, 7)
    stats = {
        (aid, st): n
        for aid, st, n in (
            await db.execute(
                select(AutomationRun.automation_id, AutomationRun.status, func.count())
                .where(AutomationRun.created_at >= since, AutomationRun.status != "skipped")
                .group_by(AutomationRun.automation_id, AutomationRun.status)
            )
        ).all()
    }
    out = []
    for a in autos:
        item = AutomationOut.model_validate(a)
        item.runs_7d = stats.get((a.id, "done"), 0) + stats.get((a.id, "failed"), 0)
        item.failed_7d = stats.get((a.id, "failed"), 0)
        out.append(item)
    return out


@router.get("", response_model=list[AutomationOut])
async def list_automations(db: CrmDb, _: Configurer) -> list[AutomationOut]:
    rows = (
        await db.scalars(select(Automation).order_by(Automation.position, Automation.created_at))
    ).all()
    return await _out(db, list(rows))


@router.post("", response_model=AutomationOut, status_code=status.HTTP_201_CREATED)
async def create_automation(body: AutomationIn, db: CrmDb, actor: Configurer) -> AutomationOut:
    subject, trigger, conds, actions = await A.check_definition(
        db, body.trigger, body.conditions, body.actions
    )
    auto = Automation(
        tenant_id=actor.user.tenant_id,
        name=" ".join(body.name.split()),
        subject=subject,
        trigger=trigger,
        conditions=conds,
        actions=actions,
        is_active=body.is_active,
        position=await _next_position(db, Automation),
        created_by_user_id=actor.user.id,
    )
    db.add(auto)
    await db.flush()
    await audit(db, actor, "automation.created", "automation", auto.id, None, {"name": auto.name})
    await db.refresh(auto)
    return (await _out(db, [auto]))[0]


@router.get("/{auto_id}", response_model=AutomationOut)
async def get_automation(auto_id: uuid.UUID, db: CrmDb, _: Configurer) -> AutomationOut:
    return (await _out(db, [await _get(db, Automation, auto_id, "Automation")]))[0]


@router.patch("/{auto_id}", response_model=AutomationOut)
async def update_automation(
    auto_id: uuid.UUID, body: AutomationPatch, db: CrmDb, actor: Configurer
) -> AutomationOut:
    auto = await _get(db, Automation, auto_id, "Automation")
    before = {"name": auto.name, "active": auto.is_active}
    if {"trigger", "conditions", "actions"} & body.model_fields_set:
        subject, trigger, conds, actions = await A.check_definition(
            db,
            body.trigger if body.trigger is not None else auto.trigger,
            body.conditions if body.conditions is not None else auto.conditions,
            body.actions if body.actions is not None else auto.actions,
            old_actions=auto.actions,
        )
        if subject != auto.subject and body.conditions is None and auto.conditions:
            raise Invalid("The conditions are for another kind of record; set them again")
        auto.subject, auto.trigger, auto.conditions, auto.actions = subject, trigger, conds, actions
    if body.name is not None:
        auto.name = " ".join(body.name.split())
    if body.is_active is not None:
        auto.is_active = body.is_active
        if body.is_active:
            auto.failures_in_row = 0
    await audit(
        db, actor, "automation.updated", "automation", auto.id, before,
        {"name": auto.name, "active": auto.is_active},
    )  # fmt: skip
    await db.flush()
    await db.refresh(auto)
    return (await _out(db, [auto]))[0]


@router.delete("/{auto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(auto_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    auto = await _get(db, Automation, auto_id, "Automation")
    await db.delete(auto)
    await audit(db, actor, "automation.deleted", "automation", auto_id, {"name": auto.name})


@router.put("/order", response_model=list[AutomationOut])
async def order_automations(body: OrderIn, db: CrmDb, actor: Configurer):
    await _reorder(db, Automation, body.ids)
    return await list_automations(db, actor)


@router.get("/{auto_id}/runs", response_model=list[RunOut])
async def list_runs(
    auto_id: uuid.UUID,
    db: CrmDb,
    _: Configurer,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunOut]:
    await _get(db, Automation, auto_id, "Automation")
    runs = (
        await db.scalars(
            select(AutomationRun)
            .where(AutomationRun.automation_id == auto_id, AutomationRun.status != "skipped")
            .order_by(AutomationRun.created_at.desc())
            .limit(limit)
        )
    ).all()
    lead_ids = {r.lead_id for r in runs if r.lead_id}
    deal_ids = {r.deal_id for r in runs if r.deal_id}
    leads = (
        dict(
            (
                await db.execute(select(Lead.id, Lead.display_name).where(Lead.id.in_(lead_ids)))
            ).all()
        )
        if lead_ids
        else {}
    )
    deals = (
        dict((await db.execute(select(Deal.id, Deal.name).where(Deal.id.in_(deal_ids)))).all())
        if deal_ids
        else {}
    )
    out = []
    for r in runs:
        item = RunOut.model_validate(r)
        item.subject_name = deals.get(r.deal_id) or leads.get(r.lead_id)
        out.append(item)
    return out


class TestOut(BaseModel):
    matches: bool
    conditions: list[dict]  # each condition with "ok"


@router.post("/{auto_id}/test", response_model=TestOut)
async def test_automation(
    auto_id: uuid.UUID,
    db: CrmDb,
    _: Configurer,
    lead_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
) -> TestOut:
    """Would the conditions match this lead or deal? Changes nothing."""
    auto = await _get(db, Automation, auto_id, "Automation")
    if auto.subject == "lead":
        subject = await db.get(Lead, lead_id) if lead_id else None
        facts = await C.lead_facts(db, subject) if subject else None
    else:
        subject = await db.get(Deal, deal_id) if deal_id else None
        facts = await C.deal_facts(db, subject) if subject else None
    if facts is None:
        raise Invalid(f"Choose a {auto.subject} to test with")
    checks = [c | {"ok": C.match(c, facts)} for c in auto.conditions]
    return TestOut(matches=all(c["ok"] for c in checks), conditions=checks)

"""Timeline, tasks and My Day."""

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.errors import Forbidden, Invalid
from app.core.events import emit
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import deals as D
from app.modules.crm import leads as L
from app.modules.crm import records as RC
from app.modules.crm import work as W
from app.modules.crm.deps import CRM, CrmDb
from app.modules.crm.leads_router import LeadOut, _out
from app.modules.crm.models import Activity, Deal, Lead, Record, Task
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["work"], dependencies=CRM)
Editor = Annotated[CurrentUser, require("leads.edit")]


class ActivityOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    lead_id: uuid.UUID
    deal_id: uuid.UUID | None = None
    type_key: str
    actor_type: str
    actor_id: uuid.UUID | None
    actor_name: str | None = None
    occurred_at: datetime
    summary: str
    body: str | None
    data: dict
    disposition: str | None


class ActivityIn(BaseModel):
    type_key: str = Field(min_length=1, max_length=60)
    body: str | None = Field(default=None, max_length=10000)
    data: dict = {}
    occurred_at: datetime | None = None
    next_follow_up_at: datetime | None = None


class LoggedOut(BaseModel):
    activity: ActivityOut
    lead: LeadOut


class TaskOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    lead_id: uuid.UUID | None
    lead_name: str | None = None
    lead_phone: str | None = None
    record_id: uuid.UUID | None = None
    record_name: str | None = None
    deal_id: uuid.UUID | None = None
    deal_name: str | None = None
    title: str
    notes: str | None
    due_at: datetime
    owner_user_id: uuid.UUID
    status: str
    priority: str
    is_follow_up: bool
    completed_at: datetime | None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime
    lead_id: uuid.UUID | None = None
    record_id: uuid.UUID | None = None  # a task on a record instead of a lead
    deal_id: uuid.UUID | None = None  # a task on a deal (it belongs to the deal's lead too)
    owner_user_id: uuid.UUID | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    notes: str | None = Field(default=None, max_length=5000)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_at: datetime | None = None
    owner_user_id: uuid.UUID | None = None
    priority: Literal["low", "normal", "high"] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    status: Literal["open", "done", "cancelled"] | None = None


class MyDayOut(BaseModel):
    overdue: list[TaskOut]
    today: list[TaskOut]
    upcoming: list[TaskOut]
    new_leads: list[LeadOut]
    to_call: list[LeadOut] = []  # the dialer, after due follow-ups: never contacted, none booked
    unassigned_count: int | None


async def _activities_out(db, rows: list[Activity]) -> list[ActivityOut]:
    ids = {a.actor_id for a in rows if a.actor_id}
    names = (
        dict((await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all())
        if ids
        else {}
    )
    out = []
    for a in rows:
        item = ActivityOut.model_validate(a)
        item.actor_name = names.get(a.actor_id)
        out.append(item)
    return out


async def _tasks_out(db, tasks: list[Task]) -> list[TaskOut]:
    lead_ids = {t.lead_id for t in tasks if t.lead_id}
    leads = {}
    if lead_ids:
        rows = await db.execute(
            select(Lead.id, Lead.display_name, Lead.primary_phone).where(Lead.id.in_(lead_ids))
        )
        leads = {r.id: r for r in rows.all()}
    record_ids = {t.record_id for t in tasks if t.record_id}
    records = {}
    if record_ids:
        records = dict(
            (
                await db.execute(select(Record.id, Record.name).where(Record.id.in_(record_ids)))
            ).all()
        )
    deal_ids = {t.deal_id for t in tasks if t.deal_id}
    deals = {}
    if deal_ids:
        deals = dict(
            (await db.execute(select(Deal.id, Deal.name).where(Deal.id.in_(deal_ids)))).all()
        )
    out = []
    for t in tasks:
        item = TaskOut.model_validate(t)
        item.record_name = records.get(t.record_id)
        item.deal_name = deals.get(t.deal_id)
        if t.lead_id in leads:
            item.lead_name, item.lead_phone = (
                leads[t.lead_id].display_name,
                leads[t.lead_id].primary_phone,
            )
        out.append(item)
    return out


# ---------- timeline ----------
@router.get("/leads/{lead_id}/activities", response_model=list[ActivityOut])
async def list_activities(
    lead_id: uuid.UUID,
    db: CrmDb,
    actor: ActiveUser,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityOut]:
    await L.get_visible(db, actor, lead_id)
    # Deal entries show here too, but only for deals this person may see.
    visible_deals = select(Deal.id).where(await D.visibility_filter(db, actor))
    q = select(Activity).where(
        Activity.lead_id == lead_id,
        or_(Activity.deal_id.is_(None), Activity.deal_id.in_(visible_deals)),
    )
    if before:
        q = q.where(Activity.occurred_at < before)
    rows = await db.scalars(
        q.order_by(Activity.occurred_at.desc(), Activity.created_at.desc()).limit(limit)
    )
    return await _activities_out(db, list(rows.all()))


@router.post(
    "/leads/{lead_id}/activities", response_model=LoggedOut, status_code=status.HTTP_201_CREATED
)
async def log_activity(lead_id: uuid.UUID, body: ActivityIn, db: CrmDb, actor: Editor) -> LoggedOut:
    lead = await L.get_visible(db, actor, lead_id)
    activity = await W.log_activity(
        db,
        actor,
        lead,
        type_key=body.type_key,
        body=body.body,
        data=body.data,
        occurred_at=body.occurred_at,
        next_follow_up_at=body.next_follow_up_at,
    )
    await db.flush()
    return LoggedOut(
        activity=(await _activities_out(db, [activity]))[0], lead=(await _out(db, [lead], actor))[0]
    )


# ---------- tasks ----------
@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    db: CrmDb,
    actor: ActiveUser,
    scope: Literal["mine", "team"] = "mine",
    status_: Annotated[Literal["open", "done", "cancelled"] | None, Query(alias="status")] = "open",
    lead_id: uuid.UUID | None = None,
    record_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
) -> list[TaskOut]:
    if record_id or deal_id:  # everything on a record or deal you may see
        if record_id:
            await RC.get_visible(db, actor, record_id)
            q = select(Task).where(Task.record_id == record_id)
        else:
            await D.get_visible(db, actor, deal_id)
            q = select(Task).where(Task.deal_id == deal_id)
        if status_:
            q = q.where(Task.status == status_)
        return await _tasks_out(db, list((await db.scalars(q.order_by(Task.due_at))).all()))
    tasks = await W.tasks_for(
        db,
        actor,
        mine_only=scope == "mine" and lead_id is None,
        status=status_,
        lead_id=lead_id,
        due_before=None,
        due_from=None,
    )
    return await _tasks_out(db, tasks)


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskIn, db: CrmDb, actor: Editor) -> TaskOut:
    if sum(x is not None for x in (body.lead_id, body.record_id, body.deal_id)) > 1:
        raise Invalid("A task belongs to one lead, deal or record")
    lead_id = body.lead_id
    if body.deal_id:
        deal = await D.get_visible(db, actor, body.deal_id)
        D.require(actor, "deals.edit")
        lead_id = deal.lead_id
    if body.lead_id:
        await L.get_visible(db, actor, body.lead_id)
    if body.record_id:
        v = await RC.get_visible(db, actor, body.record_id)
        if not v.access.edit:
            raise Forbidden("permission_denied")
    task = Task(
        tenant_id=actor.user.tenant_id,
        lead_id=lead_id,
        record_id=body.record_id,
        deal_id=body.deal_id,
        title=body.title.strip(),
        notes=body.notes,
        due_at=body.due_at,
        owner_user_id=await W.task_owner(db, actor, body.owner_user_id),
        priority=body.priority,
        created_by_user_id=actor.user.id,
    )
    db.add(task)
    await db.flush()
    await emit(
        db,
        task.tenant_id,
        "task.created",
        {"task_id": str(task.id), "lead_id": str(task.lead_id) if task.lead_id else None},
    )
    return (await _tasks_out(db, [task]))[0]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: uuid.UUID, body: TaskPatch, db: CrmDb, actor: Editor) -> TaskOut:
    task = await W.visible_task(db, actor, task_id)
    changes = body.model_dump(exclude_unset=True)
    if "owner_user_id" in changes:
        if changes["owner_user_id"] is None:
            raise Invalid("A task needs an owner")
        task.owner_user_id = await W.task_owner(db, actor, changes["owner_user_id"])
    for key in ("title", "priority", "notes"):
        if key in changes:
            setattr(task, key, changes[key])
    if "due_at" in changes and changes["due_at"]:
        task.due_at, task.due_notified_at = changes["due_at"], None
        if task.is_follow_up and task.status == "open" and task.lead_id:
            lead = await db.get(Lead, task.lead_id)
            lead.next_follow_up_at = task.due_at
    if "status" in changes and changes["status"] != task.status:
        await W.finish_task(db, actor, task, changes["status"])
    await db.flush()
    return (await _tasks_out(db, [task]))[0]


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, db: CrmDb, actor: Editor) -> None:
    task = await W.visible_task(db, actor, task_id)
    if task.is_follow_up and task.status == "open" and task.lead_id:
        lead = await db.get(Lead, task.lead_id)
        lead.next_follow_up_at = None
    await db.delete(task)


# ---------- My Day ----------
@router.get("/me/day", response_model=MyDayOut)
async def my_day(db: CrmDb, actor: ActiveUser) -> MyDayOut:
    """Overdue first, then today: the order the calling queue works through (#21)."""
    now, tomorrow = await L.day_bounds(db, actor.user.tenant_id)
    mine = await W.tasks_for(
        db,
        actor,
        mine_only=True,
        status="open",
        lead_id=None,
        due_before=tomorrow + timedelta(days=7),
        due_from=None,
    )
    since = now - timedelta(days=2)
    new_leads = await db.scalars(
        select(Lead)
        .where(
            Lead.owner_user_id == actor.user.id,
            Lead.is_open.is_(True),
            Lead.last_activity_at.is_(None),
            Lead.assigned_at >= since,
        )
        .order_by(Lead.assigned_at.desc())
        .limit(50)
    )
    to_call = await db.scalars(
        select(Lead)
        .where(
            Lead.owner_user_id == actor.user.id,
            Lead.is_open.is_(True),
            Lead.last_contacted_at.is_(None),
            Lead.next_follow_up_at.is_(None),
            Lead.primary_phone.is_not(None),
        )
        .order_by(Lead.assigned_at.desc().nulls_last())
        .limit(200)
    )
    unassigned = None
    if actor.role.scope in ("team", "all"):
        unassigned = await db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.owner_user_id.is_(None), Lead.is_open.is_(True))
        )
    out = await _tasks_out(db, mine)
    return MyDayOut(
        overdue=[t for t in out if t.due_at < now],
        today=[t for t in out if now <= t.due_at < tomorrow],
        upcoming=[t for t in out if t.due_at >= tomorrow],
        new_leads=await _out(db, list(new_leads.all()), actor),
        to_call=await _out(db, list(to_call.all()), actor),
        unassigned_count=unassigned,
    )

"""Logging activities (with the follow-up rule and one-step logging), tasks, My Day and the
task-due notifier."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Invalid, NotFound
from app.core.events import emit
from app.core.tenancy import platform_session, tenant_session
from app.modules.auth.deps import CurrentUser
from app.modules.crm import fields as F
from app.modules.crm import leads as L
from app.modules.crm.models import Activity, ActivityType, Lead, Record, Task
from app.modules.crm.notify import notify
from app.modules.crm.routing import mark_contacted
from app.modules.teams.service import visible_user_ids
from app.platform.models import Tenant

# Types that count as reaching the lead (a note does not).
NOT_CONTACT = {"note"}


async def log_activity(
    db: AsyncSession,
    actor: CurrentUser,
    lead: Lead,
    *,
    type_key: str,
    body: str | None,
    data: dict,
    occurred_at: datetime | None,
    next_follow_up_at: datetime | None,
) -> Activity:
    kind = await db.scalar(select(ActivityType).where(ActivityType.key == type_key))
    if kind is None or not kind.is_active or not kind.is_loggable:
        raise Invalid("Choose an activity type you can log")
    clean: dict = {}
    for f in kind.fields:
        value = F.coerce(f, data.get(f["key"]))
        if f.get("required") and value is None:
            raise Invalid(f"{f['label']} is required")
        if value is not None:
            clean[f["key"]] = value
    unknown = set(data) - {f["key"] for f in kind.fields}
    if unknown:
        raise Invalid(f"Unknown field: {sorted(unknown)[0]}")
    when = occurred_at or L.now()
    if when > L.now():
        raise Invalid("An activity cannot happen in the future")
    if type_key == "note" and not (body or "").strip():
        raise Invalid("Write the note")

    # The anti-leakage rule: a worked open lead must have a next follow-up (R4, #21).
    if (
        lead.is_open
        and next_follow_up_at is None
        and await L.follow_up_required(db, lead.tenant_id)
    ):
        raise Invalid("Set the next follow-up date for this lead")
    if next_follow_up_at is not None:
        if not lead.is_open:
            raise Invalid("Closed leads have no follow-up")
        if next_follow_up_at <= L.now():
            raise Invalid("The next follow-up must be in the future")

    disposition_label = None
    if "disposition" in clean:
        field = next(f for f in kind.fields if f["key"] == "disposition")
        disposition_label = next(
            (o["label"] for o in field["options"] if o["value"] == clean["disposition"]), None
        )
    if type_key == "note":
        summary = (body or "").strip().splitlines()[0][:120]
    elif disposition_label:
        summary = f"{kind.label}: {disposition_label}"
    else:
        summary = kind.label
    activity = await L.log(
        db,
        lead,
        type_key,
        summary,
        actor,
        clean,
        disposition=disposition_label,
        body=(body or "").strip() or None,
        occurred_at=when,
    )

    # One-step logging (#21): the due follow-up is done, not left as a separate task.
    await db.execute(
        update(Task)
        .where(Task.lead_id == lead.id, Task.is_follow_up.is_(True), Task.status == "open")
        .values(status="done", completed_at=L.now())
    )
    if next_follow_up_at is not None or lead.next_follow_up_at is not None:
        await L.set_follow_up(db, lead, next_follow_up_at, actor)

    lead.last_activity_at = max(filter(None, [lead.last_activity_at, when]))
    if type_key not in NOT_CONTACT:
        lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, when]))
        lead.first_response_at = lead.first_response_at or when
        await mark_contacted(db, lead)
    if disposition_label:
        lead.last_disposition = disposition_label
    lead.version += 1
    await emit(
        db,
        lead.tenant_id,
        "activity.logged",
        {
            "lead_id": str(lead.id),
            "activity_id": str(activity.id),
            "type": type_key,
            "disposition": clean.get("disposition"),
        },
    )
    from app.modules.crm import scoring  # scoring builds on leads, as this module does

    await scoring.refresh(db, lead)
    return activity


# ---------- tasks ----------
async def visible_task(db: AsyncSession, actor: CurrentUser, task_id: uuid.UUID) -> Task:
    task = await db.get(Task, task_id)
    visible = await visible_user_ids(db, actor.user.id, actor.role.scope)
    if task is None or (visible is not None and task.owner_user_id not in visible):
        raise NotFound("Task not found")
    return task


async def task_owner(db: AsyncSession, actor: CurrentUser, owner_id: uuid.UUID | None) -> uuid.UUID:
    if owner_id is None or owner_id == actor.user.id:
        return actor.user.id
    if not L.can(actor, "leads.assign"):
        raise Forbidden("You can only give tasks to yourself")
    user = await L.check_assignable(db, actor, owner_id)
    return user.id


async def finish_task(db: AsyncSession, actor: CurrentUser, task: Task, status: str) -> None:
    task.status, task.completed_at = status, L.now() if status != "open" else None
    if task.record_id and status == "done":
        from app.modules.crm import records as RC  # records builds on this module

        record = await db.get(Record, task.record_id)
        await RC.log(
            db,
            record,
            "task_completed",
            f"Done: {task.title}"[:500],
            actor,
            {"task_id": str(task.id)},
        )
    if task.lead_id is None:
        return
    lead = await db.get(Lead, task.lead_id)
    if task.is_follow_up and status != "open":
        lead.next_follow_up_at = None
    if status == "done":
        activity = await L.log(
            db,
            lead,
            "task_completed",
            f"Done: {task.title}"[:500],
            actor,
            {"task_id": str(task.id)},
        )
        activity.deal_id = task.deal_id  # a deal's task also shows on the deal


async def tasks_for(
    db: AsyncSession,
    actor: CurrentUser,
    *,
    mine_only: bool,
    status: str | None,
    lead_id: uuid.UUID | None,
    due_before: datetime | None,
    due_from: datetime | None,
) -> list[Task]:
    q = select(Task)
    if mine_only:
        q = q.where(Task.owner_user_id == actor.user.id)
    else:
        visible = await visible_user_ids(db, actor.user.id, actor.role.scope)
        if visible is not None:
            q = q.where(Task.owner_user_id.in_(visible))
    if status:
        q = q.where(Task.status == status)
    if lead_id:
        await L.get_visible(db, actor, lead_id)
        q = q.where(Task.lead_id == lead_id)
    if due_before:
        q = q.where(Task.due_at < due_before)
    if due_from:
        q = q.where(Task.due_at >= due_from)
    return list((await db.scalars(q.order_by(Task.due_at).limit(500))).all())


# ---------- task.due ----------
async def notify_due_tasks() -> int:
    """Emit task.due once per task when it falls due. Runs every minute in the worker."""
    async with platform_session() as s:
        tenant_ids = (await s.scalars(select(Tenant.id).where(Tenant.status == "active"))).all()
    sent = 0
    for tenant_id in tenant_ids:
        async with tenant_session(tenant_id) as db:
            due = (
                await db.scalars(
                    select(Task)
                    .where(
                        Task.status == "open",
                        Task.due_at <= L.now(),
                        Task.due_notified_at.is_(None),
                    )
                    .limit(1000)
                )
            ).all()
            for task in due:
                task.due_notified_at = L.now()
                await notify(
                    db,
                    tenant_id,
                    [task.owner_user_id],
                    "task_due",
                    f"Due: {task.title}",
                    task.lead_id,
                )
                await emit(
                    db,
                    tenant_id,
                    "task.due",
                    {
                        "task_id": str(task.id),
                        "lead_id": str(task.lead_id) if task.lead_id else None,
                        "owner_user_id": str(task.owner_user_id),
                    },
                )
                sent += 1
    return sent

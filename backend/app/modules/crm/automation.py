"""Automation: WHEN a trigger IF conditions THEN actions (Decision log #16, #27).

The worker reads new events every few seconds, finds active automations whose trigger
matches, checks their conditions against the lead or deal, and runs the actions in order.
Actions use the same service functions people use, so every rule still applies (required
fields, stage rules, lost needs a reason) and everything lands on the timeline as
"Automation: <name>". A failed action rolls back that run and is recorded.

Loop guard: events written by an automation carry "_via" (chain of automation ids, depth).
Chains stop at depth 3, and an automation never runs again inside its own chain.
An automation that fails 20 times in a row switches itself off and tells the admins.
"""

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Invalid
from app.core.events import automation_context, emit
from app.core.events_model import Event
from app.core.tenancy import platform_session, tenant_session
from app.modules.crm import conditions as C
from app.modules.crm import deals as D
from app.modules.crm import leads as L
from app.modules.crm import tags as T
from app.modules.crm.models import (
    Automation,
    AutomationRun,
    Deal,
    Lead,
    LeadStage,
    LostReason,
    PipelineStage,
    Tag,
    Task,
)
from app.modules.crm.notify import managers_of, notify
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.platform.models import Tenant

MAX_DEPTH = 3
MAX_FAILURES = 20
MAX_ACTIONS = 10
MAX_CONDITIONS = 20

# trigger type -> (subject, event type it listens to; None = checked on a schedule)
TRIGGERS: dict[str, tuple[str, str | None]] = {
    "lead.created": ("lead", "lead.created"),
    "lead.stage_changed": ("lead", "lead.stage_changed"),
    "lead.field_changed": ("lead", "lead.updated"),
    "lead.assigned": ("lead", "lead.assigned"),
    "activity.logged": ("lead", "activity.logged"),
    "task.overdue": ("lead", "task.due"),
    "lead.no_response": ("lead", None),
    "deal.created": ("deal", "deal.created"),
    "deal.stage_changed": ("deal", "deal.stage_changed"),
    "deal.won": ("deal", "deal.won"),
    "deal.lost": ("deal", "deal.lost"),
    "customer.created": ("lead", "customer.created"),  # step 5 (Decision log #32)
    "document.received": ("lead", "document.received"),
}
EVENT_TYPES = {ev for _, ev in TRIGGERS.values() if ev}
ACTIONS = {
    "create_task",
    "update_field",
    "add_tag",
    "remove_tag",
    "change_owner",
    "change_stage",
    "notify",
    "webhook",
    "enrol",  # put the lead into a sequence (step 9a, #16, #39)
}
LEAD_EDITABLE_BUILTINS = {"city", "region", "preferred_language", "campaign"}


# ---------- checking a definition ----------
async def _active_user(db: AsyncSession, user_id) -> User:
    try:
        user = await db.get(User, uuid.UUID(str(user_id)))
    except ValueError:
        user = None
    if user is None or user.status != "active":
        raise Invalid("Choose an active user")
    return user


async def _lead_stage(db, stage_id) -> LeadStage:
    try:
        stage = await db.get(LeadStage, uuid.UUID(str(stage_id)))
    except ValueError:
        stage = None
    if stage is None:
        raise Invalid("Choose a stage")
    return stage


async def _deal_stage(db, stage_id) -> PipelineStage:
    try:
        stage = await db.get(PipelineStage, uuid.UUID(str(stage_id)))
    except ValueError:
        stage = None
    if stage is None:
        raise Invalid("Choose a deal stage")
    return stage


async def _tag(db, tag_id) -> Tag:
    try:
        tag = await db.get(Tag, uuid.UUID(str(tag_id)))
    except ValueError:
        tag = None
    if tag is None:
        raise Invalid("Choose a tag")
    return tag


DEV_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")


def check_url(url: str) -> str:
    """Webhook targets: https on a public host (never this server's own network). On a
    developer's machine (ENVIRONMENT=dev) only, this machine is allowed too, so an add-on
    like ACE can receive webhooks locally without a tunnel. Never in test or prod."""
    parsed = urlparse(url or "")
    if (
        get_settings().environment == "dev"
        and parsed.scheme in ("http", "https")
        and parsed.hostname in DEV_HOSTS
        and len(url) <= 500
    ):
        return url
    if parsed.scheme != "https" or not parsed.hostname or len(url) > 500:
        raise Invalid("Webhook address must start with https://")
    host = parsed.hostname
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443)}
    except (socket.gaierror, UnicodeError):
        addresses = set()
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not ip.is_global:
            raise Invalid("Webhook address must be on the public internet")
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        raise Invalid("Webhook address must be on the public internet")
    return url


async def check_definition(
    db: AsyncSession, trigger: dict, conds: list, actions: list, *, old_actions: list | None = None
) -> tuple[str, dict, list, list]:
    """Clean and validate. Returns (subject, trigger, conditions, actions)."""
    ttype = trigger.get("type")
    if ttype not in TRIGGERS:
        raise Invalid("Choose what starts this automation")
    subject = TRIGGERS[ttype][0]
    clean_t: dict = {"type": ttype}
    if ttype in ("lead.stage_changed",) and trigger.get("to_stage_id"):
        clean_t["to_stage_id"] = str((await _lead_stage(db, trigger["to_stage_id"])).id)
    if ttype == "deal.stage_changed" and trigger.get("to_stage_id"):
        clean_t["to_stage_id"] = str((await _deal_stage(db, trigger["to_stage_id"])).id)
    if ttype == "lead.field_changed":
        field = trigger.get("field")
        known = C.LEAD_FIELDS | set(await L.lead_fields(db, "lead"))
        if field not in known:
            raise Invalid("Choose which field")
        clean_t["field"] = field
    if ttype == "activity.logged":
        if trigger.get("type_key"):
            clean_t["type_key"] = str(trigger["type_key"])[:60]
        if trigger.get("disposition"):
            clean_t["disposition"] = str(trigger["disposition"])[:100]
    if ttype == "lead.no_response":
        hours = trigger.get("hours")
        if not isinstance(hours, int) or not 1 <= hours <= 24 * 30:
            raise Invalid("No response within how many hours? (1 to 720)")
        clean_t["hours"] = hours
    if len(conds) > MAX_CONDITIONS:
        raise Invalid(f"At most {MAX_CONDITIONS} conditions")
    clean_c = [await C.check(db, subject, c) for c in conds]
    if not 1 <= len(actions) <= MAX_ACTIONS:
        raise Invalid(f"Add between 1 and {MAX_ACTIONS} actions")
    old_secrets = {a.get("url"): a.get("secret") for a in (old_actions or []) if a.get("secret")}
    clean_a = [await _check_action(db, subject, a, old_secrets) for a in actions]
    return subject, clean_t, clean_c, clean_a


async def _check_action(db, subject: str, a: dict, old_secrets: dict) -> dict:
    kind = a.get("type")
    if kind not in ACTIONS:
        raise Invalid("Unknown action")
    if kind == "create_task":
        title = " ".join(str(a.get("title", "")).split())[:200]
        hours = a.get("due_hours", 0)
        if not title:
            raise Invalid("Give the task a title")
        if not isinstance(hours, int) or not 0 <= hours <= 24 * 365:
            raise Invalid("Due in how many hours? (0 to 8760)")
        to = a.get("assign_to") or "owner"
        if to != "owner":
            to = str((await _active_user(db, to)).id)
        return {"type": kind, "title": title, "due_hours": hours, "assign_to": to}
    if kind == "update_field":
        field = a.get("field")
        entity = "lead" if subject == "lead" else D.ENTITY
        defs = await L.lead_fields(db, entity)
        if field in defs:
            if defs[field].type == "calculated":
                raise Invalid(f"{defs[field].label} is calculated")
            from app.modules.crm import fields as F

            value = F.coerce(
                {
                    "type": defs[field].type,
                    "label": defs[field].label,
                    "options": defs[field].options,
                },
                a.get("value"),
            )
        elif subject == "lead" and field in LEAD_EDITABLE_BUILTINS:
            value = (str(a.get("value") or "").strip() or None) and str(a["value"]).strip()[:120]
        else:
            raise Invalid("Choose a field this automation can change")
        return {"type": kind, "field": field, "value": value}
    if kind in ("add_tag", "remove_tag"):
        return {"type": kind, "tag_id": str((await _tag(db, a.get("tag_id"))).id)}
    if kind == "change_owner":
        to = a.get("user_id")
        if to == "rules":
            if subject != "lead":
                raise Invalid("Assignment rules are for leads")
            return {"type": kind, "user_id": "rules"}
        return {"type": kind, "user_id": str((await _active_user(db, to)).id)}
    if kind == "change_stage":
        if subject == "lead":
            stage = await _lead_stage(db, a.get("stage_id"))
            out = {"type": kind, "stage_id": str(stage.id)}
            if stage.is_unqualified:
                reason = " ".join(str(a.get("reason", "")).split())[:300]
                if not reason:
                    raise Invalid(f"Give a reason for moving to {stage.name}")
                out["reason"] = reason
            return out
        stage = await _deal_stage(db, a.get("stage_id"))
        out = {"type": kind, "stage_id": str(stage.id)}
        if stage.kind == "lost":
            try:
                reason = await db.get(LostReason, uuid.UUID(str(a.get("lost_reason_id"))))
            except ValueError:
                reason = None
            if reason is None:
                raise Invalid("Choose why the deal is lost")
            out["lost_reason_id"] = str(reason.id)
        return out
    if kind == "notify":
        to = a.get("to") or "owner"
        if to not in ("owner", "managers"):
            to = str((await _active_user(db, to)).id)
        message = " ".join(str(a.get("message", "")).split())[:300]
        if not message:
            raise Invalid("Write the notification")
        return {"type": kind, "to": to, "message": message}
    if kind == "enrol":
        from app.modules.engage.models import Sequence

        try:
            seq = await db.get(Sequence, uuid.UUID(str(a.get("sequence_id"))))
        except ValueError:
            seq = None
        if seq is None:
            raise Invalid("Choose a sequence")
        return {"type": kind, "sequence_id": str(seq.id)}
    url = check_url(str(a.get("url", "")).strip())
    secret = old_secrets.get(url) or "whsec_" + secrets.token_urlsafe(24)
    return {"type": "webhook", "url": url, "secret": secret}


# ---------- running ----------
class Skip(Exception):
    """Nothing to do (no owner to give a task to, etc.); not a failure."""


async def _load(db, subject: str, sid) -> Lead | Deal | None:
    if not sid:
        return None
    model = Lead if subject == "lead" else Deal
    try:
        return await db.get(model, uuid.UUID(str(sid)))
    except ValueError:
        return None


def _trigger_matches(auto: Automation, event: Event | None) -> bool:
    t, p = auto.trigger, (event.payload if event else {})
    if t["type"] in ("lead.stage_changed", "deal.stage_changed") and t.get("to_stage_id"):
        return p.get("to") == t["to_stage_id"]
    if t["type"] == "lead.field_changed":
        return t["field"] in (p.get("fields") or [])
    if t["type"] == "activity.logged":
        if t.get("type_key") and p.get("type") != t["type_key"]:
            return False
        return not t.get("disposition") or p.get("disposition") == t["disposition"]
    return True


async def _act(db, auto: Automation, subject: Lead | Deal, a: dict, webhooks: list) -> str:
    is_lead = isinstance(subject, Lead)
    kind = a["type"]
    if kind == "create_task":
        owner = subject.owner_user_id if a["assign_to"] == "owner" else uuid.UUID(a["assign_to"])
        if owner is None:
            raise Skip("no owner to give the task to")
        task = Task(
            tenant_id=subject.tenant_id,
            lead_id=subject.id if is_lead else subject.lead_id,
            deal_id=None if is_lead else subject.id,
            title=a["title"],
            due_at=L.now() + timedelta(hours=a["due_hours"]),
            owner_user_id=owner,
            created_from="automation",
        )
        db.add(task)
        await db.flush()
        await emit(
            db,
            subject.tenant_id,
            "task.created",
            {"task_id": str(task.id), "lead_id": str(task.lead_id)},
        )
        return f"Task: {a['title']}"
    if kind == "update_field":
        if is_lead and a["field"] in LEAD_EDITABLE_BUILTINS:
            if getattr(subject, a["field"]) == a["value"]:
                return "No change"
            setattr(subject, a["field"], a["value"])
            changed = [a["field"]]
        else:
            entity = "lead" if is_lead else D.ENTITY
            changed = await L.apply_custom_fields(
                db, subject, {a["field"]: a["value"]}, creating=False, entity=entity
            )
            if not changed:
                return "No change"
        subject.version += 1
        if is_lead:
            await L.log(
                db,
                subject,
                "lead_updated",
                f"Changed {', '.join(changed)}",
                None,
                {"fields": changed},
            )
            await L.event(db, subject, "lead.updated", {"fields": changed})
        else:
            summary = f"{subject.name}: changed {', '.join(changed)}"
            await D.log(db, subject, "deal_updated", summary, None, {"fields": changed})
            await D.event(db, subject, "deal.updated", {"fields": changed})
        return f"Set {a['field']}"
    if kind in ("add_tag", "remove_tag"):
        tag = await db.get(Tag, uuid.UUID(a["tag_id"]))
        if tag is None:
            raise Invalid("The tag was deleted")
        if kind == "add_tag":
            await T.change(db, None, subject, add=[tag])
        else:
            await T.change(db, None, subject, remove=[tag.id])
        return f"{'Tagged' if kind == 'add_tag' else 'Untagged'} {tag.name}"
    if kind == "change_owner":
        if a["user_id"] == "rules":
            from app.modules.crm.routing import assign_by_rules

            user = await assign_by_rules(db, subject)
            return f"Assigned to {user.name}" if user else "No rule matched"
        user = await _active_user(db, a["user_id"])
        if is_lead:
            await L.change_owner(db, subject, user, None)
            subject.version += 1
        elif subject.owner_user_id != user.id:
            subject.owner_user_id = user.id
            subject.team_id = await L.owner_team(db, user.id)
            subject.version += 1
            await D.log(
                db, subject, "deal_updated", f"{subject.name}: assigned to {user.name}", None
            )
            await D.event(db, subject, "deal.updated", {"fields": ["owner"]})
        return f"Assigned to {user.name}"
    if kind == "change_stage":
        if is_lead:
            stage = await _lead_stage(db, a["stage_id"])
            if stage.is_unqualified:
                subject.unqualified_reason = a.get("reason")
            await L.move_stage(db, subject, stage, None)
        else:
            stage = await _deal_stage(db, a["stage_id"])
            reason = uuid.UUID(a["lost_reason_id"]) if a.get("lost_reason_id") else None
            await D.move(db, None, subject, stage, lost_reason_id=reason)
        subject.version += 1
        return f"Moved to {stage.name}"
    if kind == "notify":
        lead = subject if is_lead else await db.get(Lead, subject.lead_id)
        if a["to"] == "owner":
            if subject.owner_user_id is None:
                raise Skip("no owner to notify")
            users = [subject.owner_user_id]
        elif a["to"] == "managers":
            users = await managers_of(db, lead)
        else:
            users = [uuid.UUID(a["to"])]
        await notify(db, subject.tenant_id, users, "automation", a["message"], lead.id)
        return f"Notified {len(users)}"
    if kind == "enrol":
        from app.modules.engage import engine as E
        from app.modules.engage.models import Sequence

        seq = await db.get(Sequence, uuid.UUID(a["sequence_id"]))
        if seq is None:
            raise Skip("the sequence was deleted")
        lead = subject if is_lead else await db.get(Lead, subject.lead_id)
        out = await E.enrol(db, None, seq, lead)
        if isinstance(out, str):
            raise Skip(out)
        return f"Added to {seq.name}"
    body = {
        "automation_id": str(auto.id),
        "automation": auto.name,
        "trigger": auto.trigger["type"],
        "lead_id": str(subject.id if is_lead else subject.lead_id),
        "deal_id": None if is_lead else str(subject.id),
        "sent_at": int(time.time()),
    }
    webhooks.append(
        {
            "url": a["url"],
            "secret": a["secret"],
            "automation_id": str(auto.id),
            "body": json.dumps(body),
        }
    )
    return f"Webhook queued: {urlparse(a['url']).hostname}"


async def run_one(
    db: AsyncSession, auto: Automation, subject: Lead | Deal, event: Event | None, webhooks: list
) -> AutomationRun | None:
    """Conditions, then the actions in one savepoint. None when conditions do not match."""
    via = (event.payload.get("_via") if event else None) or {}
    chain, depth = list(via.get("chain", [])), int(via.get("depth", 0))
    is_lead = isinstance(subject, Lead)
    run = AutomationRun(
        tenant_id=auto.tenant_id,
        automation_id=auto.id,
        event_id=event.id if event else None,
        lead_id=subject.id if is_lead else subject.lead_id,
        deal_id=None if is_lead else subject.id,
        status="done",
        detail=[],
    )
    if str(auto.id) in chain or depth >= MAX_DEPTH:
        return None  # a loop or a too-long chain: stop quietly
    facts = await (C.lead_facts(db, subject) if is_lead else C.deal_facts(db, subject))
    if not C.match_all(auto.conditions, facts):
        return None
    token = automation_context.set(
        {"id": str(auto.id), "name": auto.name, "chain": [*chain, str(auto.id)], "depth": depth + 1}
    )
    pending: list = []
    try:
        async with db.begin_nested():
            for a in auto.actions:
                try:
                    run.detail.append(
                        {"action": a["type"], "result": await _act(db, auto, subject, a, pending)}
                    )
                except Skip as s:
                    run.detail.append({"action": a["type"], "result": f"Skipped: {s}"})
        webhooks.extend(pending)
        auto.failures_in_row = 0
    except Exception as e:  # noqa: BLE001 — any failure is recorded, never breaks the batch
        run.status = "failed"
        run.error = (getattr(e, "detail", None) or str(e) or type(e).__name__)[:500]
        auto.failures_in_row += 1
        if auto.failures_in_row >= MAX_FAILURES and auto.is_active:
            auto.is_active = False
            admins = (
                await db.scalars(
                    select(User.id)
                    .join(Role, Role.id == User.role_id)
                    .where(Role.key.in_(["owner", "admin"]), User.status == "active")
                )
            ).all()
            title = f"Automation switched off after {MAX_FAILURES} failures: {auto.name}"
            await notify(db, auto.tenant_id, list(admins), "automation", title)
    finally:
        automation_context.reset(token)
    auto.last_run_at = L.now()
    db.add(run)
    await db.flush()
    return run


async def _subject_id(auto: Automation, event: Event) -> str | None:
    p = event.payload
    return p.get("lead_id") if auto.subject == "lead" else p.get("deal_id")


async def process_tenant(tenant_id: uuid.UUID, batch: int = 200) -> int:
    """Run automations for this company's new events. Returns how many runs happened."""
    runs, webhooks = 0, []
    async with tenant_session(tenant_id) as db:
        events = (
            await db.scalars(
                select(Event)
                .where(Event.automation_handled_at.is_(None))
                .order_by(Event.occurred_at, Event.id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not events:
            return 0
        autos = (
            await db.scalars(
                select(Automation)
                .where(Automation.is_active.is_(True))
                .order_by(Automation.position, Automation.created_at)
            )
        ).all()
        by_event: dict[str, list[Automation]] = {}
        for a in autos:
            ev = TRIGGERS[a.trigger["type"]][1]
            if ev:
                by_event.setdefault(ev, []).append(a)
        for event in events:
            for auto in by_event.get(event.type, []):
                if not auto.is_active or event.occurred_at < auto.created_at:
                    continue
                if not _trigger_matches(auto, event):
                    continue
                subject = await _load(db, auto.subject, await _subject_id(auto, event))
                if subject is None:
                    continue
                if await run_one(db, auto, subject, event, webhooks):
                    runs += 1
            event.automation_handled_at = L.now()
    await _send(tenant_id, webhooks)
    return runs


async def no_response_tenant(tenant_id: uuid.UUID) -> int:
    """'No response within X hours': open leads with no first response, once per lead."""
    runs, webhooks = 0, []
    async with tenant_session(tenant_id) as db:
        autos = (
            await db.scalars(
                select(Automation).where(
                    Automation.is_active.is_(True),
                    Automation.trigger["type"].astext == "lead.no_response",
                )
            )
        ).all()
        for auto in autos:
            already = select(AutomationRun.lead_id).where(AutomationRun.automation_id == auto.id)
            leads = (
                await db.scalars(
                    select(Lead)
                    .where(
                        Lead.is_open.is_(True),
                        Lead.first_response_at.is_(None),
                        Lead.created_at >= auto.created_at,
                        Lead.created_at <= L.now() - timedelta(hours=auto.trigger["hours"]),
                        Lead.id.not_in(already),
                    )
                    .limit(200)
                )
            ).all()
            for lead in leads:
                run = await run_one(db, auto, lead, None, webhooks)
                if run is None:  # conditions did not match: remember, so it is not rechecked
                    db.add(
                        AutomationRun(
                            tenant_id=tenant_id,
                            automation_id=auto.id,
                            lead_id=lead.id,
                            status="skipped",
                            detail=[],
                        )
                    )
                else:
                    runs += 1
    await _send(tenant_id, webhooks)
    return runs


async def _active_tenants() -> list[uuid.UUID]:
    async with platform_session() as s:
        return list((await s.scalars(select(Tenant.id).where(Tenant.status == "active"))).all())


async def process_all() -> int:
    return sum([await process_tenant(t) for t in await _active_tenants()])


async def no_response_all() -> int:
    return sum([await no_response_tenant(t) for t in await _active_tenants()])


async def pending_count(db: AsyncSession) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(Event).where(Event.automation_handled_at.is_(None))
        )
        or 0
    )


# ---------- webhooks ----------
def sign(secret: str, timestamp: int, body: str) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()


async def _send(tenant_id: uuid.UUID, webhooks: list) -> None:
    """After the changes are saved: queue each webhook (the job signs and retries)."""
    from app.workers.queue import enqueue

    for w in webhooks:
        await enqueue(
            "webhook_job",
            str(tenant_id),
            w["automation_id"],
            w["url"],
            w["secret"],
            w["body"],
            defer_by=0,
            job_id=f"webhook:{uuid.uuid4()}",
        )


async def deliver(url: str, secret: str, body: str) -> int:
    """POST once. Raises on a network error or a non-2xx answer."""
    import httpx

    check_url(url)
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "X-Versnq-Timestamp": str(ts),
        "X-Versnq-Signature": f"sha256={sign(secret, ts, body)}",
        "User-Agent": "Versnq-Core-Webhooks/1",
    }
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        r = await client.post(url, content=body, headers=headers)
    r.raise_for_status()
    return r.status_code


async def reset_failures(db: AsyncSession, auto_id: uuid.UUID) -> None:
    await db.execute(update(Automation).where(Automation.id == auto_id).values(failures_in_row=0))

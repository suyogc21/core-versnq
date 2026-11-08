"""Invented CRM data for demos: leads with identities, custom fields, timelines and follow-ups.
Deterministic (seeded random) so every demo-reset looks the same. Dev only (see demo.py)."""

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import (
    Activity,
    ActivityType,
    CustomFieldDefinition,
    CustomFieldUniqueValue,
    Lead,
    LeadIdentity,
    LeadSource,
    LeadStage,
    Task,
)
from app.modules.teams.models import TeamMember

FIRST = (
    "Aarav Vivaan Aditya Vihaan Arjun Sai Reyansh Krishna Ishaan Shaurya Atharv Kabir Rohan "
    "Ananya Diya Aadhya Saanvi Pari Anika Navya Myra Sara Ira Riya Kavya Meera Sneha Tanvi "
    "Nikhil Karthik Rahul Varun Yash Neha Pooja Shreya Isha Zara Fatima Imran Farhan Gurpreet "
    "Harpreet Simran Lakshmi Deepak Suresh Manoj Priyanka Aisha Omar"
).split()
LAST = (
    "Sharma Verma Gupta Iyer Nair Reddy Rao Patel Shah Mehta Joshi Kulkarni Desai Pillai Menon "
    "Khan Singh Kaur Das Banerjee Chatterjee Mukherjee Bose Naidu Hegde Shetty Agarwal Malhotra"
).split()
MAIL_DOMAINS = ["gmail.com", "outlook.com", "yahoo.in"]
NOTES = [
    "Asked about weekend timings.",
    "Wants fee details on WhatsApp.",
    "Parent will join the next call.",
    "Comparing with another provider; price sensitive.",
    "Prefers calls after 6 pm.",
    "Interested, needs EMI option.",
]


def _ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _phone(rng: random.Random, country: str) -> str:
    if country == "AE":
        return f"+9715{rng.choice('024568')}{rng.randint(1000000, 9999999)}"
    return f"+91{rng.choice('9876')}{rng.randint(100000000, 999999999)}"


async def seed_leads(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    count: int,
    country: str,
    reps: list[uuid.UUID],
    unassigned: int,
    custom: dict[str, object] | None = None,
    seed: int = 7,
) -> int:
    """Create `count` invented leads spread over the last ~45 days. Returns how many."""
    rng = random.Random(seed)
    stages = (await db.scalars(select(LeadStage).order_by(LeadStage.position))).all()
    sources = (await db.scalars(select(LeadSource).where(LeadSource.is_active))).all()
    fields = {
        f.key: f
        for f in (
            await db.scalars(
                select(CustomFieldDefinition).where(CustomFieldDefinition.entity == "lead")
            )
        ).all()
    }
    call = await db.scalar(select(ActivityType).where(ActivityType.key == "call"))
    outcomes = [(o["value"], o["label"]) for o in call.fields[0]["options"]]
    custom_types = (
        await db.scalars(
            select(ActivityType).where(
                ActivityType.is_system.is_(False), ActivityType.is_active.is_(True)
            )
        )
    ).all()
    open_stages = [s for s in stages if s.is_open]
    closed = {s.name: s for s in stages if not s.is_open}
    teams = dict((await db.execute(select(TeamMember.user_id, TeamMember.team_id))).all())
    unique_counter = 1000
    made = 0
    for i in range(count):
        created = _ago(rng.uniform(0.2, 45))
        roll = rng.random()
        if roll < 0.62:
            stage = rng.choice(open_stages[: max(1, len(open_stages))])
        elif roll < 0.74:
            stage = (
                next(s for s in stages if s.is_converted)
                if any(s.is_converted for s in stages)
                else open_stages[-1]
            )
        elif roll < 0.90:
            stage = next(
                (s for s in stages if s.is_unqualified and not s.is_system), closed.get("Invalid")
            )
        else:
            stage = closed["Invalid"]
        owner = None if i < unassigned else rng.choice(reps)
        if owner is None:  # unassigned leads are fresh website enquiries
            stage, created = open_stages[0], _ago(rng.uniform(0.05, 1.5))
        first, last = rng.choice(FIRST), rng.choice(LAST)
        phone = _phone(rng, country)
        email = (
            f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@{rng.choice(MAIL_DOMAINS)}"
            if rng.random() < 0.55
            else None
        )
        values: dict = {}
        for key, rule in (custom or {}).items():
            f = fields.get(key)
            if f is None:
                continue
            if rule == "pick":
                opts = [
                    o
                    for o in f.options
                    if not f.depends_on or o.get("parent") == values.get(f.depends_on)
                ]
                if opts:
                    values[key] = rng.choice(opts)["value"]
            elif rule == "unique" and (
                stage.is_converted or key in stage.required_fields or rng.random() < 0.2
            ):
                unique_counter += 1
                values[key] = f"{f.label[:3].upper()}-{unique_counter}"
        for key in stage.required_fields:  # stage requirements always met
            if key in fields and key not in values and fields[key].options:
                values[key] = rng.choice(fields[key].options)["value"]
        lead = Lead(
            tenant_id=tenant_id,
            kind="person",
            first_name=first,
            last_name=last,
            display_name=f"{first} {last}",
            primary_phone=phone,
            primary_email=email,
            owner_user_id=owner,
            team_id=teams.get(owner),
            assigned_at=created if owner else None,
            stage_id=stage.id,
            stage_changed_at=created,
            is_open=stage.is_open,
            origin=rng.choice(["inbound", "inbound", "outside"]),
            source_id=(sources[0] if owner is None else rng.choice(sources)).id,
            created_via="manual",
            custom_fields=values,
            city=rng.choice(["Pune", "Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai"])
            if country == "IN"
            else rng.choice(["Dubai", "Abu Dhabi", "Sharjah"]),
            unqualified_reason=rng.choice(
                ["Budget too low", "Chose a competitor", "Not reachable for weeks"]
            )
            if stage.is_unqualified
            else None,
            created_at=created,
            attribution={},
        )
        db.add(lead)
        await db.flush()
        db.add(
            LeadIdentity(
                tenant_id=tenant_id,
                lead_id=lead.id,
                type="phone",
                value=phone,
                value_normalized=phone,
                is_primary=True,
                is_whatsapp=True,
            )
        )
        if email:
            db.add(
                LeadIdentity(
                    tenant_id=tenant_id,
                    lead_id=lead.id,
                    type="email",
                    value=email,
                    value_normalized=email,
                    is_primary=True,
                )
            )
        for key, value in values.items():
            if fields[key].is_unique:
                db.add(
                    CustomFieldUniqueValue(
                        tenant_id=tenant_id,
                        entity="lead",
                        field_key=key,
                        value_normalized=str(value).lower(),
                        record_id=lead.id,
                    )
                )

        # Timeline: created, then a few calls / notes / custom activities, then the stage move.
        def act(type_key, summary, when, actor=owner, lead=lead, **kw):
            db.add(
                Activity(
                    tenant_id=tenant_id,
                    lead_id=lead.id,
                    type_key=type_key,
                    actor_type="user" if actor else "system",
                    actor_id=actor,
                    occurred_at=when,
                    summary=summary,
                    data=kw.pop("data", {}),
                    **kw,
                )
            )

        act("lead_created", "Added from a web enquiry" if owner is None else "Added", created, None)
        touches = 0 if owner is None else rng.randint(0, 4)
        last_touch = None
        when = created
        for _ in range(touches):
            when = min(when + timedelta(hours=rng.uniform(3, 60)), _ago(0.02))
            r = rng.random()
            if r < 0.65:
                value, label = rng.choice(outcomes)
                act(
                    "call",
                    f"Call: {label}",
                    when,
                    data={"disposition": value},
                    disposition=label,
                    body=rng.choice(NOTES) if rng.random() < 0.5 else None,
                )
                lead.last_disposition, lead.last_contacted_at = label, when
                lead.first_response_at = lead.first_response_at or when
            elif r < 0.85 or not custom_types:
                act("note", rng.choice(NOTES), when, body=rng.choice(NOTES))
            else:
                kind = rng.choice(custom_types)
                act(kind.key, kind.label, when)
                lead.last_contacted_at = when
            last_touch = when
        lead.last_activity_at = last_touch
        if stage.id != open_stages[0].id:
            act(
                "stage_changed",
                f"{open_stages[0].name} → {stage.name}",
                (last_touch or created) + timedelta(minutes=5),
            )

        # Follow-ups for open, owned leads: some overdue, some today, most later, a few missing.
        if stage.is_open and owner:
            r = rng.random()
            if r < 0.05:
                due = None
            elif r < 0.20:  # overdue: a business hour on one of the last three days
                past = datetime.now(UTC) - timedelta(days=rng.randint(1, 3))
                due = past.replace(
                    hour=rng.choice([4, 6, 8, 10]), minute=0, second=0, microsecond=0
                )
            elif r < 0.38:
                due = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(
                    hours=rng.randint(1, 6)
                )
            else:  # a business hour on one of the next ten days
                day = datetime.now(UTC) + timedelta(days=rng.randint(1, 10))
                due = day.replace(
                    hour=rng.choice([4, 5, 6, 8, 10, 11, 12]),
                    minute=rng.choice([0, 30]),
                    second=0,
                    microsecond=0,
                )  # 09:30–17:30 IST
            lead.next_follow_up_at = due
            if due:
                db.add(
                    Task(
                        tenant_id=tenant_id,
                        lead_id=lead.id,
                        title=f"Follow up with {lead.display_name}",
                        due_at=due,
                        owner_user_id=owner,
                        is_follow_up=True,
                        created_from="manual",
                        created_by_user_id=owner,
                        due_notified_at=due if due < datetime.now(UTC) else None,
                    )
                )
        made += 1
    await db.flush()
    return made


# ---------- step 1: routing, a web form, response times, notifications ----------
async def seed_routing(
    db: AsyncSession, tenant_id: uuid.UUID, *, team_id: uuid.UUID, reps: list[uuid.UUID]
) -> str:
    """Rules a real admissions team would set up. Returns the demo web form's secret key."""
    import hashlib
    import secrets

    from app.modules.crm.models import (
        AssignmentRule,
        CaptureSource,
        Lead,
        Notification,
        SlaRule,
    )
    from app.modules.settings.models import TenantSettings

    settings = await db.get(TenantSettings, tenant_id)
    settings.org_grouping, settings.leakage_hours, settings.leakage_action = "suggest", 24, "alert"
    sources = {s.name: s.id for s in (await db.scalars(select(LeadSource))).all()}
    online = [str(sources[n]) for n in ("Website", "Meta ads", "Google ads") if n in sources]
    db.add_all(
        [
            AssignmentRule(
                tenant_id=tenant_id,
                name="Online enquiries → Pune counsellors",
                position=0,
                conditions=[{"field": "source", "op": "in", "values": online}],
                strategy="round_robin",
                team_id=team_id,
                user_ids=[],
            ),
            AssignmentRule(
                tenant_id=tenant_id,
                name="Everyone else takes turns",
                position=1,
                conditions=[],
                strategy="round_robin",
                user_ids=[str(r) for r in reps],
            ),
            SlaRule(
                tenant_id=tenant_id,
                name="First call",
                trigger="lead_created",
                within_minutes=30,
                create_task=True,
                task_title="Call the new enquiry",
                on_breach="alert",
            ),
        ]
    )
    key = "vqf_" + secrets.token_urlsafe(24)
    db.add(
        CaptureSource(
            tenant_id=tenant_id,
            name="Website enquiry form",
            source_id=sources["Website"],
            key_hash=hashlib.sha256(key.encode()).hexdigest(),
            key_hint=key[:8],
            field_map={"Which course?": "cf.program_interest"},
            consent_text="I agree to be contacted by email and WhatsApp about courses",
        )
    )
    # A few unread notifications so the bell has something to show.
    recent = (
        await db.scalars(
            select(Lead)
            .where(Lead.owner_user_id.in_(reps))
            .order_by(Lead.created_at.desc())
            .limit(12)
        )
    ).all()
    for lead in recent:
        db.add(
            Notification(
                tenant_id=tenant_id,
                user_id=lead.owner_user_id,
                kind="lead_assigned",
                title=f"New lead: {lead.display_name}",
                lead_id=lead.id,
            )
        )
    await db.flush()
    return key

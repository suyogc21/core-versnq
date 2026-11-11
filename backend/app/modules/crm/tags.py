"""Tags on leads and deals (Decision log #27, A2/A3). Anyone who may edit a lead or deal tags
it and may create a new tag while doing so; tidying tags is crm.configure (tags_router)."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.crm.models import Deal, Lead, Tag, Tagging

PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#8b5cf6", "#64748b"]
MAX_PER_SUBJECT = 50


async def resolve(
    db: AsyncSession, tenant_id: uuid.UUID, ids: list[uuid.UUID], names: list[str]
) -> list[Tag]:
    """Existing tags by id, plus tags by name (made when new; matched without case)."""
    found: dict[uuid.UUID, Tag] = {}
    if ids:
        rows = (await db.scalars(select(Tag).where(Tag.id.in_(ids)))).all()
        if len(rows) != len(set(ids)):
            raise Invalid("Choose tags that exist")
        found |= {t.id: t for t in rows}
    for raw in names:
        name = " ".join(raw.split())[:60]
        if not name:
            continue
        tag = await db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower()))
        if tag is None:
            count = await db.scalar(select(func.count()).select_from(Tag)) or 0
            tag = Tag(tenant_id=tenant_id, name=name, colour=PALETTE[count % len(PALETTE)])
            db.add(tag)
            await db.flush()
        found[tag.id] = tag
    return list(found.values())


def _col(subject: Lead | Deal):
    return Tagging.lead_id if isinstance(subject, Lead) else Tagging.deal_id


async def current(db: AsyncSession, subject: Lead | Deal) -> set[uuid.UUID]:
    return set((await db.scalars(select(Tagging.tag_id).where(_col(subject) == subject.id))).all())


async def change(
    db: AsyncSession,
    actor: CurrentUser | None,
    subject: Lead | Deal,
    *,
    add: list[Tag] = (),
    remove: list[uuid.UUID] = (),
) -> tuple[list[str], list[str]]:
    """Add and remove tags; one timeline entry and one event. Returns (added, removed) names."""
    have = await current(db, subject)
    to_add = [t for t in add if t.id not in have]
    to_remove = [i for i in remove if i in have]
    if not to_add and not to_remove:
        return [], []
    if len(have) + len(to_add) - len(to_remove) > MAX_PER_SUBJECT:
        raise Invalid(f"At most {MAX_PER_SUBJECT} tags each")
    is_lead = isinstance(subject, Lead)
    for t in to_add:
        db.add(
            Tagging(
                tenant_id=subject.tenant_id,
                tag_id=t.id,
                lead_id=subject.id if is_lead else None,
                deal_id=None if is_lead else subject.id,
                created_by_user_id=actor.user.id if actor else None,
            )
        )
    if to_remove:
        await db.execute(
            delete(Tagging).where(_col(subject) == subject.id, Tagging.tag_id.in_(to_remove))
        )
    await db.flush()
    removed_names = (
        list((await db.scalars(select(Tag.name).where(Tag.id.in_(to_remove)))).all())
        if to_remove
        else []
    )
    added_names = [t.name for t in to_add]
    parts = [f"+{n}" for n in added_names] + [f"−{n}" for n in removed_names]
    data = {"added": added_names, "removed": removed_names}
    if is_lead:
        from app.modules.crm import leads as L

        await L.log(db, subject, "tagged", f"Tags: {', '.join(parts)}", actor, data)
        await L.event(db, subject, "lead.updated", {"fields": ["tags"]})
    else:
        from app.modules.crm import deals as D

        await D.log(db, subject, "tagged", f"{subject.name} tags: {', '.join(parts)}", actor, data)
        await D.event(db, subject, "deal.updated", {"fields": ["tags"]})
    return added_names, removed_names


async def set_exact(
    db: AsyncSession, actor: CurrentUser | None, subject: Lead | Deal, tags: list[Tag]
) -> None:
    want = {t.id for t in tags}
    have = await current(db, subject)
    await change(db, actor, subject, add=tags, remove=list(have - want))


async def of(db: AsyncSession, *, lead_ids=(), deal_ids=()) -> dict[uuid.UUID, list[Tag]]:
    """Tags per lead or deal id, by name."""
    lead_ids, deal_ids = list(lead_ids), list(deal_ids)
    if not lead_ids and not deal_ids:
        return {}
    col = Tagging.lead_id if lead_ids else Tagging.deal_id
    rows = (
        await db.execute(
            select(col, Tag)
            .join(Tag, Tag.id == Tagging.tag_id)
            .where(col.in_(lead_ids or deal_ids))
            .order_by(func.lower(Tag.name))
        )
    ).all()
    out: dict[uuid.UUID, list[Tag]] = {}
    for sid, tag in rows:
        out.setdefault(sid, []).append(tag)
    return out


def has_any(subject_col, tag_ids: list[uuid.UUID]):
    """SQL: the lead/deal has at least one of these tags."""
    col = Tagging.lead_id if subject_col is Lead.id else Tagging.deal_id
    return subject_col.in_(select(col).where(Tagging.tag_id.in_(tag_ids)))

"""One definition of 'which leads' for the list, the view counts and bulk actions, so
'select all matching' acts on exactly the rows the list shows."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.auth.deps import CurrentUser
from app.modules.crm import access as A
from app.modules.crm import leads as L
from app.modules.crm import tags as T
from app.modules.crm.models import Lead, LeadIdentity, LeadSource, LeadStage
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User

SortKey = Literal[
    "name", "stage", "follow_up", "owner", "last_activity", "source", "created", "city", "score"
]


class LeadFilter(BaseModel):
    """Every value list is OR within itself and AND across fields."""

    q: str | None = Field(default=None, max_length=200)
    stage_id: list[uuid.UUID] = []
    source_id: list[uuid.UUID] = []
    brand_id: list[uuid.UUID] = Field(default=[], description="of any of these brands")
    owner: list[str] = Field(default=[], description="'me', 'unassigned' or user ids")
    status: Literal["open", "closed"] | None = None
    follow_up: Literal["overdue", "today", "none"] | None = None
    cf: list[str] = Field(default=[], description="custom field filters as key:value")
    tag: list[uuid.UUID] = Field(default=[], description="has any of these tags")
    band: list[Literal["hot", "warm", "cold"]] = []
    created_from: date | None = Field(default=None, description="created on or after (company day)")
    created_to: date | None = Field(default=None, description="created on or before (company day)")


async def where_clauses(db: AsyncSession, actor: CurrentUser, f: LeadFilter) -> list:
    where = [await L.visibility_filter(db, actor)]
    rules = await A.rules(db, actor, "lead")  # hidden fields can't be searched or filtered
    if f.q and f.q.strip():
        term = f"%{f.q.strip().lower()}%"  # ILIKE uses the trigram indexes (0020)
        digits = "".join(ch for ch in f.q if ch.isdigit())
        identity = select(LeadIdentity.lead_id).where(
            or_(
                LeadIdentity.value_normalized.like(term),
                LeadIdentity.value_normalized.like(f"%{digits}%") if len(digits) >= 4 else False,
            )
        )
        where.append(
            or_(
                Lead.display_name.ilike(term),
                Lead.org_name.ilike(term) if not rules.hidden("org_name") else False,
                Lead.id.in_(identity),
            )
        )
    if f.created_from or f.created_to:  # whole days in the company's time zone (dashboards)
        tz = ZoneInfo(await db.scalar(select(TenantSettings.timezone)) or "UTC")
        if f.created_from:
            start = datetime.combine(f.created_from, time.min, tz)
            where.append(Lead.created_at >= start)
        if f.created_to:
            end = datetime.combine(f.created_to + timedelta(days=1), time.min, tz)
            where.append(Lead.created_at < end)
    if f.stage_id:
        where.append(Lead.stage_id.in_(f.stage_id))
    if f.source_id:
        where.append(Lead.source_id.in_(f.source_id))
    if f.brand_id:
        where.append(Lead.brand_id.in_(f.brand_id))
    if f.owner:
        owners, unassigned = set(), False
        for o in f.owner:
            if o == "me":
                owners.add(actor.user.id)
            elif o == "unassigned":
                unassigned = True
            else:
                try:
                    owners.add(uuid.UUID(o))
                except ValueError:
                    raise Invalid("owner must be 'me', 'unassigned' or a user id") from None
        parts = ([Lead.owner_user_id.in_(owners)] if owners else []) + (
            [Lead.owner_user_id.is_(None)] if unassigned else []
        )
        where.append(or_(*parts))
    if f.status:
        where.append(Lead.is_open.is_(f.status == "open"))
    if f.follow_up:
        now, end_of_day = await L.day_bounds(db, actor.user.tenant_id)
        where.append(Lead.is_open.is_(True))
        where.append(
            {
                "overdue": Lead.next_follow_up_at < now,
                "today": and_(Lead.next_follow_up_at >= now, Lead.next_follow_up_at < end_of_day),
                "none": Lead.next_follow_up_at.is_(None),
            }[f.follow_up]
        )
    if f.tag:
        where.append(T.has_any(Lead.id, f.tag))
    if f.band:
        where.append(Lead.score_band.in_(f.band))
    by_key: dict[str, list[str]] = {}
    for item in f.cf:
        key, sep, value = item.partition(":")
        if not sep or not key:
            raise Invalid("Custom field filters look like key:value")
        by_key.setdefault(key, []).append(value)
    for key, values in by_key.items():
        if rules.hidden(f"cf.{key}"):
            raise Invalid("You can't filter on a field you can't see")
        # A select field holds a string, a multi-select a list: match either.
        where.append(
            or_(
                Lead.custom_fields[key].astext.in_(values),
                *[Lead.custom_fields[key].contains([v]) for v in values],
            )
        )
    return where


def ordered(query, sort: SortKey, direction: Literal["asc", "desc"]):
    """Apply a sort; ties break on newest first so pages never overlap."""
    up = direction == "asc"

    def by(col):
        return (col.asc() if up else col.desc()).nulls_last()

    if sort == "stage":
        query = query.join(LeadStage, LeadStage.id == Lead.stage_id)
        key = by(LeadStage.position)
    elif sort == "owner":
        query = query.outerjoin(User, User.id == Lead.owner_user_id)
        key = by(User.name)
    elif sort == "source":
        query = query.join(LeadSource, LeadSource.id == Lead.source_id)
        key = by(LeadSource.name)
    else:
        column = {
            "name": Lead.display_name,
            "follow_up": Lead.next_follow_up_at,
            "last_activity": Lead.last_activity_at,
            "created": Lead.created_at,
            "city": Lead.city,
            "score": Lead.score,
        }[sort]
        key = by(column)
    return query.order_by(key, Lead.created_at.desc(), Lead.id)


async def matching_ids(
    db: AsyncSession, actor: CurrentUser, f: LeadFilter, cap: int
) -> list[uuid.UUID]:
    where = await where_clauses(db, actor, f)
    rows = await db.scalars(select(Lead.id).where(*where).order_by(Lead.created_at).limit(cap + 1))
    ids = list(rows.all())
    if len(ids) > cap:
        raise Invalid(f"That matches more than {cap} leads; narrow the filters first")
    return ids

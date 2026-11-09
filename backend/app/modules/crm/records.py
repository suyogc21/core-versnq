"""Company-defined records (Property, Batch, Vehicle...) and labelled links between any leads
and records. One generic engine: nothing here knows any type by name.

Access is set per role and per record type: view / create / edit / delete, plus a scope
(own / team / all, like leads). The Owner role may always do everything. A role without a row
for a type has no access. Types without owners are shared: anyone who may view sees all.

Links: a link type allows links between two kinds (a lead kind or a record type) and names
them both ways ("Interested in" / "Interested buyers"). Either side can be limited to one.
To link or unlink you must be able to see both ends and edit at least one of them. A link is
written on both timelines and emits link.created / link.deleted.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import false, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.events import emit
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import (
    Activity,
    Lead,
    Link,
    LinkType,
    Record,
    RecordType,
    RecordTypeAccess,
    RecordTypeStage,
)
from app.modules.roles.models import Role
from app.modules.teams.service import visible_user_ids
from app.modules.users.models import User


# ---------- access ----------
@dataclass
class Access:
    view: bool = False
    create: bool = False
    edit: bool = False
    delete: bool = False
    scope: str = "own"


FULL = Access(True, True, True, True, "all")

# Starting access for a new type, by system role. Admins change it per type.
DEFAULT_ACCESS: dict[str, Access] = {
    "admin": FULL,
    "sales_manager": Access(True, True, True, False, "team"),
    "sales_user": Access(True, True, True, False, "own"),
}


async def access_for(db: AsyncSession, actor: CurrentUser, rtype: RecordType) -> Access:
    if actor.role.key == "owner":
        return FULL
    row = await db.scalar(
        select(RecordTypeAccess).where(
            RecordTypeAccess.role_id == actor.role.id,
            RecordTypeAccess.record_type_id == rtype.id,
        )
    )
    if row is None:
        return Access()
    return Access(row.can_view, row.can_create, row.can_edit, row.can_delete, row.scope)


async def seed_access(db: AsyncSession, rtype: RecordType) -> None:
    """Default rows for every role (custom roles: view only, with the role's own scope)."""
    for role in (await db.scalars(select(Role))).all():
        if role.key == "owner":
            continue
        a = DEFAULT_ACCESS.get(role.key or "", None)
        if a is None:
            a = Access(view=role.key != "finance", scope=role.scope)
        db.add(
            RecordTypeAccess(
                tenant_id=rtype.tenant_id,
                role_id=role.id,
                record_type_id=rtype.id,
                can_view=a.view,
                can_create=a.create,
                can_edit=a.edit,
                can_delete=a.delete,
                scope=a.scope,
            )
        )


async def record_filter(db: AsyncSession, actor: CurrentUser, rtype: RecordType, acc: Access):
    """SQL condition for the records of this type the person may see."""
    if not acc.view:
        return false()
    if not rtype.has_owner or acc.scope == "all":
        return true()
    visible = await visible_user_ids(db, actor.user.id, acc.scope)
    owned = Record.owner_user_id.in_(visible) if visible else false()
    if acc.scope == "team":
        return or_(owned, Record.owner_user_id.is_(None))
    return owned


async def get_type(db: AsyncSession, key_or_id: str | uuid.UUID) -> RecordType:
    if isinstance(key_or_id, uuid.UUID):
        rtype = await db.get(RecordType, key_or_id)
    else:
        rtype = await db.scalar(select(RecordType).where(RecordType.key == key_or_id))
    if rtype is None:
        raise NotFound("Record type not found")
    return rtype


@dataclass
class Visible:
    record: Record
    rtype: RecordType
    access: Access


async def get_visible(db: AsyncSession, actor: CurrentUser, record_id: uuid.UUID) -> Visible:
    record = await db.get(Record, record_id)
    if record is None:
        raise NotFound("Record not found")
    rtype = await db.get(RecordType, record.record_type_id)
    acc = await access_for(db, actor, rtype)
    seen = await db.scalar(
        select(Record.id).where(Record.id == record_id, await record_filter(db, actor, rtype, acc))
    )
    if seen is None:
        raise NotFound("Record not found")
    return Visible(record, rtype, acc)


async def check_owner(
    db: AsyncSession, actor: CurrentUser, acc: Access, user_id: uuid.UUID | None
) -> User | None:
    """Owners: someone active you can see; people with 'own' scope only give records to
    themselves."""
    if user_id is None:
        if acc.scope == "own":
            raise Forbidden("You cannot leave this unassigned")
        return None
    if acc.scope == "own" and user_id != actor.user.id:
        raise Forbidden("You can only own records yourself")
    user = await db.get(User, user_id)
    visible = await visible_user_ids(db, actor.user.id, acc.scope)
    if user is None or user.status != "active" or (visible is not None and user.id not in visible):
        raise Invalid("Choose an active user from your team")
    return user


# ---------- stages ----------
async def check_stage(
    db: AsyncSession, rtype: RecordType, record: Record, stage_id
) -> RecordTypeStage:
    stage = await db.get(RecordTypeStage, stage_id)
    if stage is None or stage.record_type_id != rtype.id:
        raise Invalid("Choose a stage of this type")
    missing = []
    defs = await L.lead_fields(db, rtype.entity)
    for key in stage.required_fields:
        if key == "owner":
            if not record.owner_user_id:
                missing.append("owner")
        elif (record.custom_fields or {}).get(key) is None:
            missing.append(defs[key].label if key in defs else key)
    if missing:
        raise Invalid(f"To move to {stage.name}, fill in: {', '.join(missing)}")
    return stage


async def first_stage(db: AsyncSession, rtype: RecordType) -> RecordTypeStage | None:
    if not rtype.has_stages:
        return None
    return await db.scalar(
        select(RecordTypeStage)
        .where(RecordTypeStage.record_type_id == rtype.id, RecordTypeStage.is_open.is_(True))
        .order_by(RecordTypeStage.position)
        .limit(1)
    )


# ---------- timeline + events ----------
async def log(
    db: AsyncSession,
    record: Record,
    type_key: str,
    summary: str,
    actor: CurrentUser | None,
    data: dict | None = None,
    body: str | None = None,
) -> Activity:
    activity = Activity(
        tenant_id=record.tenant_id,
        record_id=record.id,
        type_key=type_key,
        actor_type="user" if actor else "system",
        actor_id=actor.user.id if actor else None,
        occurred_at=L.now(),
        summary=summary[:500],
        body=body,
        data=data or {},
    )
    db.add(activity)
    await db.flush()
    return activity


async def event(db: AsyncSession, record: Record, rtype: RecordType, type_: str, extra=None):
    await emit(
        db,
        record.tenant_id,
        type_,
        {"record_id": str(record.id), "record_type": rtype.key} | (extra or {}),
    )


# ---------- links ----------
@dataclass
class End:
    """One end of a link: a lead or a record."""

    kind: str  # lead / record
    id: uuid.UUID
    name: str
    type_id: uuid.UUID | None  # None for leads
    type_key: str | None
    obj: Lead | Record


async def resolve(db: AsyncSession, actor: CurrentUser, lead_id, record_id) -> tuple[End, bool]:
    """A visible end and whether the actor may edit it."""
    if (lead_id is None) == (record_id is None):
        raise Invalid("Each side of a link is one lead or one record")
    if lead_id:
        lead = await L.get_visible(db, actor, lead_id)
        return End("lead", lead.id, lead.display_name, None, None, lead), L.can(actor, "leads.edit")
    v = await get_visible(db, actor, record_id)
    return End(
        "record", v.record.id, v.record.name, v.rtype.id, v.rtype.key, v.record
    ), v.access.edit


def _side(link_kind_type: uuid.UUID | None, end: End) -> bool:
    return (end.kind == "lead" and link_kind_type is None) or (
        end.kind == "record" and end.type_id == link_kind_type
    )


def _cols(prefix: str, end: End) -> dict:
    return {
        f"{prefix}_lead_id": end.id if end.kind == "lead" else None,
        f"{prefix}_record_id": end.id if end.kind == "record" else None,
    }


def _match(prefix: str, end: End):
    col = getattr(Link, f"{prefix}_{'lead' if end.kind == 'lead' else 'record'}_id")
    return col == end.id


async def _log_end(db, end: End, type_key: str, summary: str, actor, data: dict) -> None:
    if end.kind == "lead":
        await L.log(db, end.obj, type_key, summary, actor, data)
    else:
        await log(db, end.obj, type_key, summary, actor, data)


async def create_link(
    db: AsyncSession, actor: CurrentUser, link_type: LinkType, src: End, dst: End
) -> Link:
    if not link_type.is_active:
        raise Invalid("This kind of link is switched off")
    if not (_side(link_type.from_type_id, src) and _side(link_type.to_type_id, dst)):
        raise Invalid("These two cannot be linked this way")
    if src.kind == dst.kind and src.id == dst.id:
        raise Invalid("Something cannot be linked to itself")
    # Serialise links of this type touching either end, so 'only one' limits hold.
    for end in (src, dst):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"link:{link_type.id}:{end.id}"},
        )
    exists = await db.scalar(
        select(Link.id).where(
            Link.link_type_id == link_type.id, _match("from", src), _match("to", dst)
        )
    )
    if exists:
        raise Conflict("These are already linked")
    if not link_type.many_to:
        taken = await db.scalar(
            select(Link.id).where(Link.link_type_id == link_type.id, _match("from", src))
        )
        if taken:
            raise Conflict(f"{src.name} already has a '{link_type.label}' link; remove it first")
    if not link_type.many_from:
        taken = await db.scalar(
            select(Link.id).where(Link.link_type_id == link_type.id, _match("to", dst))
        )
        if taken:
            raise Conflict(
                f"{dst.name} already has a '{link_type.inverse_label}' link; remove it first"
            )
    link = Link(
        tenant_id=actor.user.tenant_id,
        link_type_id=link_type.id,
        created_by_user_id=actor.user.id,
        **_cols("from", src),
        **_cols("to", dst),
    )
    db.add(link)
    await db.flush()
    data = {"link_id": str(link.id), "link_type_id": str(link_type.id)}
    await _log_end(db, src, "linked", f"{link_type.label}: {dst.name}", actor, data)
    await _log_end(db, dst, "linked", f"{link_type.inverse_label}: {src.name}", actor, data)
    await emit(db, actor.user.tenant_id, "link.created", _payload(link, link_type))
    return link


async def delete_link(db: AsyncSession, actor: CurrentUser, link: Link) -> None:
    link_type = await db.get(LinkType, link.link_type_id)
    src, src_edit = await resolve(db, actor, link.from_lead_id, link.from_record_id)
    dst, dst_edit = await resolve(db, actor, link.to_lead_id, link.to_record_id)
    if not (src_edit or dst_edit):
        raise Forbidden("permission_denied")
    data = {"link_id": str(link.id), "link_type_id": str(link_type.id)}
    payload = _payload(link, link_type)
    await db.delete(link)
    await _log_end(db, src, "unlinked", f"{link_type.label}: {dst.name} removed", actor, data)
    await _log_end(
        db, dst, "unlinked", f"{link_type.inverse_label}: {src.name} removed", actor, data
    )
    await emit(db, actor.user.tenant_id, "link.deleted", payload)


def _payload(link: Link, link_type: LinkType) -> dict:
    def side(lead_id, record_id):
        return {"lead_id": str(lead_id)} if lead_id else {"record_id": str(record_id)}

    return {
        "link_id": str(link.id),
        "link_type_id": str(link_type.id),
        "label": link_type.label,
        "from": side(link.from_lead_id, link.from_record_id),
        "to": side(link.to_lead_id, link.to_record_id),
    }


@dataclass
class LinkView:
    """A link as seen from one end."""

    link: Link
    link_type: LinkType
    label: str  # the name from this end
    other: End


async def links_of(db: AsyncSession, actor: CurrentUser, end: End) -> list[LinkView]:
    """Every link of a lead or record, both directions; other ends you cannot see are left out."""
    rows = (
        await db.execute(
            select(Link, LinkType)
            .join(LinkType, LinkType.id == Link.link_type_id)
            .where(or_(_match("from", end), _match("to", end)))
            .order_by(LinkType.position, Link.created_at)
            .limit(1000)
        )
    ).all()
    lead_ids, record_ids = set(), set()
    for link, _ in rows:
        outward = _match_value("from", link, end)
        lid, rid = (
            (link.to_lead_id, link.to_record_id)
            if outward
            else (link.from_lead_id, link.from_record_id)
        )
        (lead_ids if lid else record_ids).add(lid or rid)
    leads = {}
    if lead_ids:
        visible = await L.visibility_filter(db, actor)
        leads = {
            x.id: x
            for x in (await db.scalars(select(Lead).where(Lead.id.in_(lead_ids), visible))).all()
        }
    records = await _visible_records(db, actor, record_ids)
    out = []
    for link, link_type in rows:
        outward = _match_value("from", link, end)
        lid, rid = (
            (link.to_lead_id, link.to_record_id)
            if outward
            else (link.from_lead_id, link.from_record_id)
        )
        if lid and lid in leads:
            other = End("lead", lid, leads[lid].display_name, None, None, leads[lid])
        elif rid and rid in records:
            r, rt = records[rid]
            other = End("record", rid, r.name, rt.id, rt.key, r)
        else:
            continue
        out.append(
            LinkView(
                link, link_type, link_type.label if outward else link_type.inverse_label, other
            )
        )
    return out


def _match_value(prefix: str, link: Link, end: End) -> bool:
    col = f"{prefix}_{'lead' if end.kind == 'lead' else 'record'}_id"
    return getattr(link, col) == end.id


async def _visible_records(
    db: AsyncSession, actor: CurrentUser, ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[Record, RecordType]]:
    if not ids:
        return {}
    found = (await db.scalars(select(Record).where(Record.id.in_(ids)))).all()
    out = {}
    by_type: dict[uuid.UUID, list[Record]] = {}
    for r in found:
        by_type.setdefault(r.record_type_id, []).append(r)
    for type_id, items in by_type.items():
        rtype = await db.get(RecordType, type_id)
        acc = await access_for(db, actor, rtype)
        allowed = set(
            (
                await db.scalars(
                    select(Record.id).where(
                        Record.id.in_([r.id for r in items]),
                        await record_filter(db, actor, rtype, acc),
                    )
                )
            ).all()
        )
        for r in items:
            if r.id in allowed:
                out[r.id] = (r, rtype)
    return out


async def count_records(db: AsyncSession, rtype: RecordType) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(Record).where(Record.record_type_id == rtype.id)
        )
        or 0
    )

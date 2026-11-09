"""Records of company-defined types, their timeline, and links between leads and records."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Text, cast, func, inspect, nulls_last, or_, select

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.modules.auth.deps import ActiveUser
from app.modules.crm import leads as L
from app.modules.crm import records as RC
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import (
    Activity,
    CustomFieldUniqueValue,
    Link,
    LinkType,
    Record,
    RecordTypeStage,
)
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["records"], dependencies=CRM)


class RecordOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    record_type_id: uuid.UUID
    name: str
    owner_user_id: uuid.UUID | None
    owner_name: str | None = None
    stage_id: uuid.UUID | None
    stage_changed_at: datetime | None
    custom_fields: dict
    created_at: datetime
    updated_at: datetime
    version: int


class RecordPage(BaseModel):
    items: list[RecordOut]
    total: int


class RecordIn(BaseModel):
    type: str = Field(min_length=1, max_length=40)  # the record type's key
    name: str = Field(min_length=1, max_length=300)
    owner_user_id: uuid.UUID | None = None
    assign_to_me: bool = True
    stage_id: uuid.UUID | None = None
    custom_fields: dict = {}


class RecordPatch(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=300)
    owner_user_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    custom_fields: dict | None = None


async def _out(db, records: list[Record]) -> list[RecordOut]:
    for r in records:
        if inspect(r).expired_attributes:
            await db.refresh(r)
    owners = {r.owner_user_id for r in records if r.owner_user_id}
    names = {}
    if owners:
        names = dict(
            (await db.execute(select(User.id, User.name).where(User.id.in_(owners)))).all()
        )
    out = []
    for r in records:
        item = RecordOut.model_validate(r)
        item.owner_name = names.get(r.owner_user_id)
        out.append(item)
    return out


SortKey = Literal["name", "created", "updated", "owner", "stage"]


@router.get("/records", response_model=RecordPage)
async def list_records(
    db: CrmDb,
    actor: ActiveUser,
    type: Annotated[str, Query(min_length=1, max_length=40)],
    q: str | None = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006 — FastAPI query lists
    stage_id: Annotated[list[uuid.UUID], Query()] = [],  # noqa: B006
    cf: Annotated[list[str], Query()] = [],  # noqa: B006 — "key:value"
    sort: SortKey = "created",
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecordPage:
    rtype = await RC.get_type(db, type)
    acc = await RC.access_for(db, actor, rtype)
    if not acc.view or not rtype.is_active:
        raise NotFound("Record type not found")
    where = [Record.record_type_id == rtype.id, await RC.record_filter(db, actor, rtype, acc)]
    if q and q.strip():
        term = f"%{q.strip()}%"
        where.append(or_(Record.name.ilike(term), cast(Record.custom_fields, Text).ilike(term)))
    if owner:
        conds = []
        for o in owner:
            if o == "me":
                conds.append(Record.owner_user_id == actor.user.id)
            elif o == "unassigned":
                conds.append(Record.owner_user_id.is_(None))
            else:
                try:
                    conds.append(Record.owner_user_id == uuid.UUID(o))
                except ValueError:
                    raise Invalid("Unknown owner filter") from None
        where.append(or_(*conds))
    if stage_id:
        where.append(Record.stage_id.in_(stage_id))
    by_key: dict[str, list[str]] = {}
    for item in cf:
        key, _, value = item.partition(":")
        if not key or not value:
            raise Invalid("Custom field filters look like key:value")
        by_key.setdefault(key, []).append(value)
    for key, values in by_key.items():
        field = Record.custom_fields[key]
        where.append(or_(*[or_(field.astext == v, field.contains([v])) for v in values]))
    total = await db.scalar(select(func.count()).select_from(Record).where(*where)) or 0
    query = select(Record).where(*where)
    order = {
        "name": func.lower(Record.name),
        "created": Record.created_at,
        "updated": Record.updated_at,
        "owner": select(User.name).where(User.id == Record.owner_user_id).scalar_subquery(),
        "stage": select(RecordTypeStage.position)
        .where(RecordTypeStage.id == Record.stage_id)
        .scalar_subquery(),
    }[sort]
    order = order.asc() if direction == "asc" else order.desc()
    rows = await db.scalars(
        query.order_by(nulls_last(order), Record.created_at.desc(), Record.id)
        .limit(limit)
        .offset(offset)
    )
    return RecordPage(items=await _out(db, list(rows.all())), total=total)


@router.post("/records", response_model=RecordOut, status_code=status.HTTP_201_CREATED)
async def create_record(body: RecordIn, db: CrmDb, actor: ActiveUser) -> RecordOut:
    rtype = await RC.get_type(db, body.type)
    acc = await RC.access_for(db, actor, rtype)
    if not rtype.is_active or not acc.view:
        raise NotFound("Record type not found")
    if not acc.create:
        raise Forbidden("permission_denied")
    record = Record(
        tenant_id=actor.user.tenant_id,
        record_type_id=rtype.id,
        name=" ".join(body.name.split()),
        custom_fields={},
        created_by_user_id=actor.user.id,
    )
    if rtype.has_owner:
        owner_id = body.owner_user_id or (actor.user.id if body.assign_to_me else None)
        owner = await RC.check_owner(db, actor, acc, owner_id)
        record.owner_user_id = owner.id if owner else None
        record.team_id = await L.owner_team(db, record.owner_user_id)
    db.add(record)
    await db.flush()
    await L.apply_custom_fields(db, record, body.custom_fields, creating=True, entity=rtype.entity)
    if rtype.has_stages:
        stage = (
            await RC.check_stage(db, rtype, record, body.stage_id)
            if body.stage_id
            else await RC.first_stage(db, rtype)
        )
        if stage:
            record.stage_id, record.stage_changed_at = stage.id, L.now()
    await RC.log(db, record, "record_created", f"Added by {actor.user.name}", actor)
    await RC.event(db, record, rtype, "record.created")
    await db.flush()
    return (await _out(db, [record]))[0]


@router.get("/records/{record_id}", response_model=RecordOut)
async def get_record(record_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> RecordOut:
    v = await RC.get_visible(db, actor, record_id)
    return (await _out(db, [v.record]))[0]


@router.patch("/records/{record_id}", response_model=RecordOut)
async def update_record(
    record_id: uuid.UUID, body: RecordPatch, db: CrmDb, actor: ActiveUser
) -> RecordOut:
    v = await RC.get_visible(db, actor, record_id)
    record, rtype, acc = v.record, v.rtype, v.access
    if not acc.edit:
        raise Forbidden("permission_denied")
    if body.version != record.version:
        raise Conflict("Someone else changed this record. Reload to see their changes")
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    changed: list[str] = []
    if body.name is not None and " ".join(body.name.split()) != record.name:
        record.name = " ".join(body.name.split())
        changed.append("name")
    if body.custom_fields is not None:
        changed += await L.apply_custom_fields(
            db, record, body.custom_fields, creating=False, entity=rtype.entity
        )
    if (
        "owner_user_id" in changes
        and rtype.has_owner
        and changes["owner_user_id"] != record.owner_user_id
    ):
        owner = await RC.check_owner(db, actor, acc, changes["owner_user_id"])
        record.owner_user_id = owner.id if owner else None
        record.team_id = await L.owner_team(db, record.owner_user_id)
        await RC.log(
            db,
            record,
            "owner_changed",
            f"Assigned to {owner.name}" if owner else "Unassigned",
            actor,
            {"to": str(owner.id) if owner else None},
        )
        changed.append("owner")
    if changes.get("stage_id") and rtype.has_stages and changes["stage_id"] != record.stage_id:
        stage = await RC.check_stage(db, rtype, record, changes["stage_id"])
        old = await db.get(RecordTypeStage, record.stage_id) if record.stage_id else None
        record.stage_id, record.stage_changed_at = stage.id, L.now()
        await RC.log(
            db,
            record,
            "stage_changed",
            f"{old.name if old else '—'} → {stage.name}",
            actor,
            {"from": str(old.id) if old else None, "to": str(stage.id)},
        )
        await RC.event(
            db,
            record,
            rtype,
            "record.stage_changed",
            {"from": str(old.id) if old else None, "to": str(stage.id)},
        )
    details = [c for c in changed if c != "owner"]
    if details:
        await RC.log(
            db, record, "lead_updated", f"Changed {', '.join(details)}", actor, {"fields": details}
        )
    if changed:
        await RC.event(db, record, rtype, "record.updated", {"fields": changed})
    record.version += 1
    await db.flush()
    return (await _out(db, [record]))[0]


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(record_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> None:
    """Permanent (like leads, #18): the record, its timeline, tasks and links are removed."""
    v = await RC.get_visible(db, actor, record_id)
    if not v.access.delete:
        raise Forbidden("permission_denied")
    await _delete(db, actor, v)


async def _delete(db, actor, v: RC.Visible) -> None:
    rid = v.record.id
    await db.execute(
        CustomFieldUniqueValue.__table__.delete().where(
            CustomFieldUniqueValue.entity == v.rtype.entity, CustomFieldUniqueValue.record_id == rid
        )
    )
    await RC.event(db, v.record, v.rtype, "record.deleted")
    await db.delete(v.record)
    await db.flush()
    await audit(db, actor, "record.deleted", "record", rid, {"type": v.rtype.key})


class BulkIn(BaseModel):
    action: Literal["assign", "stage", "delete"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    owner_user_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None


class Skipped(BaseModel):
    id: uuid.UUID
    name: str
    reason: str


class BulkOut(BaseModel):
    done: int
    skipped: list[Skipped]


@router.post("/records/bulk", response_model=BulkOut)
async def bulk_records(body: BulkIn, db: CrmDb, actor: ActiveUser) -> BulkOut:
    """Same rules as one at a time; records that fail one are skipped and reported."""
    done, skipped = 0, []
    for rid in body.ids:
        try:
            v = await RC.get_visible(db, actor, rid)
        except NotFound:
            continue
        try:
            if body.action == "delete":
                if not v.access.delete:
                    raise Forbidden("permission_denied")
                await _delete(db, actor, v)
            else:
                if body.action == "assign":
                    patch = RecordPatch(version=v.record.version, owner_user_id=body.owner_user_id)
                else:
                    if body.stage_id is None:
                        raise Invalid("Choose a stage")
                    patch = RecordPatch(version=v.record.version, stage_id=body.stage_id)
                async with db.begin_nested():
                    await update_record(rid, patch, db, actor)
            done += 1
        except (Invalid, Forbidden, Conflict) as e:
            skipped.append(Skipped(id=rid, name=v.record.name, reason=e.detail))
    return BulkOut(done=done, skipped=skipped)


# ---------- timeline ----------
class RecordActivityOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    type_key: str
    actor_type: str
    actor_id: uuid.UUID | None
    actor_name: str | None = None
    occurred_at: datetime
    summary: str
    body: str | None
    data: dict


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


@router.get("/records/{record_id}/activities", response_model=list[RecordActivityOut])
async def record_timeline(
    record_id: uuid.UUID,
    db: CrmDb,
    actor: ActiveUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[RecordActivityOut]:
    v = await RC.get_visible(db, actor, record_id)
    rows = (
        await db.scalars(
            select(Activity)
            .where(Activity.record_id == v.record.id)
            .order_by(Activity.occurred_at.desc(), Activity.created_at.desc())
            .limit(limit)
        )
    ).all()
    actors = {a.actor_id for a in rows if a.actor_id}
    names = {}
    if actors:
        names = dict(
            (await db.execute(select(User.id, User.name).where(User.id.in_(actors)))).all()
        )
    out = []
    for a in rows:
        item = RecordActivityOut.model_validate(a)
        item.actor_name = names.get(a.actor_id)
        out.append(item)
    return out


@router.post(
    "/records/{record_id}/notes",
    response_model=RecordActivityOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_note(record_id: uuid.UUID, body: NoteIn, db: CrmDb, actor: ActiveUser):
    v = await RC.get_visible(db, actor, record_id)
    if not v.access.edit:
        raise Forbidden("permission_denied")
    text_ = body.body.strip()
    if not text_:
        raise Invalid("Write the note")
    activity = await RC.log(db, v.record, "note", text_.splitlines()[0][:120], actor, body=text_)
    item = RecordActivityOut.model_validate(activity)
    item.actor_name = actor.user.name
    return item


# ---------- links ----------
class LinkEnd(BaseModel):
    kind: str
    id: uuid.UUID
    name: str
    type_key: str | None


class LinkOut(BaseModel):
    id: uuid.UUID
    link_type_id: uuid.UUID
    label: str
    direction: Literal["out", "in"]
    other: LinkEnd
    created_at: datetime


class LinkIn(BaseModel):
    link_type_id: uuid.UUID
    from_lead_id: uuid.UUID | None = None
    from_record_id: uuid.UUID | None = None
    to_lead_id: uuid.UUID | None = None
    to_record_id: uuid.UUID | None = None


def _link_out(view: RC.LinkView) -> LinkOut:
    o = view.other
    return LinkOut(
        id=view.link.id,
        link_type_id=view.link_type.id,
        label=view.label,
        direction="out" if _is_from(view) else "in",
        other=LinkEnd(kind=o.kind, id=o.id, name=o.name, type_key=o.type_key),
        created_at=view.link.created_at,
    )


def _is_from(view: RC.LinkView) -> bool:
    """True when this end is the link's "from" side (the other end is its "to")."""
    o = view.other
    return (o.kind == "lead" and view.link.to_lead_id == o.id) or (
        o.kind == "record" and view.link.to_record_id == o.id
    )


@router.get("/links", response_model=list[LinkOut])
async def list_links(
    db: CrmDb,
    actor: ActiveUser,
    lead_id: uuid.UUID | None = None,
    record_id: uuid.UUID | None = None,
) -> list[LinkOut]:
    """Everything linked to one lead or record (only what you may see)."""
    end, _ = await RC.resolve(db, actor, lead_id, record_id)
    return [_link_out(v) for v in await RC.links_of(db, actor, end)]


@router.post("/links", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
async def create_link(body: LinkIn, db: CrmDb, actor: ActiveUser) -> LinkOut:
    link_type = await db.get(LinkType, body.link_type_id)
    if link_type is None:
        raise NotFound("Link type not found")
    src, src_edit = await RC.resolve(db, actor, body.from_lead_id, body.from_record_id)
    dst, dst_edit = await RC.resolve(db, actor, body.to_lead_id, body.to_record_id)
    if not (src_edit or dst_edit):
        raise Forbidden("permission_denied")
    link = await RC.create_link(db, actor, link_type, src, dst)
    return _link_out(RC.LinkView(link, link_type, link_type.label, dst))


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(link_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> None:
    link = await db.get(Link, link_id)
    if link is None:
        raise NotFound("Link not found")
    await RC.delete_link(db, actor, link)

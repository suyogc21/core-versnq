"""Step 4: tags, saved views, scoring rules and score breakdowns, formula checks."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from app.core.errors import Conflict, Forbidden, Invalid
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import calc
from app.modules.crm import conditions as C
from app.modules.crm import deals as D
from app.modules.crm import leads as L
from app.modules.crm import scoring as S
from app.modules.crm import tags as T
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import ActivityType, SavedView, ScoreRule, Tag, Tagging
from app.modules.crm.setup_router import HEX, OrderIn, _get, _next_position, _reorder
from app.modules.settings.models import TenantSettings
from app.modules.teams.models import TeamMember

router = APIRouter(prefix="/api/v1", tags=["organise"], dependencies=CRM)
Configurer = Annotated[CurrentUser, require("crm.configure")]


# ---------- tags ----------
class TagOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    colour: str | None
    uses: int = 0


class TagPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    colour: str | None = Field(default=None, pattern=HEX)


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    colour: str | None = Field(default=None, pattern=HEX)


class SetTags(BaseModel):
    tag_ids: list[uuid.UUID] = Field(default=[], max_length=T.MAX_PER_SUBJECT)
    new: list[str] = Field(default=[], max_length=10)  # names of tags to create


@router.get("/tags", response_model=list[TagOut])
async def list_tags(db: CrmDb, _: ActiveUser) -> list[TagOut]:
    uses = dict(
        (await db.execute(select(Tagging.tag_id, func.count()).group_by(Tagging.tag_id))).all()
    )
    rows = (await db.scalars(select(Tag).order_by(func.lower(Tag.name)))).all()
    return [TagOut.model_validate(t).model_copy(update={"uses": uses.get(t.id, 0)}) for t in rows]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(body: TagIn, db: CrmDb, actor: ActiveUser) -> TagOut:
    if not (L.can(actor, "leads.edit") or L.can(actor, "deals.edit")):
        raise Forbidden("permission_denied")
    name = " ".join(body.name.split())
    if await db.scalar(select(Tag.id).where(func.lower(Tag.name) == name.lower())):
        raise Conflict(f"There is already a tag called {name}")
    (tag,) = await T.resolve(db, actor.user.tenant_id, [], [name])
    if body.colour:
        tag.colour = body.colour
    return TagOut.model_validate(tag)


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(tag_id: uuid.UUID, body: TagPatch, db: CrmDb, actor: Configurer) -> TagOut:
    tag = await _get(db, Tag, tag_id, "Tag")
    if body.name is not None:
        name = " ".join(body.name.split())
        clash = await db.scalar(
            select(Tag.id).where(func.lower(Tag.name) == name.lower(), Tag.id != tag.id)
        )
        if clash:
            raise Conflict(f"There is already a tag called {name}. Merge them instead")
        tag.name = name
    if body.colour is not None:
        tag.colour = body.colour
    await audit(db, actor, "tag.updated", "tag", tag.id, None, body.model_dump(exclude_unset=True))
    await db.flush()
    await db.refresh(tag)
    return TagOut.model_validate(tag)


@router.post("/tags/{tag_id}/merge", response_model=TagOut)
async def merge_tag(tag_id: uuid.UUID, db: CrmDb, actor: Configurer, into: uuid.UUID) -> TagOut:
    """Everything tagged with this tag gets `into` instead; this tag is deleted."""
    tag = await _get(db, Tag, tag_id, "Tag")
    target = await _get(db, Tag, into, "Tag")
    if tag.id == target.id:
        raise Invalid("Choose another tag to merge into")
    for col in (Tagging.lead_id, Tagging.deal_id):
        already = select(col).where(Tagging.tag_id == target.id, col.is_not(None))
        await db.execute(
            update(Tagging)
            .where(Tagging.tag_id == tag.id, col.is_not(None), col.not_in(already))
            .values(tag_id=target.id)
        )
    await db.delete(tag)
    await audit(
        db, actor, "tag.merged", "tag", target.id, {"from": tag.name}, {"into": target.name}
    )
    await db.flush()
    return next(t for t in await list_tags(db, actor) if t.id == target.id)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    """Removes the tag from every lead and deal."""
    tag = await _get(db, Tag, tag_id, "Tag")
    await db.delete(tag)
    await audit(db, actor, "tag.deleted", "tag", tag_id, {"name": tag.name})


@router.put("/leads/{lead_id}/tags", response_model=list[TagOut])
async def set_lead_tags(lead_id: uuid.UUID, body: SetTags, db: CrmDb, actor: ActiveUser):
    if not L.can(actor, "leads.edit"):
        raise Forbidden("permission_denied")
    lead = await L.get_visible(db, actor, lead_id)
    tags = await T.resolve(db, actor.user.tenant_id, body.tag_ids, body.new)
    await T.set_exact(db, actor, lead, tags)
    return [TagOut.model_validate(t) for t in (await T.of(db, lead_ids=[lead.id])).get(lead.id, [])]


@router.put("/deals/{deal_id}/tags", response_model=list[TagOut])
async def set_deal_tags(deal_id: uuid.UUID, body: SetTags, db: CrmDb, actor: ActiveUser):
    deal = await D.get_visible(db, actor, deal_id)
    D.require(actor, "deals.edit")
    tags = await T.resolve(db, actor.user.tenant_id, body.tag_ids, body.new)
    await T.set_exact(db, actor, deal, tags)
    return [TagOut.model_validate(t) for t in (await T.of(db, deal_ids=[deal.id])).get(deal.id, [])]


# ---------- saved views ----------
Entity = Literal["leads", "deals"]
Sharing = Literal["private", "team", "everyone"]


class ViewOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    entity: str
    name: str
    filters: dict
    sort: str | None
    direction: str | None
    columns: list | None
    sharing: str
    team_id: uuid.UUID | None
    owner_user_id: uuid.UUID
    position: int
    mine: bool = False


class ViewIn(BaseModel):
    entity: Entity
    name: str = Field(min_length=1, max_length=80)
    filters: dict = {}
    sort: str | None = Field(default=None, max_length=30)
    direction: Literal["asc", "desc"] | None = None
    columns: list[str] | None = Field(default=None, max_length=60)
    sharing: Sharing = "private"
    team_id: uuid.UUID | None = None


class ViewPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    filters: dict | None = None
    sort: str | None = Field(default=None, max_length=30)
    direction: Literal["asc", "desc"] | None = None
    columns: list[str] | None = Field(default=None, max_length=60)
    sharing: Sharing | None = None
    team_id: uuid.UUID | None = None


def _check_filters(entity: str, filters: dict) -> dict:
    """A view stores list filters; they are checked the same way the list checks them."""
    if len(str(filters)) > 5000:
        raise Invalid("Too many filters")
    if entity == "leads":
        from app.modules.crm.lead_query import LeadFilter

        try:
            return LeadFilter.model_validate(filters).model_dump(mode="json", exclude_defaults=True)
        except ValueError:
            raise Invalid("These filters are not valid") from None
    allowed = {
        "pipeline_id",
        "stage_id",
        "status",
        "owner",
        "q",
        "cf",
        "tag",
        "close_from",
        "close_to",
    }
    unknown = set(filters) - allowed
    if unknown:
        raise Invalid(f"Unknown filter: {sorted(unknown)[0]}")
    return filters


async def _managed_teams(db, actor: CurrentUser) -> set[uuid.UUID]:
    return set(
        (
            await db.scalars(
                select(TeamMember.team_id).where(
                    TeamMember.user_id == actor.user.id, TeamMember.is_manager.is_(True)
                )
            )
        ).all()
    )


async def _check_sharing(db, actor: CurrentUser, sharing: str, team_id) -> uuid.UUID | None:
    if sharing == "private":
        return None
    if sharing == "everyone":
        if not L.can(actor, "crm.configure"):
            raise Forbidden("Only admins share views with everyone")
        return None
    if team_id is None or team_id not in await _managed_teams(db, actor):
        if not (L.can(actor, "crm.configure") and team_id is not None):
            raise Forbidden("Share with a team you manage")
    return team_id


def _visible_views(actor: CurrentUser, my_teams):
    return or_(
        SavedView.owner_user_id == actor.user.id,
        SavedView.sharing == "everyone",
        (SavedView.sharing == "team") & SavedView.team_id.in_(my_teams),
    )


async def _my_teams(db, actor):
    return select(TeamMember.team_id).where(TeamMember.user_id == actor.user.id)


@router.get("/views", response_model=list[ViewOut])
async def list_views(db: CrmDb, actor: ActiveUser, entity: Entity) -> list[ViewOut]:
    rows = (
        await db.scalars(
            select(SavedView)
            .where(SavedView.entity == entity, _visible_views(actor, await _my_teams(db, actor)))
            .order_by(SavedView.position, SavedView.created_at)
        )
    ).all()
    return [
        ViewOut.model_validate(v).model_copy(update={"mine": v.owner_user_id == actor.user.id})
        for v in rows
    ]


@router.post("/views", response_model=ViewOut, status_code=status.HTTP_201_CREATED)
async def create_view(body: ViewIn, db: CrmDb, actor: ActiveUser) -> ViewOut:
    view = SavedView(
        tenant_id=actor.user.tenant_id,
        entity=body.entity,
        name=body.name.strip(),
        filters=_check_filters(body.entity, body.filters),
        sort=body.sort,
        direction=body.direction,
        columns=body.columns,
        sharing=body.sharing,
        team_id=await _check_sharing(db, actor, body.sharing, body.team_id),
        owner_user_id=actor.user.id,
        position=await _next_position(db, SavedView, SavedView.entity == body.entity),
    )
    db.add(view)
    await db.flush()
    await db.refresh(view)
    return ViewOut.model_validate(view).model_copy(update={"mine": True})


async def _own_view(db, actor: CurrentUser, view_id: uuid.UUID) -> SavedView:
    view = await _get(db, SavedView, view_id, "View")
    if view.owner_user_id != actor.user.id and not L.can(actor, "crm.configure"):
        raise Forbidden("Only the person who made this view can change it")
    return view


@router.patch("/views/{view_id}", response_model=ViewOut)
async def update_view(view_id: uuid.UUID, body: ViewPatch, db: CrmDb, actor: ActiveUser):
    view = await _own_view(db, actor, view_id)
    changes = body.model_dump(exclude_unset=True)
    if "filters" in changes:
        changes["filters"] = _check_filters(view.entity, changes["filters"] or {})
    if "sharing" in changes:
        changes["team_id"] = await _check_sharing(
            db, actor, changes["sharing"], changes.get("team_id", view.team_id)
        )
    for k, v in changes.items():
        setattr(view, k, v.strip() if isinstance(v, str) and k == "name" else v)
    await db.flush()
    await db.refresh(view)
    return ViewOut.model_validate(view).model_copy(
        update={"mine": view.owner_user_id == actor.user.id}
    )


@router.delete("/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_view(view_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> None:
    await db.delete(await _own_view(db, actor, view_id))


@router.put("/views/order", response_model=list[ViewOut])
async def order_views(body: OrderIn, db: CrmDb, actor: ActiveUser, entity: Entity):
    """Order your own views (shared ones keep their place)."""
    await _reorder(
        db,
        SavedView,
        body.ids,
        SavedView.entity == entity,
        SavedView.owner_user_id == actor.user.id,
    )
    return await list_views(db, actor, entity)


# ---------- scoring ----------
class ScoreRuleOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    kind: str
    condition: dict | None
    activity_type_key: str | None
    disposition: str | None
    points: int
    is_active: bool
    position: int


class ScoreRuleIn(BaseModel):
    kind: Literal["fit", "engagement"]
    condition: dict | None = None
    activity_type_key: str | None = Field(default=None, max_length=60)
    disposition: str | None = Field(default=None, max_length=100)
    points: int = Field(ge=-1000, le=1000)


class ScoreRulePatch(BaseModel):
    condition: dict | None = None
    activity_type_key: str | None = Field(default=None, max_length=60)
    disposition: str | None = Field(default=None, max_length=100)
    points: int | None = Field(default=None, ge=-1000, le=1000)
    is_active: bool | None = None


class ScoreSettings(BaseModel):
    engagement_days: int = Field(ge=1, le=365)
    hot_score: int = Field(ge=-100000, le=100000)
    warm_score: int = Field(ge=-100000, le=100000)


async def _rescore_soon(actor: CurrentUser) -> None:
    """Every lead is re-scored by the worker after rules change."""
    from app.workers.queue import enqueue

    await enqueue("rescore_job", str(actor.user.tenant_id))


async def _clean_rule(db, kind: str, condition, type_key, disposition) -> dict:
    if kind == "fit":
        if condition is None:
            raise Invalid("A fit rule needs a condition")
        return {"condition": await C.check(db, "lead", condition, for_fit=True),
                "activity_type_key": None, "disposition": None}  # fmt: skip
    kind_row = await db.scalar(select(ActivityType).where(ActivityType.key == (type_key or "")))
    if kind_row is None:
        raise Invalid("Choose an activity type")
    return {
        "condition": None,
        "activity_type_key": kind_row.key,
        "disposition": disposition or None,
    }


@router.get("/score-rules", response_model=list[ScoreRuleOut])
async def list_score_rules(db: CrmDb, _: ActiveUser) -> list[ScoreRule]:
    return list((await db.scalars(select(ScoreRule).order_by(ScoreRule.position))).all())


@router.post("/score-rules", response_model=ScoreRuleOut, status_code=status.HTTP_201_CREATED)
async def create_score_rule(body: ScoreRuleIn, db: CrmDb, actor: Configurer) -> ScoreRule:
    clean = await _clean_rule(
        db, body.kind, body.condition, body.activity_type_key, body.disposition
    )
    rule = ScoreRule(
        tenant_id=actor.user.tenant_id,
        kind=body.kind,
        points=body.points,
        position=await _next_position(db, ScoreRule),
        **clean,
    )
    db.add(rule)
    await db.flush()
    await audit(db, actor, "score_rule.created", "score_rule", rule.id, None, body.model_dump())
    await _rescore_soon(actor)
    await db.refresh(rule)
    return rule


@router.patch("/score-rules/{rule_id}", response_model=ScoreRuleOut)
async def update_score_rule(
    rule_id: uuid.UUID, body: ScoreRulePatch, db: CrmDb, actor: Configurer
) -> ScoreRule:
    rule = await _get(db, ScoreRule, rule_id, "Rule")
    changes = body.model_dump(exclude_unset=True)
    if {"condition", "activity_type_key", "disposition"} & set(changes):
        clean = await _clean_rule(
            db,
            rule.kind,
            changes.get("condition", rule.condition),
            changes.get("activity_type_key", rule.activity_type_key),
            changes.get("disposition", rule.disposition),
        )
        changes |= clean
    for k, v in changes.items():
        setattr(rule, k, v)
    await audit(
        db,
        actor,
        "score_rule.updated",
        "score_rule",
        rule.id,
        None,
        body.model_dump(exclude_unset=True),
    )
    await _rescore_soon(actor)
    await db.flush()
    await db.refresh(rule)
    return rule


@router.delete("/score-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_score_rule(rule_id: uuid.UUID, db: CrmDb, actor: Configurer) -> None:
    rule = await _get(db, ScoreRule, rule_id, "Rule")
    await db.delete(rule)
    await audit(db, actor, "score_rule.deleted", "score_rule", rule_id)
    await _rescore_soon(actor)


@router.put("/score-rules/order", response_model=list[ScoreRuleOut])
async def order_score_rules(body: OrderIn, db: CrmDb, actor: Configurer):
    await _reorder(db, ScoreRule, body.ids)
    return await list_score_rules(db, actor)


@router.get("/score-settings", response_model=ScoreSettings)
async def get_score_settings(db: CrmDb, actor: ActiveUser) -> ScoreSettings:
    s = await db.get(TenantSettings, actor.user.tenant_id)
    return ScoreSettings(
        engagement_days=s.engagement_days, hot_score=s.hot_score, warm_score=s.warm_score
    )


@router.put("/score-settings", response_model=ScoreSettings)
async def set_score_settings(body: ScoreSettings, db: CrmDb, actor: Configurer) -> ScoreSettings:
    if body.warm_score > body.hot_score:
        raise Invalid("Warm must be lower than hot")
    s = await db.get(TenantSettings, actor.user.tenant_id)
    before = await get_score_settings(db, actor)
    s.engagement_days, s.hot_score, s.warm_score = (
        body.engagement_days,
        body.hot_score,
        body.warm_score,
    )
    await audit(
        db,
        actor,
        "score_settings.updated",
        "settings",
        s.tenant_id,
        before.model_dump(),
        body.model_dump(),
    )
    await _rescore_soon(actor)
    return body


class ScoreLine(BaseModel):
    kind: str
    rule_id: str
    points: int
    times: int
    label: str


class ScoreOut(BaseModel):
    score: int
    fit: int
    engagement: int
    band: str
    lines: list[ScoreLine]


@router.get("/leads/{lead_id}/score", response_model=ScoreOut)
async def lead_score(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> ScoreOut:
    lead = await L.get_visible(db, actor, lead_id)
    s = await db.get(TenantSettings, actor.user.tenant_id)
    b = await S.compute(db, lead, settings=s)
    rules = {str(r.id): r for r in await list_score_rules(db, actor)}
    kinds = {t.key: t for t in (await db.scalars(select(ActivityType))).all()}
    types = {k: t.label for k, t in kinds.items()}

    def outcome(type_key: str, value: str) -> str:
        for f in kinds[type_key].fields if type_key in kinds else []:
            if f.get("key") == "disposition":
                return next(
                    (o["label"] for o in f.get("options", []) if o["value"] == value), value
                )
        return value

    lines = []
    for line in b.lines:
        r = rules[line["rule_id"]]
        if r.kind == "fit":
            label = await _describe(db, r.condition)
        else:
            label = types.get(r.activity_type_key, r.activity_type_key)
            if r.disposition:
                label += f": {outcome(r.activity_type_key, r.disposition)}"
            label += f" × {line['times']}"
        lines.append(ScoreLine(**line, label=label))
    return ScoreOut(
        score=b.total, fit=b.fit, engagement=b.engagement, band=S.band(b.total, s), lines=lines
    )


FIELD_NAMES = {
    "source_id": "Source", "stage_id": "Stage", "owner_user_id": "Owner", "tags": "Tags",
    "city": "City", "region": "Region", "country_code": "Country", "kind": "Type",
    "preferred_language": "Language", "campaign": "Campaign", "utm_source": "UTM source",
}  # fmt: skip
OP_WORDS = {
    "is": "is", "is_not": "is not", "any_of": "is any of", "none_of": "is none of",
    "contains": "contains", "empty": "is empty", "not_empty": "is not empty",
    "gt": "is more than", "lt": "is less than",
}  # fmt: skip


async def _describe(db, cond: dict) -> str:
    """'Source is Website' rather than ids."""
    from app.modules.crm.models import LeadSource, LeadStage
    from app.modules.users.models import User

    field, value = cond["field"], cond.get("value")
    defs = await L.lead_fields(db, "lead")
    name = defs[field].label if field in defs else FIELD_NAMES.get(field, field.replace("_", " "))
    model = {"source_id": LeadSource, "stage_id": LeadStage, "owner_user_id": User, "tags": Tag}
    values = value if isinstance(value, list) else ([value] if value is not None else [])
    shown = []
    for v in values:
        text = str(v)
        if field in model:
            try:
                row = await db.get(model[field], uuid.UUID(text))
                text = getattr(row, "name", text) if row else text
            except ValueError:
                pass
        elif field in defs and defs[field].options:
            text = next((o["label"] for o in defs[field].options if o["value"] == text), text)
        shown.append(text)
    return f"{name} {OP_WORDS.get(cond['op'], cond['op'])} {', '.join(shown)}".strip()


# ---------- formulas ----------
class FormulaIn(BaseModel):
    entity: str = Field(max_length=50)
    key: str = Field(default="new_field", max_length=60)
    formula: str = Field(max_length=500)


class FormulaOut(BaseModel):
    ok: bool
    error: str | None = None
    fields: dict[str, str]


@router.post("/formula/check", response_model=FormulaOut)
async def check_formula(body: FormulaIn, db: CrmDb, _: Configurer) -> FormulaOut:
    """Is this formula valid here? Lists the fields a formula may use."""
    defs = await L.lead_fields(db, body.entity)
    fields = calc.input_types(defs, body.entity, skip=body.key)
    try:
        calc.check_formula(defs, body.entity, body.key, body.formula)
        return FormulaOut(ok=True, fields=fields)
    except Invalid as e:
        return FormulaOut(ok=False, error=e.detail, fields=fields)

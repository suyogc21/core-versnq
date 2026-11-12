"""Key accounts endpoints (step 7b, Decision log #36). Behind the `key_accounts` module switch
(404 when off) and the CRM switch."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import Conflict, Invalid, NotFound
from app.core.modules import require_module
from app.core.money import check_amount
from app.core.money import currency as check_currency
from app.modules.accounts import service as A
from app.modules.accounts.models import (
    AccountCell,
    AccountContact,
    AccountGoal,
    AccountUnit,
    Competitor,
    KeyAccount,
)
from app.modules.auth.deps import ActiveUser
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.models import Deal, Lead, Product, Task
from app.modules.users.models import User

router = APIRouter(
    prefix="/api/v1", tags=["key accounts"], dependencies=[*CRM, require_module("key_accounts")]
)

Tier = Literal["strategic", "growth", "maintain"]
Health = Literal["on_track", "at_risk", "off_track"]


# ---------- schemas ----------
class Amount(BaseModel):
    currency: str
    minor: int


class Rollup(BaseModel):
    won_this_year: list[Amount]
    pipeline: list[Amount]
    open_deals: int
    collected_this_year: list[Amount]
    overdue: list[Amount]
    lost_last_90_days: int
    last_touch: datetime | None


class AccountRow(BaseModel):
    id: uuid.UUID
    org_lead_id: uuid.UUID
    name: str
    industry: str | None
    tier: str
    owner_user_id: uuid.UUID | None
    owner_name: str | None
    parent_id: uuid.UUID | None
    parent_name: str | None
    target_minor: int | None
    target_currency: str | None
    health: str
    health_note: str | None
    version: int
    can_edit: bool
    rollup: Rollup
    hints: list[str]


class AccountIn(BaseModel):
    org_lead_id: uuid.UUID
    tier: Tier = "growth"
    owner_user_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    target_minor: int | None = Field(default=None, ge=0)
    target_currency: str | None = Field(default=None, min_length=3, max_length=3)


class AccountPatch(BaseModel):
    version: int
    tier: Tier | None = None
    owner_user_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    no_parent: bool = False
    target_minor: int | None = Field(default=None, ge=0)
    target_currency: str | None = Field(default=None, min_length=3, max_length=3)
    no_target: bool = False
    health: Health | None = None
    health_note: str | None = Field(default=None, max_length=500)


class UnitOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    budget_holder_lead_id: uuid.UUID | None
    budget_holder_name: str | None = None
    budget_minor: int | None
    budget_currency: str | None
    position: int


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    budget_holder_lead_id: uuid.UUID | None = None
    budget_minor: int | None = Field(default=None, ge=0)
    budget_currency: str | None = Field(default=None, min_length=3, max_length=3)


class GoalOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    title: str
    target_minor: int | None
    currency: str | None
    due_on: date | None
    status: str
    position: int


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    target_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    due_on: date | None = None
    status: Literal["open", "done", "missed"] = "open"


class TaskRef(BaseModel):
    id: uuid.UUID
    title: str
    due_at: datetime
    owner_name: str | None


class TreeNode(BaseModel):
    id: uuid.UUID
    name: str
    tier: str
    health: str
    parent_id: uuid.UUID | None
    rollup: Rollup


class AccountDetail(AccountRow):
    group: Rollup  # this account and everything below it
    units: list[UnitOut]
    goals: list[GoalOut]
    actions: list[TaskRef]
    tree: list[TreeNode]  # the whole group, from its top


class DealRef(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    amount_minor: int
    currency: str


class CellOut(BaseModel):
    unit_id: uuid.UUID
    product_id: uuid.UUID
    state: str  # won / open / lost / competitor / not_fit / empty
    deals: list[DealRef]
    competitor_id: uuid.UUID | None
    note: str | None


class ProductRef(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None


class GridOut(BaseModel):
    units: list[UnitOut]
    products: list[ProductRef]
    cells: list[CellOut]


class CellIn(BaseModel):
    status: Literal["competitor", "not_fit"] | None
    competitor_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)


class PersonOut(BaseModel):
    lead_id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    on_map: bool
    unit_id: uuid.UUID | None
    role: str | None
    stance: str | None
    strength: int | None
    note: str | None
    last_touch: datetime | None


class PersonIn(BaseModel):
    unit_id: uuid.UUID | None = None
    role: Literal["decision_maker", "influencer", "user", "gatekeeper"] = "influencer"
    stance: Literal["champion", "supporter", "neutral", "blocker"] = "neutral"
    strength: int = Field(default=3, ge=1, le=5)
    note: str | None = Field(default=None, max_length=300)


class CompetitorOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    website: str | None
    is_active: bool


class CompetitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    website: str | None = Field(default=None, max_length=300)
    is_active: bool = True


class StartDealIn(BaseModel):
    unit_id: uuid.UUID
    product_id: uuid.UUID


class DealUnitIn(BaseModel):
    unit_id: uuid.UUID | None


# ---------- helpers ----------
def _target(minor: int | None, cur: str | None) -> tuple[int | None, str | None]:
    if minor is None and cur is None:
        return None, None
    if minor is None or cur is None:
        raise Invalid("Give both the target amount and its currency")
    return check_amount(minor, "Target"), check_currency(cur)


async def _row(db, actor, acc: KeyAccount, org: Lead) -> AccountRow:
    owner = await db.get(User, acc.owner_user_id) if acc.owner_user_id else None
    parent_name = None
    if acc.parent_id:
        parent_name = await db.scalar(
            select(Lead.display_name)
            .join(KeyAccount, KeyAccount.org_lead_id == Lead.id)
            .where(KeyAccount.id == acc.parent_id)
        )
    r = await A.rollup(db, [acc.id])
    return AccountRow(
        id=acc.id,
        org_lead_id=org.id,
        name=org.display_name,
        industry=org.industry,
        tier=acc.tier,
        owner_user_id=acc.owner_user_id,
        owner_name=owner.name if owner else None,
        parent_id=acc.parent_id,
        parent_name=parent_name,
        target_minor=acc.target_minor,
        target_currency=acc.target_currency,
        health=acc.health,
        health_note=acc.health_note,
        version=acc.version,
        can_edit=A.can_edit(actor, acc),
        rollup=Rollup(**r),
        hints=A.hints(r),
    )


async def _detail(db, actor, acc: KeyAccount, org: Lead) -> AccountDetail:
    row = await _row(db, actor, acc, org)
    units = await _units(db, acc)
    goals = (
        await db.scalars(
            select(AccountGoal)
            .where(AccountGoal.account_id == acc.id)
            .order_by(AccountGoal.position)
        )
    ).all()
    tasks = (
        await db.execute(
            select(Task, User.name)
            .outerjoin(User, User.id == Task.owner_user_id)
            .where(Task.lead_id == org.id, Task.status == "open")
            .order_by(Task.due_at)
            .limit(20)
        )
    ).all()
    top = await A.top_of(db, acc.id)
    members = await A.subtree(db, top)
    nodes = (
        await db.execute(
            select(KeyAccount, Lead)
            .join(Lead, Lead.id == KeyAccount.org_lead_id)
            .where(KeyAccount.id.in_(members), await A.visible(db, actor))
        )
    ).all()
    tree = [
        TreeNode(
            id=k.id,
            name=ld.display_name,
            tier=k.tier,
            health=k.health,
            parent_id=k.parent_id,
            rollup=Rollup(**await A.rollup(db, await A.subtree(db, k.id))),
        )
        for k, ld in nodes
    ]
    return AccountDetail(
        **row.model_dump(),
        group=Rollup(**await A.rollup(db, await A.subtree(db, acc.id))),
        units=units,
        goals=[GoalOut.model_validate(g) for g in goals],
        actions=[TaskRef(id=t.id, title=t.title, due_at=t.due_at, owner_name=n) for t, n in tasks],
        tree=tree,
    )


async def _units(db, acc: KeyAccount) -> list[UnitOut]:
    units = (
        await db.scalars(
            select(AccountUnit)
            .where(AccountUnit.account_id == acc.id)
            .order_by(AccountUnit.position)
        )
    ).all()
    holders = dict(
        (
            await db.execute(
                select(Lead.id, Lead.display_name).where(
                    Lead.id.in_({u.budget_holder_lead_id for u in units} - {None})
                )
            )
        ).all()
    )
    return [
        UnitOut.model_validate(u).model_copy(
            update={"budget_holder_name": holders.get(u.budget_holder_lead_id)}
        )
        for u in units
    ]


async def _editable(db, actor, account_id: uuid.UUID) -> tuple[KeyAccount, Lead]:
    acc, org = await A.get_visible(db, actor, account_id)
    A.need_edit(actor, acc)
    return acc, org


def _version(acc: KeyAccount, version: int) -> None:
    if acc.version != version:
        raise Conflict("Someone else changed this account. Reload and try again.")


# ---------- accounts ----------
@router.get("/key-accounts", response_model=list[AccountRow])
async def list_accounts(
    db: CrmDb,
    actor: ActiveUser,
    q: str | None = None,
    tier: Tier | None = None,
    health: Health | None = None,
    mine: bool = False,
):
    where = [await A.visible(db, actor)]
    if q and q.strip():
        where.append(Lead.display_name.ilike(f"%{q.strip()}%"))
    if tier:
        where.append(KeyAccount.tier == tier)
    if health:
        where.append(KeyAccount.health == health)
    if mine:
        where.append(KeyAccount.owner_user_id == actor.user.id)
    rows = (
        await db.execute(
            select(KeyAccount, Lead)
            .join(Lead, Lead.id == KeyAccount.org_lead_id)
            .where(*where)
            .order_by(KeyAccount.tier, Lead.display_name)
            .limit(500)
        )
    ).all()
    return [await _row(db, actor, k, ld) for k, ld in rows]


@router.post("/key-accounts", response_model=AccountDetail, status_code=status.HTTP_201_CREATED)
async def mark_account(body: AccountIn, db: CrmDb, actor: ActiveUser):
    A.need_manage(actor)
    org = await L.get_visible(db, actor, body.org_lead_id)
    if org.kind != "organisation":
        raise Invalid("Only an organisation can be a key account")
    await A.ensure_not_key(db, org.id)
    target, cur = _target(body.target_minor, body.target_currency)
    if body.owner_user_id and not await db.get(User, body.owner_user_id):
        raise Invalid("Choose a person from your team")
    acc = KeyAccount(
        tenant_id=actor.user.tenant_id,
        org_lead_id=org.id,
        tier=body.tier,
        owner_user_id=body.owner_user_id or org.owner_user_id or actor.user.id,
        target_minor=target,
        target_currency=cur,
        health="on_track",
    )
    db.add(acc)
    await db.flush()
    if body.parent_id:
        await A.check_parent(db, acc.id, body.parent_id)
        acc.parent_id = body.parent_id
    await db.flush()
    await A.changed(db, actor, acc, org, f"Marked as a key account ({body.tier})")
    await audit(db, actor, "key_account.created", "key_account", acc.id, after={"org": str(org.id)})
    return await _detail(db, actor, acc, org)


@router.get("/key-accounts/{account_id}", response_model=AccountDetail)
async def get_account(account_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    acc, org = await A.get_visible(db, actor, account_id)
    return await _detail(db, actor, acc, org)


@router.get("/leads/{lead_id}/key-account", response_model=AccountRow | None)
async def account_of_lead(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    row = (
        await db.execute(
            select(KeyAccount, Lead)
            .join(Lead, Lead.id == KeyAccount.org_lead_id)
            .where(KeyAccount.org_lead_id == lead_id, await A.visible(db, actor))
        )
    ).first()
    return await _row(db, actor, row[0], row[1]) if row else None


@router.patch("/key-accounts/{account_id}", response_model=AccountDetail)
async def update_account(account_id: uuid.UUID, body: AccountPatch, db: CrmDb, actor: ActiveUser):
    acc, org = await _editable(db, actor, account_id)
    _version(acc, body.version)
    changes = []
    if body.tier and body.tier != acc.tier:
        acc.tier = body.tier
        changes.append(f"tier {body.tier}")
    if body.owner_user_id and body.owner_user_id != acc.owner_user_id:
        A.need_manage(actor)  # only managers hand an account to someone else
        if not await db.get(User, body.owner_user_id):
            raise Invalid("Choose a person from your team")
        acc.owner_user_id = body.owner_user_id
        changes.append("owner changed")
    if body.no_parent and acc.parent_id:
        acc.parent_id = None
        changes.append("removed from its group")
    elif body.parent_id and body.parent_id != acc.parent_id:
        await A.check_parent(db, acc.id, body.parent_id)
        acc.parent_id = body.parent_id
        changes.append("moved in the group tree")
    if body.no_target:
        acc.target_minor = acc.target_currency = None
        changes.append("target removed")
    elif body.target_minor is not None or body.target_currency is not None:
        acc.target_minor, acc.target_currency = _target(
            body.target_minor if body.target_minor is not None else acc.target_minor,
            body.target_currency or acc.target_currency,
        )
        changes.append("target set")
    if body.health and body.health != acc.health:
        acc.health = body.health
        changes.append(f"health {body.health.replace('_', ' ')}")
    if body.health_note is not None:
        acc.health_note = body.health_note.strip() or None
    acc.version += 1
    await db.flush()
    if changes:
        await A.changed(db, actor, acc, org, "Key account: " + ", ".join(changes))
    return await _detail(db, actor, acc, org)


@router.delete("/key-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unmark_account(account_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    """The organisation and its deals stay; only the key-account plan goes."""
    A.need_manage(actor)
    acc, org = await A.get_visible(db, actor, account_id)
    for child in (await db.scalars(select(KeyAccount).where(KeyAccount.parent_id == acc.id))).all():
        child.parent_id = acc.parent_id
    await A.changed(db, actor, acc, org, "No longer a key account")
    await audit(db, actor, "key_account.deleted", "key_account", acc.id)
    await db.delete(acc)
    await db.flush()


# ---------- departments ----------
async def _check_unit(db, org: Lead, body: UnitIn) -> tuple:
    if body.budget_holder_lead_id:
        await A.check_contact(db, org, body.budget_holder_lead_id)
    if (body.budget_minor is None) != (body.budget_currency is None):
        raise Invalid("Give both the budget and its currency")
    cur = check_currency(body.budget_currency) if body.budget_currency else None
    return body.budget_minor, cur


@router.post(
    "/key-accounts/{account_id}/units",
    response_model=list[UnitOut],
    status_code=status.HTTP_201_CREATED,
)
async def add_unit(account_id: uuid.UUID, body: UnitIn, db: CrmDb, actor: ActiveUser):
    acc, org = await _editable(db, actor, account_id)
    budget, cur = await _check_unit(db, org, body)
    name = body.name.strip()
    if await db.scalar(
        select(AccountUnit.id).where(
            AccountUnit.account_id == acc.id, func.lower(AccountUnit.name) == name.lower()
        )
    ):
        raise Conflict("This department is already on the account")
    top = await db.scalar(
        select(func.coalesce(func.max(AccountUnit.position), -1)).where(
            AccountUnit.account_id == acc.id
        )
    )
    db.add(
        AccountUnit(
            tenant_id=acc.tenant_id,
            account_id=acc.id,
            name=name,
            budget_holder_lead_id=body.budget_holder_lead_id,
            budget_minor=budget,
            budget_currency=cur,
            position=top + 1,
        )
    )
    await db.flush()
    await A.changed(db, actor, acc, org, f"Department added: {name}")
    return await _units(db, acc)


@router.put("/key-accounts/{account_id}/units/{unit_id}", response_model=list[UnitOut])
async def update_unit(
    account_id: uuid.UUID, unit_id: uuid.UUID, body: UnitIn, db: CrmDb, actor: ActiveUser
):
    acc, org = await _editable(db, actor, account_id)
    unit = await A.unit_of(db, acc, unit_id)
    budget, cur = await _check_unit(db, org, body)
    unit.name, unit.budget_holder_lead_id = body.name.strip(), body.budget_holder_lead_id
    unit.budget_minor, unit.budget_currency = budget, cur
    await db.flush()
    return await _units(db, acc)


@router.delete("/key-accounts/{account_id}/units/{unit_id}", response_model=list[UnitOut])
async def remove_unit(account_id: uuid.UUID, unit_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    acc, org = await _editable(db, actor, account_id)
    unit = await A.unit_of(db, acc, unit_id)
    await db.delete(unit)  # its deals stay, just without a department
    await db.flush()
    await A.changed(db, actor, acc, org, f"Department removed: {unit.name}")
    return await _units(db, acc)


# ---------- the opportunity grid ----------
async def _products(db) -> list[Product]:
    return list(
        (
            await db.scalars(
                select(Product).where(Product.is_active.is_(True)).order_by(Product.name)
            )
        ).all()
    )


@router.get("/key-accounts/{account_id}/grid", response_model=GridOut)
async def get_grid(account_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    acc, _ = await A.get_visible(db, actor, account_id)
    products = await _products(db)
    g = await A.grid(db, acc, products)
    return GridOut(
        units=await _units(db, acc),
        products=[ProductRef(id=p.id, name=p.name, code=p.code) for p in products],
        cells=[CellOut(**c) for c in g["cells"]],
    )


@router.put("/key-accounts/{account_id}/grid/{unit_id}/{product_id}", response_model=GridOut)
async def set_cell(
    account_id: uuid.UUID,
    unit_id: uuid.UUID,
    product_id: uuid.UUID,
    body: CellIn,
    db: CrmDb,
    actor: ActiveUser,
):
    acc, org = await _editable(db, actor, account_id)
    unit = await A.unit_of(db, acc, unit_id)
    product = await db.get(Product, product_id)
    if product is None:
        raise NotFound("Product not found")
    cell = await db.scalar(
        select(AccountCell).where(
            AccountCell.unit_id == unit.id, AccountCell.product_id == product.id
        )
    )
    if body.status is None:
        if cell:
            await db.delete(cell)
    else:
        if body.competitor_id and not await db.get(Competitor, body.competitor_id):
            raise Invalid("Choose a competitor from your list")
        if body.status == "competitor" and not body.competitor_id:
            raise Invalid("Choose which competitor holds it")
        cell = cell or AccountCell(
            tenant_id=acc.tenant_id, account_id=acc.id, unit_id=unit.id, product_id=product.id
        )
        cell.status = body.status
        cell.competitor_id = body.competitor_id if body.status == "competitor" else None
        cell.note = (body.note or "").strip() or None
        db.add(cell)
    await db.flush()
    what = "cleared" if body.status is None else body.status.replace("_", " ")
    await A.changed(db, actor, acc, org, f"{unit.name} × {product.name}: {what}")
    return await get_grid(account_id, db, actor)


@router.post(
    "/key-accounts/{account_id}/grid/deal",
    response_model=GridOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_deal(account_id: uuid.UUID, body: StartDealIn, db: CrmDb, actor: ActiveUser):
    """A new deal for this department and product, straight from the grid."""
    from app.modules.crm.deals_router import DealIn, LineIn, create_deal

    acc, org = await _editable(db, actor, account_id)
    unit = await A.unit_of(db, acc, body.unit_id)
    product = await db.get(Product, body.product_id)
    if product is None:
        raise NotFound("Product not found")
    made = await create_deal(
        DealIn(
            lead_id=org.id,
            name=f"{org.display_name} — {unit.name} — {product.name}",
            lines=[LineIn(product_id=product.id)],
        ),
        db,
        actor,
    )
    deal = await db.get(Deal, made.id)
    deal.account_unit_id = unit.id
    await db.flush()
    return await get_grid(account_id, db, actor)


@router.put(
    "/key-accounts/{account_id}/deals/{deal_id}/unit", status_code=status.HTTP_204_NO_CONTENT
)
async def set_deal_unit(
    account_id: uuid.UUID, deal_id: uuid.UUID, body: DealUnitIn, db: CrmDb, actor: ActiveUser
):
    """Say which department a deal of this account is for (it then shows on the grid)."""
    acc, org = await _editable(db, actor, account_id)
    deal = await db.get(Deal, deal_id)
    if deal is None or deal.lead_id not in await A.lead_ids(db, [acc.id]):
        raise NotFound("Deal not found on this account")
    if body.unit_id:
        await A.unit_of(db, acc, body.unit_id)
    deal.account_unit_id = body.unit_id
    await db.flush()


@router.get("/key-accounts/{account_id}/deals", response_model=list[DealRef])
async def account_deals(account_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    acc, _ = await A.get_visible(db, actor, account_id)
    rows = (
        await db.scalars(
            select(Deal)
            .where(Deal.lead_id.in_(await A.lead_ids(db, [acc.id])))
            .order_by(Deal.created_at.desc())
        )
    ).all()
    return [
        DealRef(
            id=d.id, name=d.name, status=d.status, amount_minor=d.amount_minor, currency=d.currency
        )
        for d in rows
    ]


# ---------- people map ----------
async def _people_out(db, acc, org) -> list[PersonOut]:
    return [
        PersonOut(
            lead_id=ld.id,
            name=ld.display_name,
            email=ld.primary_email,
            phone=ld.primary_phone,
            on_map=c is not None,
            unit_id=c.unit_id if c else None,
            role=c.role if c else None,
            stance=c.stance if c else None,
            strength=c.strength if c else None,
            note=c.note if c else None,
            last_touch=ld.last_contacted_at or ld.last_activity_at,
        )
        for ld, c in await A.people(db, acc, org)
    ]


@router.get("/key-accounts/{account_id}/people", response_model=list[PersonOut])
async def get_people(account_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    acc, org = await A.get_visible(db, actor, account_id)
    return await _people_out(db, acc, org)


@router.put("/key-accounts/{account_id}/people/{lead_id}", response_model=list[PersonOut])
async def set_person(
    account_id: uuid.UUID, lead_id: uuid.UUID, body: PersonIn, db: CrmDb, actor: ActiveUser
):
    acc, org = await _editable(db, actor, account_id)
    person = await A.check_contact(db, org, lead_id)
    if body.unit_id:
        await A.unit_of(db, acc, body.unit_id)
    c = await db.scalar(
        select(AccountContact).where(
            AccountContact.account_id == acc.id, AccountContact.lead_id == person.id
        )
    )
    c = c or AccountContact(tenant_id=acc.tenant_id, account_id=acc.id, lead_id=person.id)
    c.unit_id, c.role, c.stance, c.strength = body.unit_id, body.role, body.stance, body.strength
    c.note = (body.note or "").strip() or None
    db.add(c)
    await db.flush()
    await A.changed(
        db, actor, acc, org, f"{person.display_name}: {body.role.replace('_', ' ')}, {body.stance}"
    )
    return await _people_out(db, acc, org)


@router.delete("/key-accounts/{account_id}/people/{lead_id}", response_model=list[PersonOut])
async def remove_person(account_id: uuid.UUID, lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    acc, org = await _editable(db, actor, account_id)
    c = await db.scalar(
        select(AccountContact).where(
            AccountContact.account_id == acc.id, AccountContact.lead_id == lead_id
        )
    )
    if c:
        await db.delete(c)
        await db.flush()
    return await _people_out(db, acc, org)


# ---------- account plan ----------
def _goal_values(body: GoalIn) -> tuple:
    if (body.target_minor is None) != (body.currency is None):
        raise Invalid("Give both the target amount and its currency")
    return body.target_minor, check_currency(body.currency) if body.currency else None


@router.post(
    "/key-accounts/{account_id}/goals",
    response_model=list[GoalOut],
    status_code=status.HTTP_201_CREATED,
)
async def add_goal(account_id: uuid.UUID, body: GoalIn, db: CrmDb, actor: ActiveUser):
    acc, org = await _editable(db, actor, account_id)
    target, cur = _goal_values(body)
    top = await db.scalar(
        select(func.coalesce(func.max(AccountGoal.position), -1)).where(
            AccountGoal.account_id == acc.id
        )
    )
    db.add(
        AccountGoal(
            tenant_id=acc.tenant_id,
            account_id=acc.id,
            title=body.title.strip(),
            target_minor=target,
            currency=cur,
            due_on=body.due_on,
            status=body.status,
            position=top + 1,
        )
    )
    await db.flush()
    await A.changed(db, actor, acc, org, f"Goal added: {body.title.strip()}")
    return await _goals(db, acc)


async def _goals(db, acc) -> list[GoalOut]:
    rows = (
        await db.scalars(
            select(AccountGoal)
            .where(AccountGoal.account_id == acc.id)
            .order_by(AccountGoal.position)
        )
    ).all()
    return [GoalOut.model_validate(g) for g in rows]


async def _goal(db, acc, goal_id) -> AccountGoal:
    g = await db.scalar(
        select(AccountGoal).where(AccountGoal.id == goal_id, AccountGoal.account_id == acc.id)
    )
    if g is None:
        raise NotFound("Goal not found")
    return g


@router.put("/key-accounts/{account_id}/goals/{goal_id}", response_model=list[GoalOut])
async def update_goal(
    account_id: uuid.UUID, goal_id: uuid.UUID, body: GoalIn, db: CrmDb, actor: ActiveUser
):
    acc, org = await _editable(db, actor, account_id)
    g = await _goal(db, acc, goal_id)
    target, cur = _goal_values(body)
    was = g.status
    g.title, g.target_minor, g.currency, g.due_on, g.status = (
        body.title.strip(),
        target,
        cur,
        body.due_on,
        body.status,
    )
    await db.flush()
    if was != body.status:
        await A.changed(db, actor, acc, org, f"Goal {body.status}: {g.title}")
    return await _goals(db, acc)


@router.delete("/key-accounts/{account_id}/goals/{goal_id}", response_model=list[GoalOut])
async def remove_goal(account_id: uuid.UUID, goal_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    acc, _ = await _editable(db, actor, account_id)
    await db.delete(await _goal(db, acc, goal_id))
    await db.flush()
    return await _goals(db, acc)


# ---------- competitors ----------
@router.get("/competitors", response_model=list[CompetitorOut])
async def list_competitors(db: CrmDb, actor: ActiveUser):
    return (await db.scalars(select(Competitor).order_by(Competitor.name))).all()


@router.post("/competitors", response_model=CompetitorOut, status_code=status.HTTP_201_CREATED)
async def add_competitor(body: CompetitorIn, db: CrmDb, actor: ActiveUser):
    A.need_manage(actor)
    name = body.name.strip()
    if await db.scalar(select(Competitor.id).where(func.lower(Competitor.name) == name.lower())):
        raise Conflict("This competitor is already on the list")
    c = Competitor(
        tenant_id=actor.user.tenant_id, name=name, website=body.website, is_active=body.is_active
    )
    db.add(c)
    await db.flush()
    await audit(db, actor, "competitor.created", "competitor", c.id, after={"name": name})
    return c


@router.put("/competitors/{competitor_id}", response_model=CompetitorOut)
async def update_competitor(
    competitor_id: uuid.UUID, body: CompetitorIn, db: CrmDb, actor: ActiveUser
):
    A.need_manage(actor)
    c = await db.get(Competitor, competitor_id)
    if c is None:
        raise NotFound("Competitor not found")
    c.name, c.website, c.is_active = body.name.strip(), body.website, body.is_active
    await db.flush()
    return c

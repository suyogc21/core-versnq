"""Settings → Brands, and which brands a person is limited to (finish plan, batch 4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.brands import service as B
from app.modules.brands.models import Brand, UserBrand
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.engage.models import Mailbox, WhatsAppAccount
from app.modules.money.models import BillingEntity
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["brands"], dependencies=CRM)
Admin = Annotated[CurrentUser, require("settings.manage")]
UserAdmin = Annotated[CurrentUser, require("users.manage")]

Colour = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
HttpsUrl = Field(default=None, max_length=500, pattern=r"^https://\S+$")


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    colour: str | None = Colour
    logo_url: str | None = HttpsUrl
    website: str | None = Field(default=None, max_length=300, pattern=r"^https?://\S+$")
    billing_entity_id: uuid.UUID | None = None
    is_active: bool = True


class BrandOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    colour: str | None
    logo_url: str | None
    website: str | None
    billing_entity_id: uuid.UUID | None
    is_default: bool
    is_active: bool


class UserBrandsIn(BaseModel):
    brand_ids: list[uuid.UUID] = Field(default=[], max_length=100)  # empty: every brand


class UserBrandsOut(BaseModel):
    user_id: uuid.UUID
    brand_ids: list[uuid.UUID]  # empty: every brand


async def _check(db, body: BrandIn, brand_id: uuid.UUID | None = None) -> None:
    same = await db.scalar(
        select(Brand.id).where(func.lower(Brand.name) == body.name.strip().lower())
    )
    if same is not None and same != brand_id:
        raise Invalid("A brand with this name already exists", code="brand_exists")
    if body.billing_entity_id and await db.get(BillingEntity, body.billing_entity_id) is None:
        raise Invalid("Choose a billing entity from Settings → Money")


@router.get("/brands", response_model=list[BrandOut])
async def list_brands(db: CrmDb, actor: ActiveUser, include_inactive: bool = False) -> list[Brand]:
    """The company's brands. Everyone sees the active ones (to pick from); admins can ask for
    switched-off ones too. A company with none or one brand shows no brand choices anywhere."""
    q = select(Brand).order_by(Brand.is_default.desc(), Brand.position, Brand.name)
    if not include_inactive:
        q = q.where(Brand.is_active.is_(True))
    return list((await db.scalars(q)).all())


@router.post("/brands", response_model=BrandOut, status_code=status.HTTP_201_CREATED)
async def create_brand(body: BrandIn, db: CrmDb, actor: Admin) -> Brand:
    await _check(db, body)
    first = await db.scalar(select(func.count()).select_from(Brand)) == 0
    position = (await db.scalar(select(func.max(Brand.position)))) or 0
    brand = Brand(
        id=uuid.uuid4(), tenant_id=actor.user.tenant_id, name=body.name.strip(),
        colour=body.colour, logo_url=body.logo_url, website=body.website,
        billing_entity_id=body.billing_entity_id, is_active=True, is_default=first,
        position=position + 1,
    )  # fmt: skip
    db.add(brand)
    await db.flush()
    await audit(db, actor, "brand.created", "brand", brand.id, after={"name": brand.name})
    return brand


@router.put("/brands/{brand_id}", response_model=BrandOut)
async def update_brand(brand_id: uuid.UUID, body: BrandIn, db: CrmDb, actor: Admin) -> Brand:
    brand = await db.get(Brand, brand_id)
    if brand is None:
        raise NotFound("Brand not found")
    await _check(db, body, brand.id)
    if not body.is_active and brand.is_default:
        raise Invalid("Make another brand the default first", code="brand_is_default")
    brand.name, brand.colour, brand.logo_url = body.name.strip(), body.colour, body.logo_url
    brand.website, brand.billing_entity_id = body.website, body.billing_entity_id
    brand.is_active = body.is_active
    await db.flush()
    await audit(db, actor, "brand.updated", "brand", brand.id, after=body.model_dump(mode="json"))
    return brand


@router.post("/brands/{brand_id}/default", response_model=BrandOut)
async def make_default(brand_id: uuid.UUID, db: CrmDb, actor: Admin) -> Brand:
    brand = await db.get(Brand, brand_id)
    if brand is None or not brand.is_active:
        raise NotFound("Brand not found")
    await db.execute(update(Brand).where(Brand.id != brand.id).values(is_default=False))
    await db.flush()
    brand.is_default = True
    await db.flush()
    await audit(db, actor, "brand.made_default", "brand", brand.id)
    return brand


@router.get("/users/{user_id}/brands", response_model=UserBrandsOut)
async def user_brands(user_id: uuid.UUID, db: CrmDb, actor: UserAdmin) -> UserBrandsOut:
    if await db.get(User, user_id) is None:
        raise NotFound("User not found")
    return UserBrandsOut(user_id=user_id, brand_ids=await B.limited_to(db, user_id) or [])


@router.put("/users/{user_id}/brands", response_model=UserBrandsOut)
async def set_user_brands(
    user_id: uuid.UUID, body: UserBrandsIn, db: CrmDb, actor: UserAdmin
) -> UserBrandsOut:
    """Limit a person to some brands (they see only those brands' leads, deals and money), or
    send an empty list for every brand. Nobody can limit themselves (no lock-out)."""
    if await db.get(User, user_id) is None:
        raise NotFound("User not found")
    if user_id == actor.user.id and body.brand_ids:
        raise Invalid("You can't limit your own brands", code="brand_self_limit")
    ids = list(dict.fromkeys(body.brand_ids))
    for bid in ids:
        if await db.get(Brand, bid) is None:
            raise Invalid("Choose brands from Settings → Brands", code="brand_invalid")
    await db.execute(delete(UserBrand).where(UserBrand.user_id == user_id))
    for bid in ids:
        db.add(UserBrand(id=uuid.uuid4(), tenant_id=actor.user.tenant_id, user_id=user_id,
                         brand_id=bid))  # fmt: skip
    await db.flush()
    await audit(db, actor, "user.brands_set", "user", user_id,
                after={"brand_ids": [str(b) for b in ids]})  # fmt: skip
    return UserBrandsOut(user_id=user_id, brand_ids=ids)


# ---------- which inbox and WhatsApp number belong to which brand ----------
class ChannelBrandIn(BaseModel):
    brand_id: uuid.UUID | None = None  # None: no brand (its leads get the default)


class MailboxChannel(BaseModel):
    id: uuid.UUID
    email_address: str
    brand_id: uuid.UUID | None


class WhatsAppChannel(BaseModel):
    id: uuid.UUID
    display_number: str | None
    brand_id: uuid.UUID | None


class ChannelsOut(BaseModel):
    mailboxes: list[MailboxChannel]
    whatsapp: WhatsAppChannel | None


async def _brand_or_none(db, brand_id: uuid.UUID | None) -> uuid.UUID | None:
    if brand_id is None:
        return None
    brand = await db.get(Brand, brand_id)
    if brand is None or not brand.is_active:
        raise Invalid("Choose an active brand", code="brand_invalid")
    return brand.id


async def _channels(db) -> ChannelsOut:
    boxes = (await db.scalars(select(Mailbox).order_by(Mailbox.email_address))).all()
    wa = await db.scalar(select(WhatsAppAccount))
    return ChannelsOut(
        mailboxes=[MailboxChannel(id=m.id, email_address=m.email_address, brand_id=m.brand_id)
                   for m in boxes],
        whatsapp=WhatsAppChannel(id=wa.id, display_number=wa.display_number, brand_id=wa.brand_id)
        if wa else None,
    )  # fmt: skip


@router.get("/brands/channels", response_model=ChannelsOut)
async def channels(db: CrmDb, actor: Admin) -> ChannelsOut:
    """Settings → Brands: the company's inboxes and WhatsApp number, with their brand. Leads that
    come in through one of them get its brand."""
    return await _channels(db)


@router.put("/brands/channels/mailboxes/{mailbox_id}", response_model=ChannelsOut)
async def set_mailbox_brand(
    mailbox_id: uuid.UUID, body: ChannelBrandIn, db: CrmDb, actor: Admin
) -> ChannelsOut:
    box = await db.get(Mailbox, mailbox_id)
    if box is None:
        raise NotFound("Inbox not found")
    box.brand_id = await _brand_or_none(db, body.brand_id)
    await db.flush()
    await audit(db, actor, "mailbox.brand_set", "mailbox", box.id,
                after={"brand_id": str(box.brand_id) if box.brand_id else None})  # fmt: skip
    return await _channels(db)


@router.put("/brands/channels/whatsapp", response_model=ChannelsOut)
async def set_whatsapp_brand(body: ChannelBrandIn, db: CrmDb, actor: Admin) -> ChannelsOut:
    wa = await db.scalar(select(WhatsAppAccount))
    if wa is None:
        raise NotFound("No WhatsApp number is connected")
    wa.brand_id = await _brand_or_none(db, body.brand_id)
    await db.flush()
    await audit(db, actor, "whatsapp.brand_set", "whatsapp_account", wa.id,
                after={"brand_id": str(wa.brand_id) if wa.brand_id else None})  # fmt: skip
    return await _channels(db)

"""Brand rules (finish plan, batch 4).

- A person limited to some brands sees only the leads, deals, invoices, customers and payments
  of those brands, on top of their role's own / team / all scope. This is enforced in the lead
  and deal visibility filters, which every list, search, record and money query goes through.
- A new lead gets the brand it came in through (a form, a mailbox, the WhatsApp number), the one
  chosen by hand, or the default brand. A company with no brands works exactly as before.
"""

import uuid

from sqlalchemy import select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.brands.models import Brand, UserBrand


async def limited_to(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID] | None:
    """The brands this person is limited to, or None when they see every brand."""
    ids = (await db.scalars(select(UserBrand.brand_id).where(UserBrand.user_id == user_id))).all()
    return list(ids) or None


async def condition(db: AsyncSession, user_id: uuid.UUID, column):
    """SQL condition on a brand_id column for this person (true when not limited)."""
    ids = await limited_to(db, user_id)
    return true() if ids is None else column.in_(ids)


async def active(db: AsyncSession) -> list[Brand]:
    return list(
        (
            await db.scalars(
                select(Brand)
                .where(Brand.is_active.is_(True))
                .order_by(Brand.is_default.desc(), Brand.position, Brand.name)
            )
        ).all()
    )


async def pick(
    db: AsyncSession, user_id: uuid.UUID | None, wanted: uuid.UUID | None
) -> uuid.UUID | None:
    """The brand for something new: the one wanted (checked), else the default (the person's
    first allowed one when they are limited). None when the company has no brands."""
    allowed = await limited_to(db, user_id) if user_id else None
    if wanted is not None:
        brand = await db.get(Brand, wanted)
        if (brand is None or not brand.is_active) and user_id is None:
            wanted = None  # a form or number whose brand was switched off: the default
        elif brand is None or not brand.is_active:
            raise Invalid("Choose an active brand", code="brand_invalid")
    if wanted is not None:
        if allowed is not None and brand.id not in allowed:
            raise Invalid("You can't use that brand", code="brand_not_yours")
        return brand.id
    brands = await active(db)
    if allowed is not None:
        brands = [b for b in brands if b.id in allowed]
    return brands[0].id if brands else None


async def check_allowed(db: AsyncSession, user_id: uuid.UUID, brand_id: uuid.UUID | None) -> None:
    """Refuse moving something to a brand the person isn't allowed."""
    allowed = await limited_to(db, user_id)
    if allowed is not None and brand_id not in allowed:
        raise Invalid("You can't use that brand", code="brand_not_yours")


async def follow_lead(db: AsyncSession, lead) -> None:
    """A lead moved to another brand: its deals and invoices move with it, so nobody sees a
    deal or invoice whose lead they can't see."""
    from app.modules.crm.models import Deal
    from app.modules.money.models import Invoice

    await db.execute(update(Deal).where(Deal.lead_id == lead.id).values(brand_id=lead.brand_id))
    await db.execute(
        update(Invoice).where(Invoice.lead_id == lead.id).values(brand_id=lead.brand_id)
    )

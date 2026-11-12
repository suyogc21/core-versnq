"""Key accounts tables (migration 0019). An add-on: Core never depends on these."""

import uuid
from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped, _fk


class KeyAccount(TenantScoped, TimestampMixin, Base):
    """An organisation marked as a key account."""

    __tablename__ = "key_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_key_accounts_tenant_id_id"),
        _fk("org_lead_id", "leads", "fk_key_accounts_org_same_tenant", "CASCADE"),
    )

    org_lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tier: Mapped[str] = mapped_column(String(10), default="growth")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target_minor: Mapped[int | None] = mapped_column(BigInteger)
    target_currency: Mapped[str | None] = mapped_column(String(3))
    health: Mapped[str] = mapped_column(String(9), default="on_track")
    health_note: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1)


class AccountUnit(TenantScoped, TimestampMixin, Base):
    """A department that buys (HR, Finance, IT), with its budget holder."""

    __tablename__ = "account_units"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_account_units_tenant_id_id"),
        _fk("account_id", "key_accounts", "fk_account_units_account_same_tenant", "CASCADE"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(80))
    budget_holder_lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    budget_currency: Mapped[str | None] = mapped_column(String(3))
    position: Mapped[int] = mapped_column(Integer)


class Competitor(TenantScoped, TimestampMixin, Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_competitors_tenant_id_id"),)

    name: Mapped[str] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccountCell(TenantScoped, TimestampMixin, Base):
    """A grid cell set by hand: a competitor holds it, or it is not a fit."""

    __tablename__ = "account_cells"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_account_cells_tenant_id_id"),
        _fk("account_id", "key_accounts", "fk_account_cells_account_same_tenant", "CASCADE"),
        _fk("unit_id", "account_units", "fk_account_cells_unit_same_tenant", "CASCADE"),
        _fk("product_id", "products", "fk_account_cells_product_same_tenant", "CASCADE"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10))  # competitor / not_fit
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(String(300))


class AccountContact(TenantScoped, TimestampMixin, Base):
    """A person on the people map: role, stance and strength of the relationship."""

    __tablename__ = "account_contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_account_contacts_tenant_id_id"),
        _fk("account_id", "key_accounts", "fk_account_contacts_account_same_tenant", "CASCADE"),
        _fk("lead_id", "leads", "fk_account_contacts_lead_same_tenant", "CASCADE"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(14), default="influencer")
    stance: Mapped[str] = mapped_column(String(9), default="neutral")
    strength: Mapped[int] = mapped_column(Integer, default=3)
    note: Mapped[str | None] = mapped_column(String(300))


class AccountGoal(TenantScoped, TimestampMixin, Base):
    __tablename__ = "account_goals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_account_goals_tenant_id_id"),
        _fk("account_id", "key_accounts", "fk_account_goals_account_same_tenant", "CASCADE"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    target_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(6), default="open")
    position: Mapped[int] = mapped_column(Integer)

"""Money tables (migration 0017). Every amount is an integer in minor units (rule 7)."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin
from app.modules.crm.models import TenantScoped, _fk


class BillingEntity(TenantScoped, TimestampMixin, Base):
    """The legal company that issues an invoice, with its own numbering and gateway."""

    __tablename__ = "billing_entities"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_billing_entities_tenant_id_id"),)

    name: Mapped[str] = mapped_column(String(120))
    legal_name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3))
    tax_label: Mapped[str | None] = mapped_column(String(20))
    tax_id: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    bank_details: Mapped[str | None] = mapped_column(Text)
    upi_id: Mapped[str | None] = mapped_column(String(100))
    terms: Mapped[str | None] = mapped_column(Text)
    due_days: Mapped[int] = mapped_column(Integer, default=7)
    invoice_prefix: Mapped[str] = mapped_column(String(20), default="INV-")
    receipt_prefix: Mapped[str] = mapped_column(String(20), default="RCT-")
    next_invoice_number: Mapped[int] = mapped_column(Integer, default=1)
    next_receipt_number: Mapped[int] = mapped_column(Integer, default=1)
    yearly_reset: Mapped[bool] = mapped_column(Boolean, default=False)
    year_start_month: Mapped[int] = mapped_column(Integer, default=4)
    number_period: Mapped[str | None] = mapped_column(String(9))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer)


class TaxRate(TenantScoped, TimestampMixin, Base):
    __tablename__ = "tax_rates"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_tax_rates_tenant_id_id"),)

    name: Mapped[str] = mapped_column(String(60))
    parts: Mapped[list] = mapped_column(JSONB, default=list)  # [{"name", "rate_bp"}]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer)


class Invoice(TenantScoped, TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_invoices_tenant_id_id"),
        _fk("customer_id", "customers", "fk_invoices_customer_same_tenant"),
        _fk("lead_id", "leads", "fk_invoices_lead_same_tenant"),
        _fk("entity_id", "billing_entities", "fk_invoices_entity_same_tenant"),
        _fk("deal_id", "deals", "fk_invoices_deal_same_tenant"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    currency: Mapped[str] = mapped_column(String(3))
    number: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    pay_link: Mapped[bool] = mapped_column(Boolean, default=True)
    pay_direct: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_breakdown: Mapped[list] = mapped_column(JSONB, default=list)
    repeat_months: Mapped[int | None] = mapped_column(Integer)
    repeat_next_date: Mapped[date | None] = mapped_column(Date)
    repeated_from_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    void_reason: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, default=1)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # the lead's brand (batch 4)


class InvoiceLine(TenantScoped, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_invoice_lines_tenant_id_id"),
        _fk("invoice_id", "invoices", "fk_invoice_lines_invoice_same_tenant", "CASCADE"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    discount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    net_minor: Mapped[int] = mapped_column(BigInteger)
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    tax_name: Mapped[str | None] = mapped_column(String(60))
    tax_parts: Mapped[list] = mapped_column(JSONB, default=list)
    tax_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger)


class Installment(TenantScoped, Base):
    __tablename__ = "installments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_installments_tenant_id_id"),
        _fk("invoice_id", "invoices", "fk_installments_invoice_same_tenant", "CASCADE"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    due_date: Mapped[date] = mapped_column(Date)
    paid_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    before_sent_on: Mapped[date | None] = mapped_column(Date)
    due_sent_on: Mapped[date | None] = mapped_column(Date)
    overdue_sent_on: Mapped[date | None] = mapped_column(Date)


class GatewayAccount(TenantScoped, TimestampMixin, Base):
    __tablename__ = "gateway_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_gateway_accounts_tenant_id_id"),
        _fk("entity_id", "billing_entities", "fk_gateway_accounts_entity_same_tenant", "CASCADE"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    gateway: Mapped[str] = mapped_column(String(10))  # razorpay / stripe
    key_id: Mapped[str | None] = mapped_column(String(200))
    secret_enc: Mapped[str] = mapped_column(Text)
    webhook_secret_enc: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(4))  # test / live
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Payment(TenantScoped, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payments_tenant_id_id"),
        _fk("invoice_id", "invoices", "fk_payments_invoice_same_tenant"),
        _fk("lead_id", "leads", "fk_payments_lead_same_tenant"),
        _fk("entity_id", "billing_entities", "fk_payments_entity_same_tenant"),
        _fk("proof_file_id", "files", "fk_payments_proof_same_tenant"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    method: Mapped[str] = mapped_column(String(10))
    paid_on: Mapped[date] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(120))
    gateway_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    gateway_payment_id: Mapped[str | None] = mapped_column(String(100))
    proof_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    receipt_number: Mapped[str] = mapped_column(String(40))
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(8), default="ok")
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reverse_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class PaymentAllocation(TenantScoped, Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payment_allocations_tenant_id_id"),
        _fk("payment_id", "payments", "fk_payment_allocations_payment_same_tenant", "CASCADE"),
        _fk("installment_id", "installments", "fk_payment_allocations_inst_same_tenant", "CASCADE"),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    installment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount_minor: Mapped[int] = mapped_column(BigInteger)


class PaymentLink(TenantScoped, Base):
    __tablename__ = "payment_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payment_links_tenant_id_id"),
        _fk("invoice_id", "invoices", "fk_payment_links_invoice_same_tenant", "CASCADE"),
        _fk("gateway_account_id", "gateway_accounts", "fk_payment_links_account_same_tenant"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    installment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    gateway_account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    gateway: Mapped[str] = mapped_column(String(10))
    gateway_link_id: Mapped[str] = mapped_column(String(100))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(9), default="active")
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class GatewayEvent(TenantScoped, Base):
    __tablename__ = "gateway_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_gateway_events_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "gateway_account_id", "event_id", name="uq_gateway_events_event"
        ),
        _fk("gateway_account_id", "gateway_accounts", "fk_gateway_events_account_same_tenant"),
    )

    gateway_account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class MailAccount(TenantScoped, TimestampMixin, Base):
    """The company's own mailbox (SMTP), used to email invoices, receipts and reminders."""

    __tablename__ = "mail_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_mail_accounts_tenant_id_id"),)

    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    security: Mapped[str] = mapped_column(String(8))  # ssl / starttls
    username: Mapped[str] = mapped_column(String(254))
    password_enc: Mapped[str] = mapped_column(Text)
    from_name: Mapped[str] = mapped_column(String(120))
    from_email: Mapped[str] = mapped_column(String(254))
    reply_to: Mapped[str | None] = mapped_column(String(254))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class MoneyMessage(TenantScoped, Base):
    """One email to the customer about an invoice (sent by the worker, retried on failure)."""

    __tablename__ = "money_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_money_messages_tenant_id_id"),
        _fk("invoice_id", "invoices", "fk_money_messages_invoice_same_tenant", "CASCADE"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(8))  # invoice / receipt / reminder / void
    channel: Mapped[str] = mapped_column(String(8), default="email")
    to_address: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(7), default="queued")
    error: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

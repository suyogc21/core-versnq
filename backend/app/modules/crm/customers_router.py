"""Customers (step 5): make a customer, the customers list, one customer, the document
checklist and its files, checklist settings, storage use. Only staff upload files; customers
never send anything into Core themselves (Decision log #33)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core import storage
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser, require
from app.modules.crm import access as A
from app.modules.crm import customers as C
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, SCREENS, CrmDb, audit
from app.modules.crm.models import (
    Customer,
    Deal,
    Document,
    DocumentRequirement,
    Lead,
    Product,
    StoredFile,
)
from app.modules.settings.models import TenantSettings
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["customers"], dependencies=[*CRM, *SCREENS])
Configurer = Annotated[CurrentUser, require("crm.configure")]
# A file opened in the browser can never run scripts or load anything else.
CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"


# ---------- schemas ----------
class CustomerOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    lead_id: uuid.UUID
    number: str
    since: datetime
    status: str
    custom_fields: dict
    won_deal_id: uuid.UUID | None
    version: int
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    owner_user_id: uuid.UUID | None = None
    owner_name: str | None = None
    docs_done: int = 0
    docs_required: int = 0


class CustomerPage(BaseModel):
    items: list[CustomerOut]
    total: int


class MakeIn(BaseModel):
    deal_id: uuid.UUID | None = None


class CustomerPatch(BaseModel):
    version: int
    status: Literal["active", "inactive"] | None = None
    custom_fields: dict | None = None


class FileOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    original_name: str
    content_type: str
    size_bytes: int
    uploaded_by_user_id: uuid.UUID | None
    created_at: datetime
    previewable: bool = False


class DocumentOut(BaseModel):
    id: uuid.UUID
    requirement_id: uuid.UUID | None
    name: str
    hint: str | None
    is_required: bool
    allow_office: bool
    status: str
    reject_reason: str | None
    received_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by_name: str | None
    files: list[FileOut]


class ChecklistOut(BaseModel):
    documents: list[DocumentOut]
    done: int
    required: int


class OtherIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RequirementIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    hint: str | None = Field(default=None, max_length=300)
    is_required: bool = True
    allow_office: bool = False
    product_ids: list[uuid.UUID] = Field(default_factory=list)


class RequirementPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    hint: str | None = Field(default=None, max_length=300)
    is_required: bool | None = None
    allow_office: bool | None = None
    product_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


class RequirementOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    hint: str | None
    is_required: bool
    allow_office: bool
    product_ids: list[str]
    is_active: bool
    position: int


class RequirementOrderIn(BaseModel):
    ids: list[uuid.UUID]


class CustomerSettings(BaseModel):
    customer_prefix: str = Field(min_length=1, max_length=10)
    document_reminder_days: int = Field(ge=1, le=60)


class StorageOut(BaseModel):
    used_bytes: int
    quota_bytes: int


# ---------- helpers ----------
async def _out(
    db, rows: list[tuple[Customer, Lead]], actor: CurrentUser | None
) -> list[CustomerOut]:
    """Customers as the person may see them: hidden fields are blanked (step 8)."""
    rules = await A.rules(db, actor, "customer")
    owners = {
        u.id: u.name
        for u in (
            await db.scalars(
                select(User).where(User.id.in_({ld.owner_user_id for _, ld in rows} - {None}))
            )
        ).all()
    }
    counts = await C.doc_counts(db, [c.id for c, _ in rows])
    out = []
    for c, ld in rows:
        done, required = counts.get(c.id, (0, 0))
        out.append(
            CustomerOut.model_validate(c).model_copy(
                update={
                    "name": ld.display_name,
                    "phone": ld.primary_phone,
                    "email": ld.primary_email,
                    "owner_user_id": ld.owner_user_id,
                    "owner_name": owners.get(ld.owner_user_id),
                    "docs_done": done,
                    "docs_required": required,
                    "custom_fields": rules.redact_custom(c.custom_fields),
                }
            )
        )
    return out


async def _checklist(db, customer: Customer) -> ChecklistOut:
    items = await C.checklist(db, customer)
    reviewers = {
        u.id: u.name
        for u in (
            await db.scalars(
                select(User).where(
                    User.id.in_({d.reviewed_by_user_id for d, _, _ in items} - {None})
                )
            )
        ).all()
    }
    docs = [
        DocumentOut(
            id=d.id,
            requirement_id=d.requirement_id,
            name=r.name if r else d.name,
            hint=r.hint if r else None,
            is_required=bool(r and r.is_required),
            allow_office=r.allow_office if r else True,
            status=d.status,
            reject_reason=d.reject_reason,
            received_at=d.received_at,
            reviewed_at=d.reviewed_at,
            reviewed_by_name=reviewers.get(d.reviewed_by_user_id),
            files=[
                FileOut.model_validate(f).model_copy(
                    update={"previewable": f.content_type in storage.PREVIEWABLE}
                )
                for f in files
            ],
        )
        for d, r, files in items
    ]
    done, required = C.done_counts(items)
    return ChecklistOut(documents=docs, done=done, required=required)


async def _check_products(db, ids: list[uuid.UUID]) -> list[str]:
    if ids:
        found = set((await db.scalars(select(Product.id).where(Product.id.in_(ids)))).all())
        if len(found) != len(set(ids)):
            raise Invalid("Choose products from your catalogue")
    return [str(i) for i in dict.fromkeys(ids)]


# ---------- making a customer ----------
@router.post(
    "/leads/{lead_id}/customer", response_model=CustomerOut, status_code=status.HTTP_201_CREATED
)
async def make_customer(lead_id: uuid.UUID, body: MakeIn, db: CrmDb, actor: ActiveUser):
    if not (L.can(actor, "customers.create") and L.can(actor, "leads.edit")):
        raise Forbidden("permission_denied")
    lead = await L.get_visible(db, actor, lead_id)
    deal = None
    if body.deal_id:
        deal = await db.scalar(select(Deal).where(Deal.id == body.deal_id, Deal.lead_id == lead.id))
        if deal is None or deal.status != "won":
            raise Invalid("Choose a won deal of this lead")
    customer = await C.make(db, actor, lead, deal)
    await audit(
        db, actor, "customer.created", "customer", customer.id, after={"lead": str(lead.id)}
    )
    return (await _out(db, [(customer, lead)], actor))[0]


@router.get("/leads/{lead_id}/customer", response_model=CustomerOut | None)
async def customer_of_lead(lead_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    row = (
        await db.execute(
            select(Customer, Lead)
            .join(Lead, Lead.id == Customer.lead_id)
            .where(Customer.lead_id == lead_id, await C.visibility(db, actor))
        )
    ).first()
    return (await _out(db, [tuple(row)], actor))[0] if row else None


# ---------- list and one ----------
@router.get("/customers", response_model=CustomerPage)
async def list_customers(
    db: CrmDb,
    actor: ActiveUser,
    q: str | None = None,
    status_: Annotated[Literal["active", "inactive"] | None, Query(alias="status")] = None,
    owner: Annotated[list[str], Query()] = [],  # noqa: B006
    documents: Literal["missing", "complete"] | None = None,
    sort: Literal["since", "-since", "name", "number"] = "-since",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    if not L.can(actor, "customers.read"):
        raise Forbidden("permission_denied")
    where = [await C.visibility(db, actor)]
    if q and q.strip():
        like = f"%{q.strip()}%"
        where.append(
            or_(
                Lead.display_name.ilike(like),
                Customer.number.ilike(like),
                Lead.primary_phone.ilike(like),
                Lead.primary_email.ilike(like),
            )
        )
    if status_:
        where.append(Customer.status == status_)
    if owner:
        ids = [uuid.UUID(o) for o in owner if o not in ("me", "none")]
        conds = [Lead.owner_user_id.in_(ids)] if ids else []
        if "me" in owner:
            conds.append(Lead.owner_user_id == actor.user.id)
        if "none" in owner:
            conds.append(Lead.owner_user_id.is_(None))
        where.append(or_(*conds))
    if documents:
        missing = (
            select(Document.customer_id)
            .join(DocumentRequirement, DocumentRequirement.id == Document.requirement_id)
            .where(
                Document.status.in_(("pending", "rejected")),
                DocumentRequirement.is_required.is_(True),
                DocumentRequirement.is_active.is_(True),
            )
        )
        where.append(
            Customer.id.in_(missing) if documents == "missing" else Customer.id.not_in(missing)
        )
    base = select(Customer, Lead).join(Lead, Lead.id == Customer.lead_id).where(*where)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    order = {
        "since": Customer.since.asc(),
        "-since": Customer.since.desc(),
        "name": Lead.display_name.asc(),
        "number": Customer.number.asc(),
    }[sort]
    rows = (
        await db.execute(
            base.order_by(order, Customer.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return CustomerPage(items=await _out(db, [tuple(r) for r in rows], actor), total=total or 0)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    return (await _out(db, [await C.get_visible(db, actor, customer_id)], actor))[0]


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: uuid.UUID, body: CustomerPatch, db: CrmDb, actor: ActiveUser
):
    customer, lead = await C.get_editable(db, actor, customer_id)
    if body.version != customer.version:
        raise Conflict("Someone else changed this customer. Reload and try again.")
    changed = []
    if body.status and body.status != customer.status:
        customer.status = body.status
        changed.append("status")
    if body.custom_fields is not None:
        changed += await L.apply_custom_fields(
            db, customer, body.custom_fields, creating=False, entity="customer",
            rules=await A.rules(db, actor, "customer"),
        )  # fmt: skip
    if changed:
        customer.version += 1
        await L.log(
            db,
            lead,
            "customer_updated",
            "Customer details changed",
            actor,
            {"customer_id": str(customer.id), "fields": changed},
        )
        await audit(
            db, actor, "customer.updated", "customer", customer.id, after={"fields": changed}
        )
    await db.flush()
    return (await _out(db, [(customer, lead)], actor))[0]


# ---------- documents ----------
@router.get("/customers/{customer_id}/documents", response_model=ChecklistOut)
async def documents(customer_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    customer, _ = await C.get_visible(db, actor, customer_id)
    return await _checklist(db, customer)


@router.post(
    "/customers/{customer_id}/documents",
    response_model=ChecklistOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_other_document(customer_id: uuid.UUID, body: OtherIn, db: CrmDb, actor: ActiveUser):
    customer, _ = await C.get_editable(db, actor, customer_id)
    await C.add_other(db, actor, customer, body.name)
    return await _checklist(db, customer)


@router.post(
    "/customers/{customer_id}/documents/{document_id}/files",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_file(
    customer_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    db: CrmDb,
    actor: ActiveUser,
    name: Annotated[str, Query(min_length=1, max_length=255)],
):
    """The request body is the file itself (up to 10 MB); `name` is its original name."""
    customer, lead = await C.get_editable(db, actor, customer_id)
    doc = await C.get_document(db, customer, document_id)
    data = await storage.read_upload(request)
    stored = await C.upload(
        db, customer=customer, lead=lead, doc=doc, data=data, name=name, actor=actor
    )
    return FileOut.model_validate(stored).model_copy(
        update={"previewable": stored.content_type in storage.PREVIEWABLE}
    )


@router.post("/customers/{customer_id}/documents/{document_id}/verify", response_model=ChecklistOut)
async def verify_document(
    customer_id: uuid.UUID, document_id: uuid.UUID, db: CrmDb, actor: ActiveUser
):
    customer, lead = await C.get_visible(db, actor, customer_id)
    doc = await C.get_document(db, customer, document_id)
    await C.review(db, actor, customer, lead, doc, verified=True)
    return await _checklist(db, customer)


@router.post("/customers/{customer_id}/documents/{document_id}/reject", response_model=ChecklistOut)
async def reject_document(
    customer_id: uuid.UUID, document_id: uuid.UUID, body: RejectIn, db: CrmDb, actor: ActiveUser
):
    customer, lead = await C.get_visible(db, actor, customer_id)
    doc = await C.get_document(db, customer, document_id)
    await C.review(db, actor, customer, lead, doc, verified=False, reason=body.reason)
    return await _checklist(db, customer)


@router.get(
    "/customers/{customer_id}/files/{file_id}",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_file(
    customer_id: uuid.UUID, file_id: uuid.UUID, db: CrmDb, actor: ActiveUser, download: bool = False
):
    customer, _ = await C.get_visible(db, actor, customer_id)
    stored = await C.get_file(db, customer, file_id)
    path = storage.full_path(stored.path)
    if not path.exists():
        raise NotFound("This file is missing on the server. Upload it again.")
    inline = not download and stored.content_type in storage.PREVIEWABLE
    return FileResponse(
        path,
        media_type=stored.content_type,
        filename=stored.original_name,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": CSP,
        },
    )


@router.delete("/customers/{customer_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(customer_id: uuid.UUID, file_id: uuid.UUID, db: CrmDb, actor: ActiveUser):
    customer, lead = await C.get_visible(db, actor, customer_id)
    stored = await C.get_file(db, customer, file_id)
    await audit(db, actor, "file.deleted", "file", stored.id, before={"name": stored.original_name})
    await C.delete_file(db, actor, customer, lead, stored)


# ---------- checklist settings ----------
@router.get("/document-requirements", response_model=list[RequirementOut])
async def list_requirements(db: CrmDb, _: ActiveUser):
    return list(
        (await db.scalars(select(DocumentRequirement).order_by(DocumentRequirement.position))).all()
    )


@router.post(
    "/document-requirements", response_model=RequirementOut, status_code=status.HTTP_201_CREATED
)
async def create_requirement(body: RequirementIn, db: CrmDb, actor: Configurer):
    if await db.scalar(
        select(DocumentRequirement.id).where(
            func.lower(DocumentRequirement.name) == body.name.strip().lower()
        )
    ):
        raise Conflict(f"'{body.name.strip()}' is already on the checklist")
    pos = await db.scalar(select(func.coalesce(func.max(DocumentRequirement.position), -1)))
    req = DocumentRequirement(
        tenant_id=actor.user.tenant_id,
        name=body.name.strip(),
        hint=body.hint,
        is_required=body.is_required,
        allow_office=body.allow_office,
        product_ids=await _check_products(db, body.product_ids),
        position=pos + 1,
    )
    db.add(req)
    await db.flush()
    await C.sync_all(db)
    await audit(db, actor, "document_requirement.created", "document_requirement", req.id)
    return req


@router.patch("/document-requirements/{req_id}", response_model=RequirementOut)
async def update_requirement(
    req_id: uuid.UUID, body: RequirementPatch, db: CrmDb, actor: Configurer
):
    req = await db.get(DocumentRequirement, req_id)
    if req is None:
        raise NotFound("Checklist item not found")
    data = body.model_dump(exclude_unset=True)
    if "product_ids" in data:
        data["product_ids"] = await _check_products(db, body.product_ids or [])
    if "name" in data:
        data["name"] = data["name"].strip()
        clash = await db.scalar(
            select(DocumentRequirement.id).where(
                func.lower(DocumentRequirement.name) == data["name"].lower(),
                DocumentRequirement.id != req.id,
            )
        )
        if clash:
            raise Conflict(f"'{data['name']}' is already on the checklist")
    for k, v in data.items():
        setattr(req, k, v)
    await db.flush()
    if data.keys() & {"product_ids", "is_active", "name"}:
        await C.sync_all(db)
    await audit(
        db,
        actor,
        "document_requirement.updated",
        "document_requirement",
        req.id,
        after=data | {"product_ids": req.product_ids},
    )
    return req


@router.delete("/document-requirements/{req_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_requirement(req_id: uuid.UUID, db: CrmDb, actor: Configurer):
    """Customers keep what they already sent (it moves to "Other documents")."""
    req = await db.get(DocumentRequirement, req_id)
    if req is None:
        raise NotFound("Checklist item not found")
    unused = select(Document.id).where(
        Document.requirement_id == req.id,
        Document.status == "pending",
        ~select(StoredFile.id).where(StoredFile.document_id == Document.id).exists(),
    )
    for doc in (await db.scalars(select(Document).where(Document.id.in_(unused)))).all():
        await db.delete(doc)
    await db.delete(req)
    await audit(db, actor, "document_requirement.deleted", "document_requirement", req_id)


@router.put("/document-requirements/order", response_model=list[RequirementOut])
async def order_requirements(body: RequirementOrderIn, db: CrmDb, _: Configurer):
    reqs = {r.id: r for r in (await db.scalars(select(DocumentRequirement))).all()}
    if set(body.ids) != set(reqs) or len(body.ids) != len(reqs):
        raise Invalid("Send every checklist item once")
    for i, rid in enumerate(body.ids):
        reqs[rid].position = i
    await db.flush()
    return [reqs[i] for i in body.ids]


@router.get("/customer-settings", response_model=CustomerSettings)
async def get_customer_settings(db: CrmDb, actor: ActiveUser):
    return CustomerSettings.model_validate(
        await db.get(TenantSettings, actor.user.tenant_id), from_attributes=True
    )


@router.put("/customer-settings", response_model=CustomerSettings)
async def put_customer_settings(body: CustomerSettings, db: CrmDb, actor: Configurer):
    s = await db.get(TenantSettings, actor.user.tenant_id)
    before = CustomerSettings.model_validate(s, from_attributes=True).model_dump()
    for k, v in body.model_dump().items():
        setattr(s, k, v.strip() if isinstance(v, str) else v)
    await db.flush()
    await audit(
        db, actor, "settings.customers", "tenant_settings", s.tenant_id, before, body.model_dump()
    )
    return CustomerSettings.model_validate(s, from_attributes=True)


@router.get("/storage", response_model=StorageOut)
async def storage_use(db: CrmDb, actor: Configurer):
    s = await db.get(TenantSettings, actor.user.tenant_id)
    return StorageOut(used_bytes=await C.storage_used(db), quota_bytes=s.storage_quota_bytes)

"""Customers and their documents (step 5, Decision log #32).

A customer is a lead that became a customer: the same record and timeline, plus a `customers`
row (number, since, status, customer-only fields). Each customer has a document checklist built
from the company's requirements; files live on our own server through `app.core.storage`.

Who sees what: customers follow the lead's visibility (own / team / all). A role that reads
customers but does not work leads (Finance) sees every customer, read-only.
"""

import uuid
from datetime import timedelta

from sqlalchemy import false, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.errors import Conflict, DomainError, Forbidden, Invalid, NotFound
from app.modules.auth.deps import CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.models import (
    Customer,
    Deal,
    DealProduct,
    Document,
    DocumentRequirement,
    Lead,
    LeadStage,
    StoredFile,
    Task,
)
from app.modules.settings.models import TenantSettings

REVIEWED = ("verified", "rejected")


# ---------- who may see and change ----------
async def visibility(db: AsyncSession, actor: CurrentUser):
    """SQL condition on Lead for the customers this person may see."""
    if not L.can(actor, "customers.read"):
        return false()
    if not L.can(actor, "leads.edit"):  # Finance: every customer (of their brands), read-only
        from app.modules.brands import service as B

        return await B.condition(db, actor.user.id, Lead.brand_id)
    return await L.visibility_filter(db, actor)


async def get_visible(
    db: AsyncSession, actor: CurrentUser, customer_id: uuid.UUID
) -> tuple[Customer, Lead]:
    row = (
        await db.execute(
            select(Customer, Lead)
            .join(Lead, Lead.id == Customer.lead_id)
            .where(Customer.id == customer_id, await visibility(db, actor))
        )
    ).first()
    if row is None:
        raise NotFound("Customer not found")
    return row[0], row[1]


async def get_editable(
    db: AsyncSession, actor: CurrentUser, customer_id: uuid.UUID
) -> tuple[Customer, Lead]:
    if not L.can(actor, "leads.edit"):
        raise Forbidden("permission_denied")
    return await get_visible(db, actor, customer_id)


async def of_lead(db: AsyncSession, lead_id: uuid.UUID) -> Customer | None:
    return await db.scalar(select(Customer).where(Customer.lead_id == lead_id))


# ---------- becoming a customer ----------
async def make(
    db: AsyncSession, actor: CurrentUser | None, lead: Lead, deal: Deal | None = None
) -> Customer:
    if await of_lead(db, lead.id):
        raise Conflict(f"{lead.display_name} is already a customer")
    settings = await db.scalar(
        select(TenantSettings).where(TenantSettings.tenant_id == lead.tenant_id).with_for_update()
    )
    number = f"{settings.customer_prefix}{settings.next_customer_number:04d}"
    settings.next_customer_number += 1
    customer = Customer(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        number=number,
        since=L.now(),
        status="active",
        custom_fields={},
        won_deal_id=deal.id if deal else None,
        created_by_user_id=actor.user.id if actor else None,
    )
    db.add(customer)
    await db.flush()
    # A company with a "converted" lead stage moves the lead there (it leaves the follow-up
    # queues). If that stage needs fields the lead lacks, the lead simply stays where it is.
    converted = await db.scalar(
        select(LeadStage).where(LeadStage.is_converted.is_(True)).order_by(LeadStage.position)
    )
    if converted and converted.id != lead.stage_id:
        try:
            async with db.begin_nested():
                await L.move_stage(db, lead, converted, actor)
        except DomainError:
            pass
    await L.log(
        db,
        lead,
        "became_customer",
        f"Became customer {number}",
        actor,
        {"customer_id": str(customer.id), "deal_id": str(deal.id) if deal else None},
    )
    await L.event(
        db,
        lead,
        "customer.created",
        {
            "customer_id": str(customer.id),
            "number": number,
            "deal_id": str(deal.id) if deal else None,
        },
    )
    await sync_documents(db, customer)
    return customer


# ---------- the checklist ----------
async def won_products(db: AsyncSession, lead_id: uuid.UUID) -> set[str]:
    rows = await db.scalars(
        select(DealProduct.product_id)
        .join(Deal, Deal.id == DealProduct.deal_id)
        .where(Deal.lead_id == lead_id, Deal.status == "won", DealProduct.product_id.isnot(None))
    )
    return {str(p) for p in rows}


async def applicable(db: AsyncSession, lead_id: uuid.UUID) -> list[DocumentRequirement]:
    reqs = (
        await db.scalars(
            select(DocumentRequirement)
            .where(DocumentRequirement.is_active.is_(True))
            .order_by(DocumentRequirement.position)
        )
    ).all()
    products = await won_products(db, lead_id)
    return [r for r in reqs if not r.product_ids or products & set(r.product_ids)]


async def sync_documents(db: AsyncSession, customer: Customer) -> None:
    """Every checklist item that applies gets a (pending) document. Never removes any."""
    reqs = await applicable(db, customer.lead_id)
    if reqs:
        await db.execute(
            insert(Document)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": customer.tenant_id,
                        "customer_id": customer.id,
                        "requirement_id": r.id,
                        "name": r.name,
                        "status": "pending",
                    }
                    for r in reqs
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["customer_id", "requirement_id"],
                index_where=Document.requirement_id.isnot(None),
            )
        )


async def checklist(
    db: AsyncSession, customer: Customer
) -> list[tuple[Document, DocumentRequirement | None, list[StoredFile]]]:
    """The customer's documents in checklist order, then "Other documents". Pending items
    whose requirement no longer applies (switched off, product changed) are hidden."""
    await sync_documents(db, customer)
    live = {r.id: (i, r) for i, r in enumerate(await applicable(db, customer.lead_id))}
    docs = (await db.scalars(select(Document).where(Document.customer_id == customer.id))).all()
    files = (
        await db.scalars(
            select(StoredFile)
            .where(StoredFile.document_id.in_([d.id for d in docs]))
            .order_by(StoredFile.created_at)
        )
    ).all()
    by_doc: dict[uuid.UUID, list[StoredFile]] = {}
    for f in files:
        by_doc.setdefault(f.document_id, []).append(f)
    reqs = {
        r.id: r
        for r in (
            await db.scalars(
                select(DocumentRequirement).where(
                    DocumentRequirement.id.in_([d.requirement_id for d in docs if d.requirement_id])
                )
            )
        ).all()
    }
    out = []
    for d in docs:
        shown = d.requirement_id is None or d.requirement_id in live
        if shown or by_doc.get(d.id) or d.status != "pending":
            out.append((d, reqs.get(d.requirement_id), by_doc.get(d.id, [])))
    far = len(live) + 1
    out.sort(
        key=lambda x: (
            live[x[0].requirement_id][0] if x[0].requirement_id in live else far,
            x[0].created_at,
        )
    )
    return out


async def get_document(db: AsyncSession, customer: Customer, document_id: uuid.UUID) -> Document:
    doc = await db.scalar(
        select(Document).where(Document.id == document_id, Document.customer_id == customer.id)
    )
    if doc is None:
        raise NotFound("Document not found")
    return doc


async def add_other(
    db: AsyncSession, actor: CurrentUser, customer: Customer, name: str
) -> Document:
    name = name.strip()
    if not name:
        raise Invalid("Give the document a name")
    doc = Document(
        tenant_id=customer.tenant_id,
        customer_id=customer.id,
        requirement_id=None,
        name=name[:120],
        status="pending",
    )
    db.add(doc)
    await db.flush()
    return doc


# ---------- files ----------
async def storage_used(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.coalesce(func.sum(StoredFile.size_bytes), 0))))


async def upload(
    db: AsyncSession,
    *,
    customer: Customer,
    lead: Lead,
    doc: Document,
    data: bytes,
    name: str,
    actor: CurrentUser | None = None,
) -> StoredFile:
    """Check, save to disk, then record. A failure after saving removes the file again.
    Only staff upload; customers never send files into Core themselves (Decision log #33)."""
    req = await db.get(DocumentRequirement, doc.requirement_id) if doc.requirement_id else None
    content_type, ext = storage.check_type(
        data, name, allow_office=req.allow_office if req else True
    )
    settings = await db.get(TenantSettings, customer.tenant_id)
    if await storage_used(db) + len(data) > settings.storage_quota_bytes:
        gb = settings.storage_quota_bytes / 1024**3
        raise Invalid(
            f"Your company has used all of its {gb:g} GB of file storage. "
            "Ask your admin to add more storage."
        )
    saved = storage.save(customer.tenant_id, data, ext, content_type)
    try:
        async with db.begin_nested():
            stored = StoredFile(
                tenant_id=customer.tenant_id,
                lead_id=lead.id,
                document_id=doc.id,
                path=saved.path,
                original_name=storage.clean_name(name),
                content_type=content_type,
                size_bytes=saved.size_bytes,
                sha256=saved.sha256,
                uploaded_by_user_id=actor.user.id if actor else None,
            )
            db.add(stored)
            doc.status, doc.received_at = "received", L.now()
            doc.reject_reason = doc.reviewed_at = doc.reviewed_by_user_id = None
            await db.flush()
    except Exception:
        storage.remove(saved.path)
        raise
    await L.log(
        db,
        lead,
        "document_uploaded",
        f"{doc.name}: {stored.original_name}",
        actor,
        {"customer_id": str(customer.id), "document_id": str(doc.id), "file_id": str(stored.id)},
    )
    await L.event(
        db,
        lead,
        "document.received",
        {"customer_id": str(customer.id), "document_id": str(doc.id), "name": doc.name},
    )
    return stored


async def review(
    db: AsyncSession,
    actor: CurrentUser,
    customer: Customer,
    lead: Lead,
    doc: Document,
    verified: bool,
    reason: str | None = None,
) -> Document:
    if not L.can(actor, "documents.verify"):
        raise Forbidden("permission_denied")
    has_files = await db.scalar(select(func.count()).where(StoredFile.document_id == doc.id))
    if not has_files:
        raise Invalid("Nothing has been uploaded for this document yet")
    reason = (reason or "").strip()
    if not verified and not reason:
        raise Invalid("Say why it is rejected, so the customer knows what to send")
    doc.status = "verified" if verified else "rejected"
    doc.reject_reason = None if verified else reason[:500]
    doc.reviewed_at, doc.reviewed_by_user_id = L.now(), actor.user.id
    await db.flush()
    word = "verified" if verified else f"rejected: {reason}"
    await L.log(
        db,
        lead,
        "document_verified" if verified else "document_rejected",
        f"{doc.name} {word}",
        actor,
        {"customer_id": str(customer.id), "document_id": str(doc.id)},
    )
    await L.event(
        db,
        lead,
        "document.verified" if verified else "document.rejected",
        {"customer_id": str(customer.id), "document_id": str(doc.id), "name": doc.name},
    )
    return doc


async def delete_file(
    db: AsyncSession, actor: CurrentUser, customer: Customer, lead: Lead, stored: StoredFile
) -> None:
    if not L.can(actor, "leads.delete"):
        raise Forbidden("permission_denied")
    doc = await db.get(Document, stored.document_id) if stored.document_id else None
    path, name = stored.path, stored.original_name
    await db.delete(stored)
    await db.flush()
    if doc is not None:
        left = await db.scalar(select(func.count()).where(StoredFile.document_id == doc.id))
        if not left:
            doc.status, doc.received_at = "pending", None
            doc.reject_reason = doc.reviewed_at = doc.reviewed_by_user_id = None
    await L.log(
        db,
        lead,
        "document_deleted",
        f"{doc.name if doc else 'File'}: {name} deleted",
        actor,
        {"customer_id": str(customer.id)},
    )
    await db.flush()
    storage.remove(path)


async def get_file(db: AsyncSession, customer: Customer, file_id: uuid.UUID) -> StoredFile:
    stored = await db.scalar(
        select(StoredFile)
        .join(Document, Document.id == StoredFile.document_id)
        .where(StoredFile.id == file_id, Document.customer_id == customer.id)
    )
    if stored is None:
        raise NotFound("File not found")
    return stored


# ---------- nightly ----------
async def remind_pending(db: AsyncSession) -> int:
    """A task for the owner when required documents are still missing after N days."""
    settings = await db.scalar(select(TenantSettings))
    if settings is None:
        return 0
    cutoff = L.now() - timedelta(days=settings.document_reminder_days)
    missing = (
        select(Document.customer_id)
        .join(DocumentRequirement, DocumentRequirement.id == Document.requirement_id)
        .where(
            Document.status.in_(("pending", "rejected")),
            DocumentRequirement.is_required.is_(True),
            DocumentRequirement.is_active.is_(True),
        )
    )
    open_task = select(Task.id).where(
        Task.lead_id == Lead.id, Task.created_from == "documents", Task.status == "open"
    )
    rows = (
        await db.execute(
            select(Customer, Lead)
            .join(Lead, Lead.id == Customer.lead_id)
            .where(
                Customer.status == "active",
                Customer.since < cutoff,
                Customer.id.in_(missing),
                Lead.owner_user_id.isnot(None),
                ~open_task.exists(),
            )
        )
    ).all()
    for _customer, lead in rows:
        db.add(
            Task(
                tenant_id=lead.tenant_id,
                lead_id=lead.id,
                title="Collect pending documents",
                due_at=L.now(),
                owner_user_id=lead.owner_user_id,
                created_from="documents",
            )
        )
    await db.flush()
    return len(rows)


async def clean_files(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Remove files on disk that lost their record; report records whose file is missing."""
    from app.modules.calls.models import Call  # call recordings live on disk too (step C1)

    known = set((await db.scalars(select(StoredFile.path))).all())
    recordings = set((await db.scalars(select(Call.recording_path).where(
        Call.recording_path.is_not(None)))).all())  # fmt: skip
    keep = known | recordings
    on_disk = storage.stored_paths(tenant_id)
    hour_ago = L.now().timestamp() - 3600
    removed = 0
    for rel in on_disk:
        if rel not in keep and storage.full_path(rel).stat().st_mtime < hour_ago:
            storage.remove(rel)
            removed += 1
    for part in storage.leftover_parts(tenant_id):
        part.unlink(missing_ok=True)
    disk = set(on_disk)
    return {"removed": removed, "missing": sorted(p for p in known if p not in disk)}


async def doc_counts(db: AsyncSession, customer_ids: list[uuid.UUID]) -> dict:
    """{customer id: (received or verified, required)} over active required checklist items."""
    rows = await db.execute(
        select(
            Document.customer_id,
            func.count().filter(Document.status.in_(("received", "verified"))),
            func.count(),
        )
        .join(DocumentRequirement, DocumentRequirement.id == Document.requirement_id)
        .where(
            Document.customer_id.in_(customer_ids),
            DocumentRequirement.is_required.is_(True),
            DocumentRequirement.is_active.is_(True),
        )
        .group_by(Document.customer_id)
    )
    return {cid: (done, req) for cid, done, req in rows}


async def sync_all(db: AsyncSession) -> None:
    """After the checklist changes: every active customer gets the items that now apply."""
    for customer in (await db.scalars(select(Customer).where(Customer.status == "active"))).all():
        await sync_documents(db, customer)


def done_counts(items) -> tuple[int, int]:
    """(verified or received required items, required items) for list badges."""
    req = [d for d, r, _ in items if r is not None and r.is_required]
    return sum(d.status in ("received", "verified") for d in req), len(req)

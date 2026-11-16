"""CSV import: upload → match columns → run in the worker → download the rows that failed.

Every row goes through the same intake rules as a lead added by hand (required fields too).
Each row is saved on its own, so one bad row never stops the good ones. Rows are processed in
batches with a commit after each, so progress is visible and a crashed worker resumes where it
stopped. Leads someone else owns are never changed by an import from a person who cannot see
them. The stored rows can be deleted once the import is done.
"""

import csv
import io
import uuid
from datetime import timedelta
from typing import Literal

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, Invalid
from app.core.tenancy import platform_session, tenant_session
from app.modules.auth.deps import CurrentUser, effective_permissions
from app.modules.crm import access as A
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm import mapping as MP
from app.modules.crm.models import Import, ImportRow, LeadSource, LeadStage
from app.modules.crm.notify import notify
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.platform.models import Tenant

MAX_ROWS = 50_000
MAX_BYTES = 20 * 1024 * 1024
BATCH = 200
IDENTITY_TARGETS = {"phone", "whatsapp", "email", "linkedin"}
Policy = Literal["update", "skip", "create", "flag"]


def read_csv(text: str) -> tuple[list[str], list[list[str]]]:
    """Header names (made unique) and data rows (blank rows dropped, padded to the header)."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise Invalid("The file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = next(reader)
    except StopIteration:
        raise Invalid("The file is empty") from None
    names: list[str] = []
    for i, h in enumerate(header):
        name = (h or "").strip()[:100] or f"Column {i + 1}"
        base, n = name, 2
        while name in names:
            name, n = f"{base} ({n})", n + 1
        names.append(name)
    rows = []
    try:
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if len(rows) >= MAX_ROWS:
                raise Invalid(f"The file has more than {MAX_ROWS:,} rows. Split it into parts")
            cells = [c.strip()[:4000] for c in row[: len(names)]]
            rows.append(cells + [""] * (len(names) - len(cells)))
    except csv.Error as e:
        raise Invalid(f"The file could not be read as CSV: {e}") from None
    if not rows:
        raise Invalid("The file has a header but no rows")
    return names, rows


async def create(
    db: AsyncSession, actor: CurrentUser, file_name: str, text: str
) -> tuple[Import, list[list[str]]]:
    if len(text.encode()) > MAX_BYTES:
        raise Invalid("The file is larger than 20 MB. Split it into parts")
    headers, rows = read_csv(text)
    imp = Import(
        tenant_id=actor.user.tenant_id,
        file_name=file_name.strip()[:200] or "import.csv",
        headers=headers,
        row_count=len(rows),
        created_by_user_id=actor.user.id,
        mapping={},
        options={},
    )
    db.add(imp)
    await db.flush()
    for start in range(0, len(rows), 1000):
        await db.execute(
            insert(ImportRow),
            [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": imp.tenant_id,
                    "import_id": imp.id,
                    "row_number": start + i + 2,  # as the spreadsheet shows it (header = 1)
                    "data": row,
                    "status": "pending",
                }
                for i, row in enumerate(rows[start : start + 1000])
            ],
        )
    return imp, rows[:5]


async def check_mapping(
    db: AsyncSession, actor: CurrentUser, imp: Import, mapping: dict[str, str], options: dict
) -> None:
    defs = await L.lead_fields(db)
    allowed = set(MP.BUILTIN_TARGETS) | set(MP.IMPORT_ONLY_TARGETS) | {f"cf.{k}" for k in defs}
    for column, target in mapping.items():
        if column not in imp.headers:
            raise Invalid(f"There is no column '{column}' in the file")
        if target not in allowed:
            raise Invalid(f"'{target}' is not a field you can import into")
    rules = await A.rules(db, actor, "lead")
    for name, (label, attrs) in A.builtins("lead").items():
        if not rules.editable(name) and set(attrs) & set(mapping.values()):
            raise Invalid(f"You can't import into {label}")
    for target in mapping.values():
        if target.startswith("cf.") and not rules.editable(target):
            raise Invalid(f"You can't import into {defs[target[3:]].label}")
    targets = set(mapping.values())
    if not targets & IDENTITY_TARGETS:
        raise Invalid("Match at least one column to a phone, email or LinkedIn field")
    if "source" not in targets and not options.get("source_id"):
        raise Invalid("Choose a source for these leads, or match a Source column")
    if (
        options.get("unknown_values") == "note"
        and "source" in targets
        and not options.get("source_id")
    ):
        raise Invalid("Choose a source for rows whose source isn't in Core")
    if options.get("source_id"):
        source = await db.get(LeadSource, uuid.UUID(options["source_id"]))
        if source is None or not source.is_active:
            raise Invalid("Choose an active source")
    if options.get("stage_id") and await db.get(LeadStage, uuid.UUID(options["stage_id"])) is None:
        raise Invalid("Choose a stage from the list")
    can_assign = L.can(actor, "leads.assign")
    owner = options.get("owner", "me")
    if (owner != "me" or "owner_email" in targets) and not can_assign:
        raise Invalid("You can only import leads for yourself")
    if owner not in ("me", "rules", "none"):
        await L.check_assignable(db, actor, uuid.UUID(owner))


async def load_actor(db: AsyncSession, user_id: uuid.UUID) -> CurrentUser | None:
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        return None
    role = await db.get(Role, user.role_id)
    return CurrentUser(
        user=user, role=role, restrictions=[], permissions=await effective_permissions(db, role)
    )


async def _row(
    db: AsyncSession,
    actor: CurrentUser,
    imp: Import,
    row: ImportRow,
    lookups: dict,
) -> None:
    opts = imp.options
    keep = opts.get("unknown_values") == "note"  # a CRM export: unknown values go to a note
    notes_from = [c for c in imp.headers if imp.mapping.get(c) == "message"]
    values: dict[str, list[str]] = {}
    for i, column in enumerate(imp.headers):
        target = imp.mapping.get(column)
        if target and i < len(row.data):
            value = row.data[i]
            if target == "message" and len(notes_from) > 1 and value.strip():
                value = f"{column}: {value.strip()}"  # several note columns: say which is which
            values.setdefault(target, []).append(value)
    p = MP.parse(values, lookups["defs"])
    if p.problems and not keep:
        raise Invalid("; ".join(p.problems))
    unknown: list[str] = []  # values from the file that aren't in Core (keep mode)

    source_id = uuid.UUID(opts["source_id"]) if opts.get("source_id") else None
    if p.source:
        found = lookups["sources"].get(p.source.lower())
        if found is None and not keep:
            raise Invalid(f"Unknown source '{p.source}'")
        if found is None:
            unknown.append(f"Source in the file: {p.source}")
        source_id = found or source_id
    stage_id = uuid.UUID(opts["stage_id"]) if opts.get("stage_id") else None
    if p.stage:
        found = lookups["stages"].get(p.stage.lower())
        if found is None and not keep:
            raise Invalid(f"Unknown stage '{p.stage}'")
        if found is None:
            unknown.append(f"Stage in the file: {p.stage}")
        stage_id = found or stage_id

    owner: uuid.UUID | str | None
    choice = opts.get("owner", "me")
    named = None
    if p.owner_email:
        named = lookups["users"].get(p.owner_email.lower())
        if named is None and keep:  # CRM exports often give the owner's name, not email
            named = lookups["user_names"].get(" ".join(p.owner_email.lower().split()))
        if named is None and not keep:
            raise Invalid(f"No active person with the email {p.owner_email}")
        if named is None:
            unknown.append(f"Owner in the file: {p.owner_email}")
    if named is not None:
        owner = named
        await L.check_assignable(db, actor, owner)
    elif p.owner_email and keep:
        owner = I.RULES  # the owner isn't in Core: the assignment rules decide
    elif choice == "me":
        owner = actor.user.id
    elif choice == "rules":
        owner = I.RULES
    elif choice == "none":
        owner = None
    else:
        owner = uuid.UUID(choice)

    inc = I.Incoming(
        identities=p.identities,
        source_id=source_id,
        created_via="csv",
        fields=p.fields,
        custom_fields=p.custom_fields,
        stage_id=stage_id,
        origin="outside",
        owner=owner,
        consents=p.consents,
        consent_wording=f"Recorded in the imported file {imp.file_name}",
        external=("csv", p.external_id) if p.external_id else None,
        message="\n".join(p.message_parts + unknown) or None,
        via_label=f"import of {imp.file_name}",
    )
    out = await I.intake(
        db, imp.tenant_id, inc, policy=opts.get("duplicate_policy", "update"), actor=actor
    )
    row.status = {"created": "created", "flagged": "created", "updated": "updated"}.get(
        out.result, "skipped"
    )
    row.lead_id = out.lead.id if out.lead else (out.match.id if out.match else None)
    row.message = out.message or (
        "Possible duplicate, flagged" if out.result == "flagged" else None
    )


async def _lookups(db: AsyncSession) -> dict:
    people = (
        await db.execute(select(User.email, User.name, User.id).where(User.status == "active"))
    ).all()
    names: dict[str, uuid.UUID | None] = {}
    for _, name, i in people:
        n = " ".join((name or "").lower().split())
        if n:
            names[n] = None if n in names else i  # two people with one name: neither
    return {
        "defs": await L.lead_fields(db),
        "sources": {
            n.lower(): i
            for n, i in (await db.execute(select(LeadSource.name, LeadSource.id))).all()
        },
        "stages": {
            n.lower(): i for n, i in (await db.execute(select(LeadStage.name, LeadStage.id))).all()
        },
        "users": {e.lower(): i for e, _, i in people},
        "user_names": {n: i for n, i in names.items() if i is not None},  # unique names only
    }


async def run_import(tenant_id: str | uuid.UUID, import_id: str | uuid.UUID) -> dict:
    tenant_id, import_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(import_id))
    async with tenant_session(tenant_id) as db:
        imp = await db.scalar(
            select(Import).where(Import.id == import_id).with_for_update(skip_locked=True)
        )
        if imp is None or imp.status not in ("queued", "running"):
            return {"skipped": True}
        imp.status, imp.started_at = "running", imp.started_at or L.now()

    while True:
        async with tenant_session(tenant_id) as db:
            imp = await db.get(Import, import_id)
            if imp.status != "running":
                return {"stopped": imp.status}
            actor = await load_actor(db, imp.created_by_user_id)
            rows = (
                await db.scalars(
                    select(ImportRow)
                    .where(ImportRow.import_id == imp.id, ImportRow.status == "pending")
                    .order_by(ImportRow.row_number)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)  # two runners never take the same row
                )
            ).all()
            if actor is None:
                break
            if not rows:
                pending = await db.scalar(
                    select(func.count())
                    .select_from(ImportRow)
                    .where(ImportRow.import_id == imp.id, ImportRow.status == "pending")
                )
                if pending:
                    return {"busy": True}  # another runner holds the last rows; it finishes
                break
            lookups = await _lookups(db)
            for row in rows:
                try:
                    async with db.begin_nested():
                        await _row(db, actor, imp, row, lookups)
                except DomainError as e:
                    row.status, row.message = "failed", e.detail[:500]
                except (ValueError, KeyError) as e:  # a malformed option; never stop the batch
                    row.status, row.message = "failed", f"Could not read this row ({e})"[:500]
            await _count(db, imp)

    async with tenant_session(tenant_id) as db:
        imp = await db.get(Import, import_id)
        await _count(db, imp)
        if actor is None:
            imp.status = "cancelled"  # the person who started it is no longer active
        else:
            imp.status = "done"
        imp.finished_at = L.now()
        await notify(
            db,
            tenant_id,
            [imp.created_by_user_id],
            "import_done",
            f"Import of {imp.file_name} finished: {imp.created_count} added, "
            f"{imp.updated_count} updated, {imp.skipped_count} skipped, {imp.failed_count} failed",
        )
        return {
            "created": imp.created_count,
            "updated": imp.updated_count,
            "skipped": imp.skipped_count,
            "failed": imp.failed_count,
        }


async def _count(db: AsyncSession, imp: Import) -> None:
    await db.flush()
    counts = dict(
        (
            await db.execute(
                select(ImportRow.status, func.count())
                .where(ImportRow.import_id == imp.id)
                .group_by(ImportRow.status)
            )
        ).all()
    )
    imp.created_count = counts.get("created", 0)
    imp.updated_count = counts.get("updated", 0)
    imp.skipped_count = counts.get("skipped", 0)
    imp.failed_count = counts.get("failed", 0)


async def run_queued_imports() -> int:
    """The minute sweep: imports that were queued but never picked up, or whose worker died."""
    async with platform_session() as s:
        tenant_ids = (await s.scalars(select(Tenant.id).where(Tenant.status == "active"))).all()
    ran = 0
    for tenant_id in tenant_ids:
        async with tenant_session(tenant_id) as db:
            stale = L.now() - timedelta(minutes=10)
            ids = (
                await db.scalars(
                    select(Import.id).where(
                        (Import.status == "queued")
                        | ((Import.status == "running") & (Import.updated_at < stale))
                    )
                )
            ).all()
        for import_id in ids:
            await run_import(tenant_id, import_id)
            ran += 1
    return ran


def failed_rows_csv(imp: Import, rows: list[ImportRow]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([*imp.headers, "Result", "Why"])
    for r in rows:
        writer.writerow([*r.data, r.status, r.message or ""])
    return out.getvalue()

"""CSV import API. The browser reads the file and sends its text (no file storage yet, #22)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import CurrentUser, require
from app.modules.crm import imports as IM
from app.modules.crm import mapping as MP
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.leads import lead_fields
from app.modules.crm.models import Import, ImportRow

router = APIRouter(prefix="/api/v1/imports", tags=["imports"], dependencies=CRM)
Importer = Annotated[CurrentUser, require("leads.import")]


class UploadIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=IM.MAX_BYTES)


class Target(BaseModel):
    key: str
    label: str


class ImportOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    file_name: str
    headers: list[str]
    row_count: int
    mapping: dict
    options: dict
    status: str
    created_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    created_by_user_id: uuid.UUID
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class UploadOut(ImportOut):
    sample: list[list[str]]
    suggested: dict[str, str]
    targets: list[Target]


async def _targets(db) -> list[Target]:
    defs = await lead_fields(db)
    builtin = MP.BUILTIN_TARGETS | MP.IMPORT_ONLY_TARGETS
    return [Target(key=k, label=v) for k, v in builtin.items()] + [
        Target(key=f"cf.{d.key}", label=d.label)
        for d in sorted(defs.values(), key=lambda d: d.position)
    ]


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload(body: UploadIn, db: CrmDb, actor: Importer) -> UploadOut:
    imp, sample = await IM.create(db, actor, body.file_name, body.content)
    await db.flush()
    await db.refresh(imp)
    defs = list((await lead_fields(db)).values())
    return UploadOut(
        **ImportOut.model_validate(imp).model_dump(),
        sample=sample,
        suggested=MP.suggest(imp.headers, defs, import_mode=True),
        targets=await _targets(db),
    )


async def _visible(db, actor: CurrentUser, import_id: uuid.UUID) -> Import:
    imp = await db.get(Import, import_id)
    if imp is None or (actor.role.scope != "all" and imp.created_by_user_id != actor.user.id):
        raise NotFound("Import not found")
    return imp


@router.get("", response_model=list[ImportOut])
async def list_imports(db: CrmDb, actor: Importer) -> list[Import]:
    q = select(Import).order_by(Import.created_at.desc()).limit(50)
    if actor.role.scope != "all":
        q = q.where(Import.created_by_user_id == actor.user.id)
    return list((await db.scalars(q)).all())


@router.get("/{import_id}", response_model=ImportOut)
async def get_import(import_id: uuid.UUID, db: CrmDb, actor: Importer) -> Import:
    return await _visible(db, actor, import_id)


class StartIn(BaseModel):
    mapping: dict[str, str] = Field(max_length=200)  # column → target
    source_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    duplicate_policy: Literal["update", "skip", "create", "flag"] = "update"
    owner: str = "me"  # me / rules / none / a user id


@router.post("/{import_id}/start", response_model=ImportOut)
async def start(import_id: uuid.UUID, body: StartIn, db: CrmDb, actor: Importer) -> Import:
    imp = await _visible(db, actor, import_id)
    if imp.created_by_user_id != actor.user.id:
        raise Invalid("Only the person who uploaded the file can start it")
    if imp.status != "uploaded":
        raise Invalid("This import has already started")
    mapping = {c: t for c, t in body.mapping.items() if t}
    options = {
        "source_id": str(body.source_id) if body.source_id else None,
        "stage_id": str(body.stage_id) if body.stage_id else None,
        "duplicate_policy": body.duplicate_policy,
        "owner": body.owner,
    }
    if body.owner not in ("me", "rules", "none"):
        try:
            uuid.UUID(body.owner)
        except ValueError:
            raise Invalid("Choose who owns the imported leads") from None
    await IM.check_mapping(db, actor, imp, mapping, options)
    imp.mapping, imp.options, imp.status = mapping, options, "queued"
    await audit(db, actor, "import.started", "import", imp.id, None, {"rows": imp.row_count})
    await db.flush()
    await db.refresh(imp)
    await _enqueue(actor.user.tenant_id, imp.id)
    return imp


async def _enqueue(tenant_id: uuid.UUID, import_id: uuid.UUID) -> None:
    """Start at once if the queue is reachable; the worker's minute sweep is the fallback.
    Runs after the request's transaction commits (the job re-checks the status)."""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        await pool.enqueue_job(
            "import_job", str(tenant_id), str(import_id), _job_id=f"import:{import_id}", _defer_by=2
        )
        await pool.aclose()
    except Exception:  # noqa: BLE001 — the sweep picks it up within a minute
        pass


@router.post("/{import_id}/cancel", response_model=ImportOut)
async def cancel(import_id: uuid.UUID, db: CrmDb, actor: Importer) -> Import:
    """Stops after the current batch; leads already imported stay."""
    imp = await _visible(db, actor, import_id)
    if imp.status not in ("uploaded", "queued", "running"):
        raise Invalid("This import has finished")
    imp.status, imp.finished_at = "cancelled", IM.L.now()
    await audit(db, actor, "import.cancelled", "import", imp.id)
    await db.flush()
    await db.refresh(imp)
    return imp


@router.get("/{import_id}/problems", response_class=PlainTextResponse)
async def problem_rows(import_id: uuid.UUID, db: CrmDb, actor: Importer) -> PlainTextResponse:
    """The failed and skipped rows as a CSV with a 'Why' column, to fix and import again."""
    imp = await _visible(db, actor, import_id)
    rows = (
        await db.scalars(
            select(ImportRow)
            .where(ImportRow.import_id == imp.id, ImportRow.status.in_(["failed", "skipped"]))
            .order_by(ImportRow.row_number)
        )
    ).all()
    name = imp.file_name.rsplit(".", 1)[0][:80].replace('"', "")
    return PlainTextResponse(
        IM.failed_rows_csv(imp, list(rows)),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}-problems.csv"'},
    )


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(import_id: uuid.UUID, db: CrmDb, actor: Importer) -> None:
    """Remove the uploaded rows (personal data) once you no longer need them. The leads stay."""
    imp = await _visible(db, actor, import_id)
    if imp.status in ("queued", "running"):
        raise Invalid("Cancel the import first")
    await db.delete(imp)
    await audit(db, actor, "import.deleted", "import", import_id, {"file": imp.file_name})

"""Custom reports endpoints (finishing plan, batch 5c).

- `GET /reports/catalogue`: what this person may report on (sources, groupings, measures).
- `POST /reports/run` and `POST /reports/run.csv`: run a definition (live preview, download).
- Saved reports: anyone saves their own; sharing with roles needs `dashboards.business` or
  `settings.manage`. A shared report always runs with the viewer's own visibility.
"""

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.errors import Forbidden, Invalid, NotFound
from app.modules.auth.deps import ActiveUser, CurrentUser
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.reports import custom as R
from app.modules.reports.models import SavedReport
from app.modules.roles.models import Role

router = APIRouter(prefix="/api/v1/reports", tags=["reports"], dependencies=CRM)
SHARERS = ("dashboards.business", "settings.manage")


class SavedReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    definition: R.ReportDefinition
    shared_role_ids: list[uuid.UUID] = Field(default=[], max_length=50)


class SavedReportOut(BaseModel):
    id: uuid.UUID
    name: str
    definition: R.ReportDefinition
    shared_role_ids: list[uuid.UUID]
    owner_user_id: uuid.UUID
    yours: bool
    updated_at: datetime


def _out(row: SavedReport, actor: CurrentUser) -> SavedReportOut:
    return SavedReportOut(
        id=row.id, name=row.name, definition=R.parse(row.definition),
        shared_role_ids=[uuid.UUID(r) for r in row.shared_role_ids or []],
        owner_user_id=row.owner_user_id, yours=row.owner_user_id == actor.user.id,
        updated_at=row.updated_at,
    )  # fmt: skip


def _may_share(actor: CurrentUser) -> bool:
    return any(L.can(actor, code) for code in SHARERS)


async def _check_sharing(db, actor: CurrentUser, role_ids: list[uuid.UUID]) -> list[str]:
    if not role_ids:
        return []
    if not _may_share(actor):
        raise Forbidden("Only people who see the business dashboard can share reports")
    found = set((await db.scalars(select(Role.id).where(Role.id.in_(role_ids)))).all())
    if found != set(role_ids):
        raise Invalid("Choose roles of this company", code="report_invalid")
    return [str(r) for r in role_ids]


async def _readable(db, actor: CurrentUser, report_id: uuid.UUID) -> SavedReport:
    row = await db.get(SavedReport, report_id)
    if row is None or not (
        row.owner_user_id == actor.user.id or str(actor.role.id) in (row.shared_role_ids or [])
    ):
        raise NotFound("Report not found")
    return row


async def _writable(db, actor: CurrentUser, report_id: uuid.UUID) -> SavedReport:
    row = await _readable(db, actor, report_id)
    if row.owner_user_id != actor.user.id and not L.can(actor, "settings.manage"):
        raise Forbidden("Only the person who made this report can change it")
    return row


@router.get("/catalogue", response_model=list[R.ReportSource])
async def catalogue(db: CrmDb, actor: ActiveUser) -> list[R.ReportSource]:
    return await R.catalogue(db, actor)


@router.post("/run", response_model=R.ReportResult)
async def run(body: R.ReportDefinition, db: CrmDb, actor: ActiveUser) -> R.ReportResult:
    return await R.run(db, actor, body)


def _csv(result: R.ReportResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(result.columns)
    for row in result.rows:
        cells = [*row.labels, *([row.currency] if result.money else []), row.value]
        # a cell starting with = + - @ would run as a formula in a spreadsheet
        w.writerow([f"'{c}" if isinstance(c, str) and c[:1] in "=+-@\t\r" else c for c in cells])
    return buf.getvalue()


@router.post("/run.csv", response_class=Response)
async def run_csv(body: R.ReportDefinition, db: CrmDb, actor: ActiveUser) -> Response:
    result = await R.run(db, actor, body)
    await audit(db, actor, "report.downloaded", "report", None, after={"source": body.source})
    return Response(
        _csv(result), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="report.csv"'},
    )  # fmt: skip


@router.get("/saved", response_model=list[SavedReportOut])
async def list_saved(db: CrmDb, actor: ActiveUser) -> list[SavedReportOut]:
    rows = (
        await db.scalars(
            select(SavedReport)
            .where(
                or_(
                    SavedReport.owner_user_id == actor.user.id,
                    SavedReport.shared_role_ids.contains([str(actor.role.id)]),
                )
            )
            .order_by(SavedReport.name)
        )
    ).all()
    return [_out(r, actor) for r in rows]


@router.post("/saved", response_model=SavedReportOut, status_code=status.HTTP_201_CREATED)
async def create_saved(body: SavedReportIn, db: CrmDb, actor: ActiveUser) -> SavedReportOut:
    await R.run(db, actor, body.definition)  # refuses what this person can't report on
    row = SavedReport(
        id=uuid.uuid4(), tenant_id=actor.user.tenant_id, owner_user_id=actor.user.id,
        name=body.name.strip(), definition=body.definition.model_dump(mode="json"),
        shared_role_ids=await _check_sharing(db, actor, body.shared_role_ids),
    )  # fmt: skip
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _out(row, actor)


@router.get("/saved/{report_id}", response_model=SavedReportOut)
async def get_saved(report_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> SavedReportOut:
    return _out(await _readable(db, actor, report_id), actor)


@router.put("/saved/{report_id}", response_model=SavedReportOut)
async def update_saved(
    report_id: uuid.UUID, body: SavedReportIn, db: CrmDb, actor: ActiveUser
) -> SavedReportOut:
    row = await _writable(db, actor, report_id)
    await R.run(db, actor, body.definition)
    shared = await _check_sharing(db, actor, body.shared_role_ids) if body.shared_role_ids else []
    if row.shared_role_ids and not shared and not _may_share(actor):
        shared = row.shared_role_ids  # only a sharer can stop sharing it, too
    row.name, row.definition = body.name.strip(), body.definition.model_dump(mode="json")
    row.shared_role_ids = shared
    await db.flush()
    await db.refresh(row)
    return _out(row, actor)


@router.delete("/saved/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved(report_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> None:
    await db.delete(await _writable(db, actor, report_id))


@router.post("/saved/{report_id}/run", response_model=R.ReportResult)
async def run_saved(report_id: uuid.UUID, db: CrmDb, actor: ActiveUser) -> R.ReportResult:
    """Runs with the viewer's own visibility, whoever saved it."""
    row = await _readable(db, actor, report_id)
    return await R.run(db, actor, R.parse(row.definition))

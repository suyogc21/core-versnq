"""API and webhook logs (Decision log #37).

The API log keeps one row for every request made with an API key; webhook deliveries are the
webhook log. Both stay in the app for 30 days. Each night older rows are appended to a
compressed file per company and month (`<files>/_logs/<company>/api-2026-11.jsonl.gz`,
`webhooks-2026-11.jsonl.gz`) and removed from the database; files older than 12 months are
deleted. The folder sits outside the companies' upload folders, so the upload clean-up never
touches it.
"""

import gzip
import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip
from app.core.storage import root
from app.core.tenancy import tenant_session
from app.modules.integrations.models import ApiRequestLog, WebhookDelivery

LIVE_DAYS = 30
KEEP_MONTHS = 12
BATCH = 5000


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def api_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        found = getattr(request.state, "api_key", None)
        if found:
            tenant_id, key_id = found
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            try:
                async with tenant_session(tenant_id) as db:
                    db.add(
                        ApiRequestLog(
                            tenant_id=tenant_id,
                            key_id=key_id,
                            method=request.method[:8],
                            path=path[:500],
                            status=response.status_code,
                            duration_ms=int((time.perf_counter() - started) * 1000),
                            ip=client_ip(request)[:64],
                        )
                    )
            except Exception:  # noqa: BLE001  a log write must never break the answer
                pass
        return response


# ---------- archive ----------
def folder(tenant_id: uuid.UUID) -> Path:
    return root() / "_logs" / str(tenant_id)


def _append(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "at", encoding="utf-8") as fh:  # gzip members append cleanly
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")


def _api_row(r: ApiRequestLog) -> dict:
    return {
        "at": r.at, "key_id": r.key_id, "method": r.method, "path": r.path,
        "status": r.status, "duration_ms": r.duration_ms, "ip": r.ip,
    }  # fmt: skip


def _hook_row(d: WebhookDelivery) -> dict:
    return {
        "created_at": d.created_at, "endpoint_id": d.endpoint_id, "event_id": d.event_id,
        "event_type": d.event_type, "status": d.status, "attempts": d.attempts,
        "last_status_code": d.last_status_code, "last_error": d.last_error,
        "delivered_at": d.delivered_at, "body": d.body,
    }  # fmt: skip


async def _archive(db: AsyncSession, tenant_id: uuid.UUID, model, at_col, kind, to_row) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=LIVE_DAYS)
    done = 0
    while True:
        q = select(model).where(at_col < cutoff).order_by(at_col).limit(BATCH)
        if model is WebhookDelivery:
            q = q.where(WebhookDelivery.status != "pending")  # still retrying: keep
        rows = (await db.scalars(q)).all()
        if not rows:
            return done
        by_month: dict[str, list[dict]] = {}
        for r in rows:
            by_month.setdefault(f"{getattr(r, at_col.key):%Y-%m}", []).append(to_row(r))
        for month, items in by_month.items():
            _append(folder(tenant_id) / f"{kind}-{month}.jsonl.gz", items)
        await db.execute(delete(model).where(model.id.in_([r.id for r in rows])))
        await db.commit()
        done += len(rows)


def _drop_old_files(tenant_id: uuid.UUID, today: date) -> int:
    base = folder(tenant_id)
    if not base.exists():
        return 0
    oldest = f"{today.year - 1}-{today.month:02d}"  # keep the last 12 months
    removed = 0
    for p in base.glob("*.jsonl.gz"):
        month = p.name.split("-", 1)[1][:7]
        if month < oldest:
            p.unlink()
            removed += 1
    return removed


async def archive_tenant(tenant_id: uuid.UUID) -> dict:
    async with tenant_session(tenant_id) as db:
        api = await _archive(db, tenant_id, ApiRequestLog, ApiRequestLog.at, "api", _api_row)
        hooks = await _archive(
            db, tenant_id, WebhookDelivery, WebhookDelivery.created_at, "webhooks", _hook_row
        )
    removed = _drop_old_files(tenant_id, datetime.now(UTC).date())
    return {"api": api, "webhooks": hooks, "files_removed": removed}


def archives(tenant_id: uuid.UUID) -> list[dict]:
    base = folder(tenant_id)
    if not base.exists():
        return []
    out = []
    for p in sorted(base.glob("*.jsonl.gz"), reverse=True):
        kind, month = p.name.removesuffix(".jsonl.gz").split("-", 1)
        out.append({"name": p.name, "kind": kind, "month": month, "size": p.stat().st_size})
    return out


def archive_path(tenant_id: uuid.UUID, name: str) -> Path | None:
    p = folder(tenant_id) / name
    if "/" in name or not name.endswith(".jsonl.gz") or not p.is_file():
        return None
    return p

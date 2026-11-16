"""Security (finishing plan, batch 1): sign-in history, the company's security settings (idle
sign-out, IP allowlist, failed sign-in alerts), "export everything", and erasing a person.

Nothing here ever stores or exports a password, token, secret or encrypted key.
"""

import ipaddress
import json
import logging
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import Base
from app.core.mailer import Email, Mailer
from app.core.tenancy import tenant_session
from app.modules.security.models import DataExport, SignIn
from app.modules.settings.models import TenantSettings

log = logging.getLogger(__name__)

DEFAULTS = {"idle_minutes": 0, "ip_allowlist": [], "alert_failed_sign_ins": True}
KEEP_SIGN_INS = timedelta(days=180)
EXPORT_DAYS = 7
FAILED_ALERT_AT = 5  # the same number login stops at (auth.router FAILS_PER_ACCOUNT)


def now() -> datetime:
    return datetime.now(UTC)


# ---------- settings ----------
async def settings_of(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    s = await db.get(TenantSettings, tenant_id)
    return {**DEFAULTS, **((s.security if s else None) or {})}


def networks(allowlist: list[str]) -> list[ipaddress._BaseNetwork]:
    return [ipaddress.ip_network(a, strict=False) for a in allowlist]


def ip_allowed(settings: dict, ip: str | None) -> bool:
    """No allowlist = everyone. Otherwise the address must be in one of the ranges."""
    allow = settings.get("ip_allowlist") or []
    if not allow:
        return True
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    return any(addr in net for net in networks(allow))


# ---------- sign-in history ----------
async def record_sign_in(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    email: str,
    user_id: uuid.UUID | None,
    success: bool,
    method: str,
    reason: str | None,
    ip: str | None,
    user_agent: str | None,
) -> None:
    db.add(
        SignIn(
            id=uuid.uuid4(), tenant_id=tenant_id, user_id=user_id, email=email.lower()[:320],
            success=success, method=method, reason=reason, ip=ip,
            user_agent=(user_agent or "")[:400] or None,
        )
    )  # fmt: skip


async def alert_failed_sign_ins(
    db: AsyncSession, mailer: Mailer, tenant_id: uuid.UUID, user, workspace_name: str, ip: str
) -> None:
    """The 5th failed try in 15 minutes: the person and the company's admins get an email."""
    from app.modules.roles.models import Role
    from app.modules.users.models import User

    if not (await settings_of(db, tenant_id))["alert_failed_sign_ins"]:
        return
    admin_emails = await db.scalars(
        select(User.email)
        .join(Role, Role.id == User.role_id)
        .where(Role.key.in_(["owner", "admin"]), User.status == "active")
    )
    to = {user.email, *admin_emails.all()}
    body = (
        f"There were {FAILED_ALERT_AT} failed sign-in attempts to {user.email} at "
        f"{workspace_name} on Versnq Core in the last 15 minutes, from the address {ip}.\n\n"
        "Sign-in to that account is paused for 15 minutes. If this wasn't you or your "
        "colleague, change the password and turn on two-factor authentication. Admins can see "
        "every sign-in under Settings → Security.\n"
    )
    for address in to:
        try:
            await mailer.send(Email(to=address, subject="Failed sign-in attempts", body=body))
        except Exception:  # noqa: BLE001 — an alert email must never break sign-in
            log.exception("Failed sign-in alert to %s", address)


async def prune(db: AsyncSession) -> int:
    """Nightly: sign-ins older than 180 days go; expired exports are deleted."""
    gone = await db.execute(delete(SignIn).where(SignIn.created_at < now() - KEEP_SIGN_INS))
    old = (
        await db.scalars(
            select(DataExport).where(DataExport.expires_at < now(), DataExport.path.is_not(None))
        )
    ).all()
    for e in old:
        export_file(e.path).unlink(missing_ok=True)
        e.path, e.status = None, "expired"
    return gone.rowcount or 0


# ---------- export everything ----------
SKIP_TABLES = {
    "user_sessions", "auth_tokens", "user_recovery_codes", "extension_tokens", "phone_devices",
    "api_keys", "push_subscriptions", "data_exports", "events", "webhook_deliveries",
    "api_request_logs", "import_rows",
}  # fmt: skip
SECRET_WORDS = ("password", "secret", "token", "_enc", "hash", "totp", "private_key")


def _secret(column: str) -> bool:
    return any(word in column for word in SECRET_WORDS)


def export_file(rel: str) -> Path:
    path = (storage.root() / "_exports" / rel).resolve()
    if (storage.root() / "_exports").resolve() not in path.parents:
        raise ValueError("bad export path")
    return path


def _json(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return None
    return value


async def build_export(tenant_id: uuid.UUID, export_id: uuid.UUID) -> None:
    """Worker: every table of this company as JSON lines, plus its stored files, in one zip.
    Secret columns and login/key tables are left out."""
    rel = f"{tenant_id}/{export_id}.zip"
    path = export_file(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with tenant_session(tenant_id) as db:
            row = await db.get(DataExport, export_id)
            if row is None or row.status not in ("queued", "failed"):
                return
            row.status = "running"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            tables = sorted(Base.metadata.tables.values(), key=lambda t: t.name)
            for table in tables:
                if "tenant_id" not in table.c or table.name in SKIP_TABLES:
                    continue
                cols = [c for c in table.c if not _secret(c.name)]
                async with tenant_session(tenant_id) as db:
                    result = await db.stream(select(*cols).where(table.c.tenant_id == tenant_id))
                    with z.open(f"data/{table.name}.jsonl", "w") as fh:
                        async for r in result:
                            line = {k: _json(v) for k, v in r._mapping.items()}
                            fh.write((json.dumps(line, default=str) + "\n").encode())
            for rel_file in storage.stored_paths(tenant_id):
                z.write(storage.full_path(rel_file), f"files/{rel_file.split('/', 1)[1]}")
            z.writestr(
                "README.txt",
                "Everything your company keeps in Versnq Core.\n\n"
                "data/: one file per kind of record, one JSON object per line.\n"
                "files/: uploaded files, call recordings and documents.\n"
                "Passwords, sign-in tokens and connected-account keys are never included.\n",
            )
        async with tenant_session(tenant_id) as db:
            row = await db.get(DataExport, export_id)
            row.status, row.path, row.size_bytes = "ready", rel, path.stat().st_size
            row.finished_at, row.expires_at = now(), now() + timedelta(days=EXPORT_DAYS)
    except Exception as e:  # noqa: BLE001
        log.exception("Export %s failed", export_id)
        path.unlink(missing_ok=True)
        async with tenant_session(tenant_id) as db:
            row = await db.get(DataExport, export_id)
            if row:
                row.status, row.error, row.finished_at = "failed", type(e).__name__, now()


# ---------- erase a person ----------
async def erase_lead(db: AsyncSession, lead) -> None:
    """Erase a person (DPDP / GDPR): their details, timeline, messages, calls, recordings, files,
    tags, tasks and consents are deleted. The lead row stays as "Erased person" because deals,
    invoices and payments (amounts and dates only) must be kept for tax law."""
    from app.modules.calls.models import Call
    from app.modules.crm import models as M
    from app.modules.engage import models as E

    lid = lead.id
    tables = Base.metadata.tables

    # files on disk first, then their rows
    files = await db.scalars(select(M.StoredFile.path).where(M.StoredFile.lead_id == lid))
    recordings = await db.scalars(select(Call.recording_path).where(Call.lead_id == lid))
    paths = [*files.all(), *(p for p in recordings.all() if p)]
    msg_ids = select(E.Message.id).where(E.Message.lead_id == lid)
    att = tables["message_attachments"]
    await db.execute(delete(att).where(att.c.message_id.in_(msg_ids)))
    await db.execute(delete(E.Message).where(E.Message.lead_id == lid))
    await db.execute(delete(Call).where(Call.lead_id == lid))
    for name in (
        "activities", "lead_identities", "tasks", "consents", "external_refs", "lead_slas",
        "notifications", "taggings", "enrolments", "conversations", "whatsapp_chat_links",
        "account_contacts", "automation_runs", "files", "contacts",
    ):  # fmt: skip
        t = tables[name]
        await db.execute(delete(t).where(t.c.lead_id == lid))
    links = tables["links"]
    either = (links.c.from_lead_id == lid) | (links.c.to_lead_id == lid)
    await db.execute(delete(links).where(either))
    rows = tables["import_rows"]
    await db.execute(update(rows).where(rows.c.lead_id == lid).values(data={}, lead_id=None))
    customers = tables["customers"]
    await db.execute(update(customers).where(customers.c.lead_id == lid).values(custom_fields={}))
    deals = tables["deals"]
    await db.execute(
        update(deals).where(deals.c.lead_id == lid).values(name="Erased person", custom_fields={})
    )
    invoices = tables["invoices"]
    await db.execute(update(invoices).where(invoices.c.lead_id == lid).values(notes=None))

    for field in (
        "first_name", "last_name", "org_name", "website", "primary_email", "primary_phone",
        "city", "region", "campaign", "utm_source", "utm_medium", "utm_campaign", "utm_term",
        "utm_content", "unqualified_reason", "ace_summary", "ace_next_step", "intent",
        "preferred_language", "industry", "employee_range",
    ):  # fmt: skip
        setattr(lead, field, None)
    lead.display_name, lead.custom_fields, lead.attribution = "Erased person", {}, {}
    lead.is_open, lead.next_follow_up_at, lead.erased_at = False, None, now()
    lead.email_consent = lead.whatsapp_consent = None
    lead.version += 1
    await db.flush()
    for p in paths:
        storage.remove(p)


async def person_data(db: AsyncSession, lead) -> dict:
    """One person's data as plain JSON (no secrets, no internal-only columns)."""
    tables = Base.metadata.tables
    skip = {"tenant_id", "version", "leak_alerted_at", "org_suggestions_dismissed"}

    def clean(row) -> dict:
        return {k: _json(v) for k, v in row._mapping.items() if k not in skip and not _secret(k)}

    async def rows(name: str, where) -> list[dict]:
        t = tables[name]
        result = await db.execute(select(t).where(where(t)).limit(5000))
        return [clean(r) for r in result]

    lid = lead.id
    lead_row = (await db.execute(select(tables["leads"]).where(tables["leads"].c.id == lid))).one()
    by_lead = lambda t: t.c.lead_id == lid  # noqa: E731
    return {
        "exported_at": now().isoformat(),
        "person": clean(lead_row),
        "contact_points": await rows("lead_identities", by_lead),
        "consents": await rows("consents", by_lead),
        "timeline": await rows("activities", by_lead),
        "messages": await rows("messages", by_lead),
        "calls": [
            {k: v for k, v in c.items() if not k.startswith("recording_")}
            for c in await rows("calls", by_lead)
        ],
        "deals": await rows("deals", by_lead),
        "invoices": await rows("invoices", by_lead),
        "payments": await rows("payments", by_lead),
        "tasks": await rows("tasks", by_lead),
    }

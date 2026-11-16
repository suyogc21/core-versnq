"""Lead ads (finishing plan, batch 5d): leads from Facebook/Instagram lead forms and Google Ads
lead forms go through the same intake as every other lead (routing, duplicates, consent).

Facebook: Meta's webhook only says "lead <id> arrived on page <page>"; Core then reads the
lead's answers from the Graph API with the Page's token. Google: the webhook carries the
answers itself. Each provider lead id is kept once (lead_ad_leads), so a repeat is ignored,
and a Facebook lead whose read failed is retried by the worker (5 tries).

Meta / Google API details here are as documented publicly and remembered, NOT checked against
live accounts; each such place says UNVERIFIED.
"""

import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets as SEC
from app.core.config import get_settings
from app.core.errors import DomainError
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm import mapping as MP
from app.modules.leadads.models import LeadAdLead, LeadAdSource
from app.modules.settings.models import TenantSettings

log = logging.getLogger(__name__)
MAX_TRIES = 5
GRAPH = "https://graph.facebook.com"
AD_KEYS = ("ad_id", "ad_name", "adset_id", "campaign_id", "campaign_name", "form_id", "platform")
# UNVERIFIED: the fields a Lead object returns when asked for them.
LEAD_FIELDS = (
    "id,created_time,field_data,ad_id,ad_name,adset_id,campaign_id,campaign_name,form_id,platform"
)
# Google's column ids (UNVERIFIED list, from Google's lead form webhook docs as remembered).
GOOGLE_COLUMNS = {
    "FULL_NAME": "full_name",
    "FIRST_NAME": "first_name",
    "LAST_NAME": "last_name",
    "EMAIL": "email",
    "WORK_EMAIL": "email",
    "PHONE_NUMBER": "phone",
    "WORK_PHONE": "phone",
    "CITY": "city",
    "REGION": "region",
    "COUNTRY": "country_code",
    "COMPANY_NAME": "org_name",
}


def now() -> datetime:
    return datetime.now(UTC)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ---------- Meta's signature ----------
def meta_signature_ok(secret: str | None, raw: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256: "sha256=" + HMAC-SHA256 of the raw body with the app secret."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    want = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header.removeprefix("sha256="))


def app_secret(src: LeadAdSource) -> str | None:
    if src.app_secret_enc:
        return SEC.decrypt(src.app_secret_enc)
    return get_settings().meta_leads_app_secret


# ---------- reading a Facebook lead ----------
class GraphClient:
    def __init__(self, src: LeadAdSource):
        self.token = SEC.decrypt(src.page_token_enc) if src.page_token_enc else ""

    async def lead(self, leadgen_id: str) -> dict:
        version = get_settings().meta_graph_version
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            r = await http.get(
                f"{GRAPH}/{version}/{leadgen_id}",
                params={"fields": LEAD_FIELDS, "access_token": self.token},
            )
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            msg = (data.get("error") or {}).get("message") or r.status_code
            raise RuntimeError(f"Meta said: {msg}")
        return data

    async def check_page(self, page_id: str) -> None:
        version = get_settings().meta_graph_version
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            r = await http.get(
                f"{GRAPH}/{version}/{page_id}",
                params={"fields": "id,name", "access_token": self.token},
            )
        if r.status_code >= 400:
            raise RuntimeError("Meta refused this Page id and token")


class TestGraph:
    """LEAD_ADS_MODE=test: nothing reaches Meta. Tests patch `lead` with their own answers."""

    def __init__(self, src: LeadAdSource):
        self.src = src

    async def lead(self, leadgen_id: str) -> dict:
        return {"id": leadgen_id, "field_data": [], "form_id": "test-form"}

    async def check_page(self, page_id: str) -> None:
        if self.src.page_token_enc and SEC.decrypt(self.src.page_token_enc).startswith(
            "wrong-token"
        ):
            raise RuntimeError("Meta refused this Page id and token")


def graph(src: LeadAdSource):  # patched in tests
    return TestGraph(src) if get_settings().lead_ads_mode == "test" else GraphClient(src)


# ---------- answers → a lead ----------
def facebook_answers(data: dict) -> tuple[dict[str, list[str]], dict[str, str]]:
    """field_data [{name, values}] → our targets; ad ids → attribution."""
    answers = {}
    for item in data.get("field_data") or []:
        name = str(item.get("name") or "")[:80]
        values = [str(v)[:500] for v in (item.get("values") or [])]
        if name:
            answers[name] = values
    attribution = {
        k: str(data[k])[:200]
        for k in (
            "ad_id",
            "ad_name",
            "adset_id",
            "campaign_id",
            "campaign_name",
            "form_id",
            "platform",
        )
        if data.get(k)
    }
    return answers, attribution


def google_answers(body: dict) -> tuple[dict[str, list[str]], dict[str, str]]:
    answers: dict[str, list[str]] = {}
    for col in body.get("user_column_data") or []:
        cid = str(col.get("column_id") or "")
        value = str(col.get("string_value") or "")[:500]
        name = GOOGLE_COLUMNS.get(cid) or str(col.get("column_name") or cid)[:80]
        if name and value:
            answers.setdefault(name, []).append(value)
    attribution = {
        k: str(body[k])[:200]
        for k in ("campaign_id", "adgroup_id", "creative_id", "form_id", "gcl_id")
        if body.get(k)
    }
    return answers, attribution


async def to_lead(
    db: AsyncSession,
    src: LeadAdSource,
    row: LeadAdLead,
    answers: dict[str, list[str]],
    attribution: dict[str, str],
) -> None:
    """The same intake as forms: known questions fill fields, others go to the note."""
    defs = await L.lead_fields(db)
    targets: dict[str, list[str]] = {}
    extras: list[str] = []
    for name, values in answers.items():
        normal = MP._norm(name)
        target = name if name in MP.BUILTIN_TARGETS else MP._ALIASES.get(normal)
        if target not in MP.BUILTIN_TARGETS:
            target = f"cf.{normal.replace(' ', '_')}" if normal.replace(" ", "_") in defs else None
        if target:
            targets.setdefault(target, []).extend(values)
        elif any(v.strip() for v in values):
            extras.append(f"{name}: {', '.join(values)[:500]}")
    p = MP.parse(targets, defs)
    settings = await db.get(TenantSettings, src.tenant_id)
    label = "Facebook ads" if src.provider == "facebook" else "Google ads"
    incoming = I.Incoming(
        identities=p.identities,
        source_id=src.source_id,
        created_via="form",
        fields=p.fields,
        custom_fields=p.custom_fields,
        stage_id=src.stage_id,
        origin="inbound",
        owner=I.RULES,
        consents={},
        external=(f"{src.provider}_ads", row.provider_lead_id),
        message="\n".join(p.message_parts + extras) or None,
        attribution={"ad_network": src.provider, **attribution},
        brand_id=src.brand_id,
        enforce_required=False,
        via_label=f"{label} ({src.name})",
    )
    async with db.begin_nested():
        out = await I.intake(
            db, src.tenant_id, incoming, policy=settings.duplicate_policy if settings else "update"
        )
    row.status, row.done_at, row.error = "done", now(), None
    row.lead_id = (out.lead or out.match).id if (out.lead or out.match) else None
    src.last_lead_at = now()


async def remember(
    db: AsyncSession, src: LeadAdSource, provider_lead_id: str, payload: dict
) -> LeadAdLead | None:
    """Keep the provider's lead id once. None: already seen (a repeat)."""
    new_id = uuid.uuid4()
    result = await db.execute(
        insert(LeadAdLead)
        .values(
            id=new_id,
            tenant_id=src.tenant_id,
            ad_source_id=src.id,
            provider=src.provider,
            provider_lead_id=provider_lead_id[:100],
            status="pending",
            tries=0,
            payload=payload,
        )
        .on_conflict_do_nothing(constraint="uq_lead_ad_leads")
        .returning(LeadAdLead.id)
    )
    if result.scalar() is None:
        return None
    return await db.get(LeadAdLead, new_id)


async def process(db: AsyncSession, src: LeadAdSource, row: LeadAdLead) -> None:
    """Make the lead. A failure is kept on the row; the worker tries again (5 tries)."""
    row.tries += 1
    try:
        if src.provider == "facebook":
            data = await graph(src).lead(row.provider_lead_id)
            answers, attribution = facebook_answers(data)
        else:
            answers, attribution = google_answers(row.payload)
        await to_lead(db, src, row, answers, attribution)
    except (DomainError, RuntimeError, httpx.HTTPError) as e:
        detail = getattr(e, "detail", None) or str(e) or type(e).__name__
        row.error = str(detail)[:300]
        row.status = "failed" if row.tries >= MAX_TRIES else "pending"
        log.info("Lead ad %s not made yet: %s", row.provider_lead_id, row.error)


async def retry_pending(db: AsyncSession) -> int:
    """Worker, every minute: Facebook leads whose read failed are tried again."""
    rows = (
        await db.scalars(
            select(LeadAdLead)
            .where(LeadAdLead.status == "pending")
            .order_by(LeadAdLead.created_at)
            .limit(50)
        )
    ).all()
    for row in rows:
        src = await db.get(LeadAdSource, row.ad_source_id)
        if src is None or not src.is_active:
            row.status, row.error = "failed", "The lead ads connection was removed or switched off"
            continue
        await process(db, src, row)
    return len(rows)

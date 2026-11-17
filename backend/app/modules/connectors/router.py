"""Settings → Connected CRM (settings.manage). One CRM per company: Custom CRM (any CRM, through
the company's own addresses), LeadSquared, HubSpot (its Service Key), Zoho CRM (a Self Client)
or Pipedrive (company address + API token). Keys are encrypted and never shown again; the Custom CRM signing secret is shown once,
when it is made."""

import json
import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core import secrets as SEC
from app.core.errors import Invalid, NotFound
from app.modules.auth.deps import CurrentUser, require
from app.modules.connectors import base as B
from app.modules.connectors import service as S
from app.modules.connectors.leadsquared import HOSTS, LeadSquared
from app.modules.connectors.models import CrmConnection, CrmSync
from app.modules.connectors.pipedrive import DOMAIN as PIPEDRIVE_DOMAIN
from app.modules.connectors.zoho import REGIONS as ZOHO_REGIONS
from app.modules.connectors.zoho import exchange_code as zoho_exchange
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.identities import normalize

router = APIRouter(prefix="/api/v1/crm-connection", tags=["crm-connection"], dependencies=CRM)
Admin = Annotated[CurrentUser, require("settings.manage")]
Url = Annotated[str, Field(max_length=500)]


class CrmConnectionIn(BaseModel):
    provider: Literal["custom", "leadsquared", "hubspot", "zoho", "pipedrive"]
    host: str | None = None  # leadsquared: one of the region hosts
    access_key: str | None = Field(default=None, max_length=200)  # leadsquared; keep if empty
    secret_key: str | None = Field(default=None, max_length=200)
    token: str | None = Field(default=None, min_length=10, max_length=500)  # hubspot; keep if empty
    client_id: str | None = Field(default=None, max_length=200)  # zoho Self Client
    client_secret: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=300)  # zoho: one-time; needed to connect
    lookup_url: Url | None = None  # custom
    create_url: Url | None = None
    activity_url: Url | None = None
    activity_event: int | None = Field(default=None, ge=1)  # leadsquared: WhatsApp activity code
    send_calls: bool = True
    send_whatsapp: bool = True
    create_leads: bool = True
    is_active: bool = True


class CrmConnectionOut(BaseModel):
    connected: bool
    regions: dict[str, str] = HOSTS
    zoho_regions: dict[str, str] = ZOHO_REGIONS
    provider: str | None = None
    host: str | None = None
    key_hint: str | None = None
    lookup_url: str | None = None
    create_url: str | None = None
    activity_url: str | None = None
    activity_event: int | None = None
    send_calls: bool = True
    send_whatsapp: bool = True
    create_leads: bool = True
    is_active: bool = False
    last_ok_at: datetime | None = None
    last_error: str | None = None
    signing_secret: str | None = None  # Custom CRM: only in the answer that made it


class CrmSyncOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    kind: str
    lead_id: uuid.UUID | None
    external_lead_id: str | None
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


class TestIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)


class TestOut(BaseModel):
    ok: bool
    lead_id: str | None = None
    error: str | None = None


async def _conn(db) -> CrmConnection | None:
    return await db.scalar(select(CrmConnection))


def _out(conn: CrmConnection | None, signing_secret: str | None = None) -> CrmConnectionOut:
    if conn is None:
        return CrmConnectionOut(connected=False)
    cfg = S.options(conn)
    hint = None
    if conn.provider in ("leadsquared", "hubspot", "zoho", "pipedrive"):
        try:
            stored = SEC.decrypt(conn.secret_enc)
            field = {"leadsquared": "access_key", "zoho": "client_id"}.get(conn.provider)
            key = json.loads(stored).get(field, "") if field else stored
            hint = SEC.hint(key)
        except ValueError:
            hint = "••••"
    return CrmConnectionOut(
        connected=True, provider=conn.provider, host=conn.host, key_hint=hint,
        lookup_url=cfg.get("lookup_url"), create_url=cfg.get("create_url"),
        activity_url=cfg.get("activity_url"), activity_event=cfg.get("activity_event"),
        send_calls=cfg["send_calls"], send_whatsapp=cfg["send_whatsapp"],
        create_leads=cfg["create_leads"], is_active=conn.is_active,
        last_ok_at=conn.last_ok_at, last_error=conn.last_error, signing_secret=signing_secret,
    )  # fmt: skip


@router.get("", response_model=CrmConnectionOut)
async def get_connection(db: CrmDb, actor: Admin) -> CrmConnectionOut:
    return _out(await _conn(db))


@router.put("", response_model=CrmConnectionOut)
async def put_connection(body: CrmConnectionIn, db: CrmDb, actor: Admin) -> CrmConnectionOut:
    conn = await _conn(db)
    if conn is not None and conn.provider != body.provider:
        raise Invalid("Disconnect the current CRM first", code="crm_other_connected")
    made_secret = None
    options = {"send_calls": body.send_calls, "send_whatsapp": body.send_whatsapp,
               "create_leads": body.create_leads}  # fmt: skip
    if body.provider == "leadsquared":
        if body.host not in HOSTS:
            raise Invalid("Choose your LeadSquared region", code="crm_region")
        keys = json.loads(SEC.decrypt(conn.secret_enc)) if conn else {}
        keys = {"access_key": body.access_key or keys.get("access_key"),
                "secret_key": body.secret_key or keys.get("secret_key")}  # fmt: skip
        if not keys["access_key"] or not keys["secret_key"]:
            raise Invalid("Enter the access key and secret key", code="crm_keys")
        secret_enc, host = SEC.encrypt(json.dumps(keys)), body.host
        if body.activity_event:
            options["activity_event"] = body.activity_event
        elif conn and (conn.config or {}).get("activity_event"):
            options["activity_event"] = conn.config["activity_event"]
    elif body.provider == "zoho":
        keys = json.loads(SEC.decrypt(conn.secret_enc)) if conn else {}
        if body.code:  # connecting (again): the one-time code becomes a refresh token
            if body.host not in ZOHO_REGIONS or not body.client_id or not body.client_secret:
                raise Invalid("Choose the region and paste the client id and secret",
                              code="crm_keys")  # fmt: skip
            try:
                made = await zoho_exchange(body.host, body.client_id, body.client_secret, body.code)
            except B.CrmError as e:
                raise Invalid(str(e), code="crm_code") from None
            keys = {"accounts": body.host, "client_id": body.client_id,
                    "client_secret": body.client_secret, **made}  # fmt: skip
        elif not keys:
            raise Invalid("Paste the one-time code from Zoho's API console", code="crm_code")
        secret_enc, host = SEC.encrypt(json.dumps(keys)), keys["accounts"]
    elif body.provider in ("hubspot", "pipedrive"):
        token = body.token or (SEC.decrypt(conn.secret_enc) if conn else None)
        if not token:
            raise Invalid("Paste the API key", code="crm_keys")
        secret_enc, host = SEC.encrypt(token.strip()), None
        if body.provider == "pipedrive":
            host = (body.host or "").strip().lower().removesuffix(".pipedrive.com")
            if not PIPEDRIVE_DOMAIN.match(host):
                raise Invalid("Type your Pipedrive address, like acme.pipedrive.com",
                              code="crm_region")  # fmt: skip
    else:
        for u in (body.lookup_url, body.create_url, body.activity_url):
            if not u or not u.startswith("https://"):
                raise Invalid("Each address must start with https://", code="crm_urls")
        options |= {"lookup_url": body.lookup_url, "create_url": body.create_url,
                    "activity_url": body.activity_url}  # fmt: skip
        host = None
        if conn is None:
            made_secret = secrets.token_urlsafe(32)
            secret_enc = SEC.encrypt(made_secret)
        else:
            secret_enc = conn.secret_enc
    if conn is None:
        # Only what happens from now on is sent: the cursor starts at the connection.
        conn = CrmConnection(id=uuid.uuid4(), tenant_id=actor.user.tenant_id, cursor_at=L.now())
        db.add(conn)
    conn.provider, conn.host, conn.secret_enc = body.provider, host, secret_enc
    conn.config, conn.is_active, conn.last_error = options, body.is_active, None
    if body.provider == "leadsquared" and body.send_whatsapp and "activity_event" not in options:
        try:  # once: the "WhatsApp (Versnq)" activity type in their LeadSquared
            code = await LeadSquared(host, json.loads(SEC.decrypt(secret_enc)), options)\
                .make_activity_type()  # fmt: skip
            conn.config = {**options, "activity_event": int(code)}
        except (B.CrmError, ValueError) as e:
            conn.last_error = f"WhatsApp activity type not made: {e}"[:300]
    await db.flush()
    await audit(db, actor, "crm.connected", "crm_connection", conn.id,
                after={"provider": conn.provider, "host": conn.host})  # fmt: skip
    return _out(conn, made_secret)


@router.post("/test", response_model=TestOut)
async def test_connection(body: TestIn, db: CrmDb, actor: Admin) -> TestOut:
    """Looks a number up in the CRM: proves the keys and addresses work."""
    conn = await _conn(db)
    if conn is None:
        raise NotFound("No CRM connected")
    phone = normalize("phone", body.phone, await L.tenant_country(db, actor.user.tenant_id))
    try:
        found = await S.connector_for(conn).find_by_phone(phone)
    except (B.CrmError, ValueError) as e:
        conn.last_error = str(e)[:300]
        return TestOut(ok=False, error=str(e))
    conn.last_ok_at, conn.last_error = S.now(), None
    return TestOut(ok=True, lead_id=found)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(db: CrmDb, actor: Admin) -> None:
    conn = await _conn(db)
    if conn is None:
        raise NotFound("No CRM connected")
    await db.execute(delete(CrmSync).where(CrmSync.connection_id == conn.id))
    await db.delete(conn)
    await audit(db, actor, "crm.disconnected", "crm_connection", conn.id)


@router.get("/syncs", response_model=list[CrmSyncOut])
async def list_syncs(db: CrmDb, actor: Admin) -> list[CrmSync]:
    return list(
        (await db.scalars(select(CrmSync).order_by(CrmSync.created_at.desc()).limit(50))).all()
    )


@router.post("/syncs/{sync_id}/retry", response_model=CrmSyncOut)
async def retry_sync(sync_id: uuid.UUID, db: CrmDb, actor: Admin) -> CrmSync:
    s = await db.get(CrmSync, sync_id)
    if s is None:
        raise NotFound("Not found")
    if s.status not in ("failed", "skipped"):
        raise Invalid("Only a failed or skipped send can be tried again")
    s.status, s.attempts, s.next_try_at, s.last_error = "pending", 0, S.now(), None
    await db.flush()
    return s

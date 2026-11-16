"""The company's official WhatsApp number on Meta's Cloud API (step 10b, Decision log #41).

Meta's rules are kept by Core, not left to people:
- The business may start a chat (or restart it after 24 hours of silence) only with a template
  Meta approved. Free text is allowed only within 24 hours of the person's last message.
- Marketing templates go only to people who opted in to WhatsApp; utility templates (reminders,
  confirmations) to anyone who has not opted out (W6).
- A STOP word opts the person out at once; nothing automatic is sent after it.
- Every webhook from Meta is checked against the company's app secret before it is used.

The autoresponder lives on this number only (never on the reps' own WhatsApp): a welcome for a
person's first message and an away message outside sending hours, at most two automatic replies
per person a day, never in answer to a STOP.

WHATSAPP_SENDER=test (default): nothing reaches Meta; sends get a test id, templates are
approved at once (and say so), so the whole flow can be built and tried before the company's
Meta Business verification. WHATSAPP_SENDER=meta: the Cloud API with the company's own keys.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets as SEC
from app.core import storage
from app.core.config import get_settings
from app.core.errors import Invalid
from app.core.storage import check_media, clean_name, save
from app.modules.auth.deps import CurrentUser
from app.modules.crm import consent as C
from app.modules.crm import intake as I
from app.modules.crm import leads as L
from app.modules.crm.customers import storage_used
from app.modules.crm.identities import normalize
from app.modules.crm.models import Lead, LeadIdentity, LeadSource, StoredFile
from app.modules.crm.notify import notify
from app.modules.crm.routing import mark_contacted
from app.modules.engage import engine as E
from app.modules.engage import render as R
from app.modules.engage.models import (
    Conversation,
    ConversationMember,
    Message,
    MessageAttachment,
    WhatsAppAccount,
    WhatsAppTemplate,
)
from app.modules.settings.models import WHATSAPP_DEFAULTS, TenantSettings
from app.platform.models import Tenant

WINDOW = timedelta(hours=24)
AUTO_PER_DAY = 2
AUTO_LABEL = {"welcome": "Automatic reply: welcome", "away": "Automatic reply: away"}
AWAY_EVERY = timedelta(hours=12)
MAX_FILE = 16 * 1024 * 1024  # Meta's own cap for audio and video
MAX_PHOTO = 5 * 1024 * 1024  # Meta's cap for images
MEDIA_KEEP = timedelta(days=25)  # Meta keeps an uploaded media id 30 days; re-upload before
HEADER_FORMATS = ("text", "image", "video", "document")
LABEL = {
    "image": "[photo]",
    "video": "[video]",
    "document": "[document]",
    "audio": "[voice note]",
    "sticker": "[sticker]",
    "location": "[location]",
    "contacts": "[contact card]",
}
STATUS_ORDER = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
# Payment reminders (W7): a utility template may also use these.
INVOICE_VARS = frozenset(
    {"invoice.number", "invoice.amount_due", "invoice.due_date", "invoice.pay_link"}
)
SAMPLE = {
    "invoice.number": "INV-0042",
    "invoice.amount_due": "₹12,000",
    "invoice.due_date": "19 Nov",
    "invoice.pay_link": "https://rzp.io/l/example",
    "lead.first_name": "Asha",
    "lead.last_name": "Rao",
    "lead.name": "Asha Rao",
    "lead.company": "Tidara",
    "lead.city": "Pune",
    "owner.name": "Ishita",
    "company.name": "Your company",
}


def now() -> datetime:
    return datetime.now(UTC)


def settings_of(ts: TenantSettings) -> dict:
    return {**WHATSAPP_DEFAULTS, **(ts.whatsapp or {})}


# ---------- talking to Meta ----------
class MetaClient:
    """Meta's Graph API for one company (its own token)."""

    def __init__(self, acct: WhatsAppAccount):
        self.acct = acct
        self.token = SEC.decrypt(acct.access_token_enc)
        self.base = f"https://graph.facebook.com/{get_settings().meta_graph_version}"

    async def _call(self, method: str, path: str, **kw) -> dict:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            try:
                r = await http.request(
                    method,
                    f"{self.base}/{path}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    **kw,
                )
            except httpx.HTTPError as e:
                raise Invalid(
                    f"Could not reach WhatsApp ({type(e).__name__})", code="whatsapp_send_failed"
                ) from None
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            err = (data or {}).get("error", {})
            said = err.get("error_user_msg") or err.get("message") or r.status_code
            raise Invalid(f"WhatsApp said: {said}", code="whatsapp_send_failed")
        return data

    async def phone_info(self) -> dict:
        return await self._call(
            "GET",
            self.acct.phone_number_id,
            params={
                "fields": "display_phone_number,verified_name,quality_rating,messaging_limit_tier"
            },
        )

    async def send(self, payload: dict) -> str:
        data = await self._call(
            "POST",
            f"{self.acct.phone_number_id}/messages",
            json={"messaging_product": "whatsapp", **payload},
        )
        return data["messages"][0]["id"]

    async def submit_template(self, payload: dict) -> dict:
        return await self._call("POST", f"{self.acct.waba_id}/message_templates", json=payload)

    async def template_status(self, name: str) -> list[dict]:
        data = await self._call(
            "GET", f"{self.acct.waba_id}/message_templates", params={"name": name}
        )
        return data.get("data", [])

    async def upload_media(self, data: bytes, mime: str, name: str) -> str:
        """Meta's media upload for sending (POST /{phone-number-id}/media, multipart)."""
        out = await self._call(
            "POST",
            f"{self.acct.phone_number_id}/media",
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (name, data, mime)},
        )
        return out["id"]

    async def upload_example(self, data: bytes, mime: str) -> str:
        """A header example for template approval: Meta's Resumable Upload API on the company's
        own app (start a session, then send the bytes), giving the handle `h`."""
        if not self.acct.app_id:
            raise Invalid(
                "Add your Meta app ID in Settings → WhatsApp first: WhatsApp needs it to receive "
                "the example file of a template with a photo, video or document",
                code="whatsapp_app_id_missing",
            )
        start = await self._call(
            "POST",
            f"{self.acct.app_id}/uploads",
            params={"file_length": len(data), "file_type": mime},
        )
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
            r = await http.post(
                f"{self.base}/{start['id']}",
                headers={"Authorization": f"OAuth {self.token}", "file_offset": "0"},
                content=data,
            )
        body = r.json() if r.content else {}
        if r.status_code >= 400 or not body.get("h"):
            raise Invalid("WhatsApp didn't accept the example file", code="whatsapp_send_failed")
        return body["h"]

    async def media(self, media_id: str) -> tuple[bytes, str] | None:
        info = await self._call("GET", media_id)
        url = info.get("url")
        if not url:
            return None
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
            r = await http.get(url, headers={"Authorization": f"Bearer {self.token}"})
        if r.status_code != 200 or len(r.content) > MAX_FILE:
            return None
        return r.content, info.get("mime_type") or r.headers.get("content-type", "")


class TestClient:
    """WHATSAPP_SENDER=test: nothing reaches Meta."""

    def __init__(self, acct: WhatsAppAccount):
        self.acct = acct

    async def phone_info(self) -> dict:
        return {
            "display_phone_number": self.acct.display_number or "+91 00000 00000 (test)",
            "verified_name": "Test number",
            "quality_rating": "GREEN",
            "messaging_limit_tier": "TIER_1K",
        }

    async def send(self, payload: dict) -> str:
        return f"wamid.TEST{secrets.token_hex(8).upper()}"

    async def submit_template(self, payload: dict) -> dict:
        return {"id": f"TEST{secrets.token_hex(6)}", "status": "APPROVED"}

    async def template_status(self, name: str) -> list[dict]:
        return []

    async def media(self, media_id: str) -> tuple[bytes, str] | None:
        return None

    async def upload_media(self, data: bytes, mime: str, name: str) -> str:
        return f"TESTMEDIA{secrets.token_hex(6)}"

    async def upload_example(self, data: bytes, mime: str) -> str:
        return f"4::TEST{secrets.token_hex(6)}"


def client(acct: WhatsAppAccount):  # patched in tests
    return TestClient(acct) if get_settings().whatsapp_sender == "test" else MetaClient(acct)


def test_mode() -> bool:
    return get_settings().whatsapp_sender == "test"


async def account(db: AsyncSession) -> WhatsAppAccount | None:
    """The connected number, only while the company's "whatsapp_number" switch is on (#44)."""
    from app.core.modules import is_enabled

    acct = await db.scalar(select(WhatsAppAccount))
    if acct is None or not await is_enabled(db, acct.tenant_id, "whatsapp_number"):
        return None
    return acct


async def require_account(db: AsyncSession) -> WhatsAppAccount:
    acct = await account(db)
    if acct is None:
        raise Invalid(
            "Connect the company's WhatsApp number first (Settings → WhatsApp)",
            code="whatsapp_not_connected",
        )
    return acct


def signature_ok(acct: WhatsAppAccount, raw: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    secret = SEC.decrypt(acct.app_secret_enc).encode()
    want = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header.removeprefix("sha256="))


# ---------- templates ----------
NAME = re.compile(r"^[a-z0-9_]{1,120}$")


def meta_body(body: str) -> tuple[str, list[dict]]:
    """Our {{lead.first_name|there}} → Meta's {{1}}, with the variables in order."""
    variables: list[dict] = []

    def one(m: re.Match) -> str:
        variables.append({"name": m.group(1), "fallback": (m.group(2) or "").strip()})
        return f"{{{{{len(variables)}}}}}"

    return R.VAR.sub(one, body), variables


def params_for(tpl: WhatsAppTemplate, values: dict[str, str | None]) -> list[str]:
    """The text for each {{n}}. Meta refuses an empty one, so a dash stands in."""
    out = []
    for v in tpl.variables or []:
        val = values.get(v["name"])
        out.append(str(val) if val not in (None, "") else (v.get("fallback") or "-"))
    return out


async def submit(db: AsyncSession, acct: WhatsAppAccount, tpl: WhatsAppTemplate) -> None:
    text, variables = meta_body(tpl.body)
    tpl.variables = variables
    body = {"type": "BODY", "text": text}
    if variables:
        body["example"] = {
            "body_text": [[SAMPLE.get(v["name"], v.get("fallback") or "sample") for v in variables]]
        }
    components = [body] + ([{"type": "FOOTER", "text": tpl.footer}] if tpl.footer else [])
    header = tpl.header or {}
    if header.get("format") == "text":
        components.insert(0, {"type": "HEADER", "format": "TEXT", "text": header["text"]})
    elif header.get("format") in ("image", "video", "document"):
        data = storage.full_path(header["path"]).read_bytes()
        handle = await client(acct).upload_example(data, header["content_type"])
        components.insert(0, {
            "type": "HEADER", "format": header["format"].upper(),
            "example": {"header_handle": [handle]},
        })  # fmt: skip
    if tpl.buttons:
        components.append({"type": "BUTTONS", "buttons": [_meta_button(b) for b in tpl.buttons]})
    out = await client(acct).submit_template(
        {
            "name": tpl.name,
            "language": tpl.language,
            "category": tpl.category.upper(),
            "components": components,
        }
    )
    tpl.meta_id = str(out.get("id") or "") or None
    tpl.status = (out.get("status") or "PENDING").lower()
    if tpl.status not in ("pending", "approved", "rejected", "paused", "disabled"):
        tpl.status = "pending"
    tpl.reason = "Test mode: approved at once (nothing was sent to Meta)" if test_mode() else None


def _meta_button(b: dict) -> dict:
    """One button as Meta's template API spells it."""
    if b["type"] == "quick_reply":
        return {"type": "QUICK_REPLY", "text": b["text"]}
    if b["type"] == "phone":
        return {"type": "PHONE_NUMBER", "text": b["text"], "phone_number": b["phone"]}
    if b.get("url_var"):  # a variable at the end of the address: {{1}}, with an example
        example = b["url"] + SAMPLE.get(b["url_var"], "example")
        return {"type": "URL", "text": b["text"], "url": b["url"] + "{{1}}", "example": [example]}
    return {"type": "URL", "text": b["text"], "url": b["url"]}


def button_line(tpl: WhatsAppTemplate) -> str:
    """How the buttons read on the timeline and in the inbox."""
    return "[Buttons: " + " · ".join(b["text"] for b in tpl.buttons) + "]" if tpl.buttons else ""


async def _header_media_id(acct: WhatsAppAccount, tpl: WhatsAppTemplate) -> str:
    """The template's header file as a Meta media id (uploaded once, again after 25 days)."""
    h = dict(tpl.header or {})
    at = datetime.fromisoformat(h["media_at"]) if h.get("media_at") else None
    if h.get("media_id") and at and now() - at < MEDIA_KEEP:
        return h["media_id"]
    data = storage.full_path(h["path"]).read_bytes()
    h["media_id"] = await client(acct).upload_media(
        data, h["content_type"], h.get("name") or "file"
    )
    h["media_at"] = now().isoformat()
    tpl.header = h  # a new dict, so the change is saved
    return h["media_id"]


async def refresh_template(db: AsyncSession, acct: WhatsAppAccount, tpl: WhatsAppTemplate) -> None:
    for row in await client(acct).template_status(tpl.name):
        if row.get("language") == tpl.language:
            tpl.status = (row.get("status") or tpl.status).lower()
            tpl.reason = row.get("rejected_reason") or tpl.reason


# ---------- conversations and the 24-hour window ----------
async def conversation(
    db: AsyncSession, acct: WhatsAppAccount, lead: Lead, by: uuid.UUID | None = None
) -> Conversation:
    conv = await db.scalar(
        select(Conversation)
        .where(Conversation.lead_id == lead.id, Conversation.whatsapp_account_id == acct.id)
        .limit(1)
    )
    if conv is None:
        conv = Conversation(
            id=uuid.uuid4(),
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            channel="whatsapp",
            subject=f"WhatsApp · {acct.verified_name or acct.display_number or 'company number'}",
            status="open",
            whatsapp_account_id=acct.id,
            created_by_user_id=by,
        )
        db.add(conv)
        await db.flush()
    return conv


def window_ends(conv: Conversation | None) -> datetime | None:
    """When free text stops being allowed (None: closed, or never opened)."""
    if conv is None or conv.last_inbound_at is None:
        return None
    ends = conv.last_inbound_at + WINDOW
    return ends if ends > now() else None


def _to(lead: Lead) -> str:
    digits = re.sub(r"\D", "", lead.primary_phone or "")
    if not digits:
        raise Invalid(f"{lead.display_name} has no phone number", code="no_phone")
    return digits


async def _opted_out(db: AsyncSession, lead: Lead) -> bool:
    if lead.whatsapp_consent == "opted_out":
        return True
    phones = [
        p
        for p in (
            await db.scalars(
                select(LeadIdentity.value_normalized).where(
                    LeadIdentity.lead_id == lead.id, LeadIdentity.type == "phone"
                )
            )
        ).all()
    ]
    return await C.is_suppressed(db, "whatsapp", phones)


async def send(
    db: AsyncSession,
    lead: Lead,
    *,
    text: str | None = None,
    template: WhatsAppTemplate | None = None,
    actor: CurrentUser | None = None,
    enrolment_id: uuid.UUID | None = None,
    step_id: uuid.UUID | None = None,
    auto: str | None = None,  # "welcome" / "away": the autoresponder
    raise_errors: bool = True,
    extra_values: dict[str, str | None] | None = None,
) -> Message:
    """One message from the official number: free text (only inside the 24-hour window) or an
    approved template. Raises Invalid with a plain reason when a rule says no."""
    acct = await require_account(db)
    to = _to(lead)
    conv = await conversation(db, acct, lead, by=actor.user.id if actor else None)
    open_until = window_ends(conv)
    if await _opted_out(db, lead) and (template is not None or open_until is None):
        raise Invalid(f"{lead.display_name} opted out of WhatsApp", code="whatsapp_opted_out")
    tenant = await db.get(Tenant, lead.tenant_id)
    values = await E.values_for(db, lead, tenant.name) | (extra_values or {})
    if template is not None:
        if template.status != "approved":
            raise Invalid(
                f"The template {template.name} is not approved by WhatsApp yet",
                code="whatsapp_template_not_approved",
            )
        if template.category == "marketing" and lead.whatsapp_consent != "opted_in":
            raise Invalid(
                f"{lead.display_name} hasn't opted in to WhatsApp; "
                "marketing templates need an opt-in (use a utility template, or record consent)",
                code="whatsapp_needs_opt_in",
            )
        params = params_for(template, values)
        body = R.fill(template.body, values)
        components: list[dict] = []
        header = template.header or {}
        if header.get("format") in ("image", "video", "document"):
            fmt = header["format"]
            media = {"id": await _header_media_id(acct, template)}
            if fmt == "document":
                media["filename"] = header.get("name") or "document.pdf"
            components.append({"type": "header", "parameters": [{"type": fmt, fmt: media}]})
            body = f"{LABEL[fmt]} {body}"
        elif header.get("format") == "text":
            body = f"{header['text']}\n{body}"
        if params:
            components.append(
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
            )
        for i, b in enumerate(template.buttons or []):
            if b["type"] == "url" and b.get("url_var"):
                value = str(values.get(b["url_var"]) or "").strip() or "-"
                components.append({
                    "type": "button", "sub_type": "url", "index": str(i),
                    "parameters": [{"type": "text", "text": value[:200]}],
                })  # fmt: skip
        if template.buttons:
            body = f"{body}\n{button_line(template)}"
        payload = {
            "to": to,
            "type": "template",
            "template": {
                "name": template.name,
                "language": {"code": template.language},
                "components": components,
            },
        }
    else:
        if open_until is None:
            raise Invalid(
                "The 24-hour window is closed: WhatsApp allows only an approved template now",
                code="whatsapp_window_closed",
            )
        body = R.fill(text or "", values).strip()
        if not body:
            raise Invalid("Write a message", code="message_empty")
        payload = {"to": to, "type": "text", "text": {"body": body[:4096]}}
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        channel="whatsapp",
        direction="out",
        conversation_id=conv.id,
        enrolment_id=enrolment_id,
        step_id=step_id,
        whatsapp_template_id=template.id if template else None,
        to_address="+" + to,
        from_address=acct.display_number,
        subject=AUTO_LABEL.get(auto) if auto else None,
        body=body[:20000],
        token=secrets.token_urlsafe(24),
        status="queued",
        sent_by_user_id=actor.user.id if actor else None,
    )
    db.add(msg)
    await db.flush()
    try:
        msg.provider_id = await client(acct).send(payload)
    except Invalid as err:
        msg.status, msg.error = "failed", str(err.detail)[:300]
        await db.flush()
        if raise_errors:
            raise
        return msg
    msg.status, msg.sent_at = "sent", now()
    msg.external_id = msg.provider_id
    E_touch(conv, msg)
    who = "auto-reply" if auto else ("sequence" if enrolment_id else None)
    await L.log(
        db,
        lead,
        "whatsapp_sent",
        f"WhatsApp sent{f' ({who})' if who else ''}: {body[:120]}",
        actor,
        {
            "message_id": str(msg.id),
            "conversation_id": str(conv.id),
            "via": "official",
            "template": template.name if template else None,
        },
        body=body[:2000],
    )
    from app.modules.engage.inbox import message_event

    await message_event(db, msg, channel="whatsapp", official=True)
    lead.last_activity_at = now()
    if actor is not None:
        lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, now()]))
        lead.first_response_at = lead.first_response_at or now()
        await mark_contacted(db, lead)
    return msg


async def send_media(
    db: AsyncSession, lead: Lead, data: bytes, name: str, caption: str | None, actor: CurrentUser
) -> Message:
    """A photo or document from the company number (finish plan, batch 3): like free text, only
    inside the 24-hour window and never to someone who opted out. The file is also kept on the
    lead (same checks and storage quota as any upload). Photos: JPG or PNG up to 5 MB (Meta's
    limit); documents: PDF, Word or Excel up to 16 MB."""
    acct = await require_account(db)
    to = _to(lead)
    conv = await conversation(db, acct, lead, by=actor.user.id)
    if window_ends(conv) is None:
        raise Invalid(
            "The 24-hour window is closed: WhatsApp allows only an approved template now",
            code="whatsapp_window_closed",
        )
    if await _opted_out(db, lead):
        raise Invalid(f"{lead.display_name} opted out of WhatsApp", code="whatsapp_opted_out")
    name = clean_name(name or "file")
    content_type, ext = storage.check_type(data, name, allow_office=True)
    if content_type in ("image/jpeg", "image/png"):
        kind, limit = "image", MAX_PHOTO
    elif content_type.startswith("image/"):
        raise Invalid("WhatsApp takes photos as JPG or PNG", code="whatsapp_media_type")
    else:
        kind, limit = "document", MAX_FILE
    if len(data) > limit:
        raise Invalid(
            f"WhatsApp takes {kind}s up to {limit // (1024 * 1024)} MB", code="whatsapp_media_size"
        )
    settings = await db.get(TenantSettings, lead.tenant_id)
    if await storage_used(db) + len(data) > settings.storage_quota_bytes:
        raise Invalid("Your company's file storage is full", code="storage_full")
    caption = (caption or "").strip()[:1024]
    if "." not in name:
        name = f"{name}.{ext}"
    body = f"{LABEL[kind]} {caption}".strip()
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        channel="whatsapp",
        direction="out",
        conversation_id=conv.id,
        to_address="+" + to,
        from_address=acct.display_number,
        body=body,
        token=secrets.token_urlsafe(24),
        status="queued",
        sent_by_user_id=actor.user.id,
    )
    db.add(msg)
    await db.flush()
    try:
        media_id = await client(acct).upload_media(data, content_type, name)
        media: dict = {"id": media_id}
        if caption:
            media["caption"] = caption
        if kind == "document":
            media["filename"] = name
        msg.provider_id = await client(acct).send({"to": to, "type": kind, kind: media})
    except Invalid as err:
        msg.status, msg.error = "failed", str(err.detail)[:300]
        await db.flush()
        raise
    msg.status, msg.sent_at, msg.external_id = "sent", now(), msg.provider_id
    saved = save(lead.tenant_id, data, ext, content_type)
    stored = StoredFile(
        tenant_id=lead.tenant_id, lead_id=lead.id, path=saved.path, original_name=name,
        content_type=content_type, size_bytes=saved.size_bytes, sha256=saved.sha256,
        uploaded_by_user_id=actor.user.id,
    )  # fmt: skip
    db.add(stored)
    await db.flush()
    db.add(MessageAttachment(tenant_id=lead.tenant_id, message_id=msg.id, file_id=stored.id))
    E_touch(conv, msg)
    await L.log(
        db, lead, "whatsapp_sent", f"WhatsApp sent: {body[:120]}", actor,
        {"message_id": str(msg.id), "conversation_id": str(conv.id), "via": "official",
         "template": None, "file_id": str(stored.id)},
        body=body[:2000],
    )  # fmt: skip
    from app.modules.engage.inbox import message_event

    await message_event(db, msg, channel="whatsapp", official=True)
    lead.last_activity_at = now()
    lead.last_contacted_at = max(filter(None, [lead.last_contacted_at, now()]))
    lead.first_response_at = lead.first_response_at or now()
    await mark_contacted(db, lead)
    return msg


def E_touch(conv: Conversation, msg: Message) -> None:
    from app.modules.engage import inbox as IB  # inbox builds on engine

    IB._touch(conv, msg)


# ---------- incoming (Meta's webhook) ----------
async def _lead_for(db: AsyncSession, tenant_id: uuid.UUID, wa_id: str) -> Lead | None:
    country = await L.tenant_country(db, tenant_id)
    try:
        phone = normalize("phone", "+" + wa_id, country)
    except Invalid:
        return None
    return await db.scalar(
        select(Lead)
        .join(LeadIdentity, LeadIdentity.lead_id == Lead.id)
        .where(LeadIdentity.type == "phone", LeadIdentity.value_normalized == phone)
        .order_by(Lead.is_open.desc(), Lead.last_activity_at.desc().nulls_last())
        .limit(1)
    )


async def _new_lead(
    db: AsyncSession, tenant_id: uuid.UUID, wa_id: str, name: str | None, cfg: dict
) -> Lead | None:
    if not cfg.get("create_leads"):
        return None
    source = None
    if cfg.get("source_id"):
        source = await db.get(LeadSource, uuid.UUID(cfg["source_id"]))
    if source is None or not source.is_active:
        sources = (
            await db.scalars(
                select(LeadSource)
                .where(LeadSource.is_active.is_(True))
                .order_by(LeadSource.position)
            )
        ).all()
        source = next((s for s in sources if s.name.strip().lower() == "whatsapp"), None) or (
            sources[0] if sources else None
        )
    if source is None:
        return None
    first, _, last = (name or "").strip().partition(" ")
    acct = await db.scalar(select(WhatsAppAccount))  # its brand, when the company has brands
    out = await I.intake(
        db,
        tenant_id,
        I.Incoming(
            identities=[
                L.IdentityInput(type="phone", value="+" + wa_id, is_primary=True, is_whatsapp=True)
            ],
            source_id=source.id,
            created_via="whatsapp",
            fields={"first_name": first or None, "last_name": last or None},
            owner=I.RULES,
            enforce_required=False,
            via_label="WhatsApp",
            brand_id=acct.brand_id if acct else None,
        ),
        policy="update",
    )
    return out.lead


async def _keep_file(
    db: AsyncSession, acct: WhatsAppAccount, lead: Lead, msg: Message, media: dict, kind: str
) -> None:
    got = await client(acct).media(media.get("id", ""))
    if got is None:
        return
    data, _mime = got
    name = clean_name(media.get("filename") or f"whatsapp-{msg.external_id or msg.id}")
    settings = await db.get(TenantSettings, lead.tenant_id)
    try:
        content_type, ext = check_media(data, name, kind)
        if await storage_used(db) + len(data) > settings.storage_quota_bytes:
            raise Invalid("storage full")
    except Invalid as e:
        msg.error = f"File not kept: {name} ({e.detail})"[:300]
        return
    saved = save(lead.tenant_id, data, ext, content_type)
    stored = StoredFile(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        path=saved.path,
        original_name=name if "." in name else f"{name}.{ext}",
        content_type=content_type,
        size_bytes=saved.size_bytes,
        sha256=saved.sha256,
    )
    db.add(stored)
    await db.flush()
    db.add(MessageAttachment(tenant_id=lead.tenant_id, message_id=msg.id, file_id=stored.id))


def _text_of(m: dict) -> tuple[str, dict | None]:
    kind = m.get("type", "text")
    if kind == "text":
        return (m.get("text") or {}).get("body", ""), None
    if kind == "button":
        return (m.get("button") or {}).get("text", ""), None
    if kind == "interactive":
        i = m.get("interactive") or {}
        reply = i.get("button_reply") or i.get("list_reply") or {}
        return reply.get("title", ""), None
    media = m.get(kind) if isinstance(m.get(kind), dict) else None
    caption = (media or {}).get("caption") or ""
    return f"{LABEL.get(kind, '[message]')} {caption}".strip(), media


def _is_stop(text: str, cfg: dict) -> bool:
    said = re.sub(r"\s+", " ", text).strip().casefold()
    return any(said == w.strip().casefold() for w in cfg.get("stop_words") or [] if w.strip())


async def _incoming(
    db: AsyncSession, acct: WhatsAppAccount, m: dict, names: dict[str, str], cfg: dict
) -> Message | None:
    wamid, wa_id = m.get("id"), re.sub(r"\D", "", m.get("from", ""))
    if not wamid or not wa_id:
        return None
    if await db.scalar(select(Message.id).where(Message.external_id == wamid)):
        return None  # Meta sends a webhook again when unsure; kept once
    lead = await _lead_for(db, acct.tenant_id, wa_id)
    created = False
    if lead is None:
        lead = await _new_lead(db, acct.tenant_id, wa_id, names.get(wa_id), cfg)
        created = lead is not None
    if lead is None:
        return None  # unknown number and the company keeps leads off (W3)
    conv = await conversation(db, acct, lead)
    first_ever = conv.last_message_at is None  # they wrote first: the welcome is for them
    answered = await db.scalar(
        select(Message)
        .where(Message.conversation_id == conv.id, Message.direction == "out")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if answered is not None and answered.replied_at is None:
        answered.replied_at = now()  # the sequence's results count it as replied
    text, media = _text_of(m)
    try:
        when = datetime.fromtimestamp(int(m.get("timestamp")), UTC)
    except (TypeError, ValueError):
        when = now()
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        channel="whatsapp",
        direction="in",
        conversation_id=conv.id,
        to_address=acct.display_number or "",
        from_address="+" + wa_id,
        body=(text or "[message]")[:20000],
        token=secrets.token_urlsafe(24),
        status="received",
        sent_at=when,
        external_id=wamid,
    )
    db.add(msg)
    await db.flush()
    if media:
        await _keep_file(db, acct, lead, msg, media, m.get("type", ""))
    E_touch(conv, msg)
    await L.log(
        db,
        lead,
        "whatsapp_received",
        f"WhatsApp received: {msg.body[:120]}",
        None,
        {"message_id": str(msg.id), "conversation_id": str(conv.id), "via": "official"},
        body=msg.body[:2000],
        occurred_at=when,
    )
    from app.modules.engage.inbox import message_event

    await message_event(db, msg, channel="whatsapp", official=True)
    lead.last_activity_at = now()

    if _is_stop(text, cfg):
        await _stop(db, lead, wa_id, msg)
        return msg
    from app.modules.engage import inbox as IB

    await IB._replied(db, lead, msg)
    from app.modules.engage.inbox import assignee_of

    people = [await assignee_of(db, conv)] + list(
        (
            await db.scalars(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conv.id
                )
            )
        ).all()
    )
    await notify(
        db,
        lead.tenant_id,
        [p for p in people if p],
        "inbox",
        f"WhatsApp from {lead.display_name}: {msg.body[:80]}",
        lead.id,
    )
    await _auto_reply(db, lead, conv, cfg, first_ever=first_ever or created)
    return msg


async def _stop(db: AsyncSession, lead: Lead, wa_id: str, msg: Message) -> None:
    phone = "+" + wa_id
    try:
        phone = normalize("phone", phone, await L.tenant_country(db, lead.tenant_id))
    except Invalid:
        pass
    await C.suppress(db, lead.tenant_id, "whatsapp", [phone], "opt_out")
    if lead.whatsapp_consent != "opted_out":
        await C.record(
            db,
            lead,
            "whatsapp",
            "opted_out",
            "whatsapp",
            evidence={"message_id": str(msg.id), "text": msg.body[:60]},
        )
    await E.stop_all(db, lead.id, "whatsapp_stop")


async def _auto_reply(
    db: AsyncSession, lead: Lead, conv: Conversation, cfg: dict, *, first_ever: bool
) -> None:
    """Welcome for a first message, away message outside sending hours. At most two automatic
    replies per person a day; this number only (Decision log #41)."""
    autos = (
        await db.execute(
            select(Message.subject, Message.sent_at).where(
                Message.conversation_id == conv.id,
                Message.direction == "out",
                Message.subject.in_(AUTO_LABEL.values()),
                Message.status != "failed",
                Message.sent_at >= now() - timedelta(days=1),
            )
        )
    ).all()
    if len(autos) >= AUTO_PER_DAY:
        return
    welcome, away = cfg.get("welcome") or {}, cfg.get("away") or {}
    text = kind = None
    if first_ever and welcome.get("on") and (welcome.get("text") or "").strip():
        text, kind = welcome["text"], "welcome"
    else:
        settings = await db.get(TenantSettings, lead.tenant_id)
        closed = E.next_open(now(), settings.engage or {}, settings.timezone) > now()
        recent = any(
            label == AUTO_LABEL["away"] and t and t > now() - AWAY_EVERY for label, t in autos
        )
        if closed and not recent and away.get("on") and (away.get("text") or "").strip():
            text, kind = away["text"], "away"
    if text:
        await send(db, lead, text=text, auto=kind, raise_errors=False)


async def _status(db: AsyncSession, st: dict) -> None:
    msg = await db.scalar(select(Message).where(Message.provider_id == st.get("id")))
    if msg is None:
        return
    kind = st.get("status")
    try:
        when = datetime.fromtimestamp(int(st.get("timestamp")), UTC)
    except (TypeError, ValueError):
        when = now()
    if kind == "failed":
        err = (st.get("errors") or [{}])[0]
        msg.status = "failed"
        msg.error = (err.get("title") or err.get("message") or "Not delivered")[:300]
        return
    if kind == "delivered":
        msg.delivered_at = msg.delivered_at or when
    if kind == "read":
        msg.read_at = msg.read_at or when
        msg.delivered_at = msg.delivered_at or when
        msg.opened_at = msg.opened_at or when
    if STATUS_ORDER.get(kind, -1) > STATUS_ORDER.get(msg.status, -1):
        msg.status = kind


async def _template_update(db: AsyncSession, v: dict) -> None:
    tpl = await db.scalar(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.meta_id == str(v.get("message_template_id"))
        )
    )
    if tpl is None:
        tpl = await db.scalar(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.name == v.get("message_template_name"),
                WhatsAppTemplate.language == v.get("message_template_language"),
            )
        )
    if tpl is None:
        return
    event = (v.get("event") or "").lower()
    if event in ("approved", "rejected", "paused", "disabled", "pending"):
        tpl.status = event
        tpl.reason = v.get("reason") if event == "rejected" else None


async def handle(db: AsyncSession, acct: WhatsAppAccount, payload: dict) -> int:
    """One webhook from Meta (already checked). Returns how many messages were kept."""
    ts = await db.get(TenantSettings, acct.tenant_id)
    cfg = settings_of(ts)
    kept = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            v = change.get("value") or {}
            field = change.get("field")
            if field == "message_template_status_update":
                await _template_update(db, v)
                continue
            if field != "messages":
                continue
            if (v.get("metadata") or {}).get("phone_number_id") != acct.phone_number_id:
                continue  # another number's message
            names = {
                re.sub(r"\D", "", c.get("wa_id", "")): (c.get("profile") or {}).get("name", "")
                for c in v.get("contacts") or []
            }
            for st in v.get("statuses") or []:
                await _status(db, st)
            for m in v.get("messages") or []:
                kept += (await _incoming(db, acct, m, names, cfg)) is not None
    return kept


# ---------- health ----------
async def refresh_health(db: AsyncSession, acct: WhatsAppAccount) -> None:
    """Quality rating and daily limit from Meta; admins are told when quality drops."""
    try:
        info = await client(acct).phone_info()
    except Invalid as e:
        acct.status, acct.last_error = "error", str(e.detail)[:500]
        acct.health_checked_at = now()
        return
    before = acct.quality_rating
    acct.display_number = info.get("display_phone_number") or acct.display_number
    acct.verified_name = info.get("verified_name") or acct.verified_name
    acct.quality_rating = info.get("quality_rating")
    acct.messaging_limit = info.get("messaging_limit_tier")
    acct.status, acct.last_error, acct.health_checked_at = "active", None, now()
    if acct.quality_rating in ("YELLOW", "RED") and acct.quality_rating != before:
        await notify(
            db,
            acct.tenant_id,
            await _admins(db),
            "whatsapp",
            f"WhatsApp number quality is {acct.quality_rating.lower()}: "
            "people may be blocking or reporting messages. Check templates and who gets them.",
            None,
        )


async def _admins(db: AsyncSession) -> list[uuid.UUID]:
    from app.modules.roles.models import Role
    from app.modules.users.models import User

    return list(
        (
            await db.scalars(
                select(User.id)
                .join(Role, Role.id == User.role_id)
                .where(User.status == "active", Role.key.in_(("owner", "admin")))
            )
        ).all()
    )


LIMITS = {"TIER_50": 50, "TIER_250": 250, "TIER_1K": 1000, "TIER_10K": 10000, "TIER_100K": 100000}


async def daily_limit(db: AsyncSession) -> int:
    """Meta's daily limit for the number (W5); 250 until Meta has told us."""
    acct = await account(db)
    return LIMITS.get((acct.messaging_limit or "") if acct else "", 250)


async def sent_today(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Templates sent today (business-started messages), for the daily cap."""
    start, _ = await L.day_bounds(db, tenant_id)
    return (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.channel == "whatsapp",
                Message.direction == "out",
                Message.whatsapp_template_id.is_not(None),
                Message.sent_at >= start,
            )
        )
        or 0
    )


# ---------- payment reminders (W7) ----------
async def payment_reminder(
    db: AsyncSession, lead: Lead, *, number: str, amount_due: str, due_date, invoice_id
) -> Message | None:
    """The company's chosen utility template, if any, on the nights an email reminder goes.
    Quietly skipped when the number isn't connected or a rule says no (opted out…)."""
    from app.modules.money.models import PaymentLink

    ts = await db.get(TenantSettings, lead.tenant_id)
    tpl_id = settings_of(ts).get("reminder_template_id")
    if not tpl_id or await account(db) is None or not lead.primary_phone:
        return None
    tpl = await db.get(WhatsAppTemplate, uuid.UUID(tpl_id))
    if tpl is None:
        return None
    link = await db.scalar(
        select(PaymentLink.url)
        .where(PaymentLink.invoice_id == invoice_id, PaymentLink.status == "active")
        .order_by(PaymentLink.created_at.desc())
        .limit(1)
    )
    try:
        return await send(
            db,
            lead,
            template=tpl,
            raise_errors=False,
            extra_values={
                "invoice.number": number,
                "invoice.amount_due": amount_due,
                "invoice.due_date": f"{due_date:%d %b}",
                "invoice.pay_link": link,
            },
        )
    except Invalid:
        return None


async def health_all(tenant_ids: list[uuid.UUID]) -> int:
    """Daily: quality rating and limit for every connected number."""
    from app.core.tenancy import tenant_session

    checked = 0
    for tenant_id in tenant_ids:
        async with tenant_session(tenant_id) as db:
            acct = await account(db)
            if acct is not None:
                await refresh_health(db, acct)
                checked += 1
    return checked

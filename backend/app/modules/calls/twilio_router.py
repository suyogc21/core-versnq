"""Calling with the company's own Twilio (calls plan, step C3): connect the account, my phone
for calls, click-to-call, and the requests Twilio sends (checked with its signature)."""

import uuid
from datetime import timedelta
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import secrets as SEC
from app.core.errors import Invalid, NotFound
from app.core.ratelimit import hit
from app.modules.auth.deps import ActiveUser, CurrentUser, WorkspaceDep, require
from app.modules.calls import service as S
from app.modules.calls import twilio as T
from app.modules.calls.models import Call, CallingAccount
from app.modules.crm import leads as L
from app.modules.crm.deps import CRM, CrmDb, audit
from app.modules.crm.identities import normalize
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["calls"], dependencies=CRM)
public = APIRouter(prefix="/api/v1/twilio", tags=["calls"], dependencies=CRM)
Admin = Annotated[CurrentUser, require("settings.manage")]
Worker = Annotated[CurrentUser, require("leads.edit")]
SID = r"^AC[0-9a-f]{32}$"


class TwilioIn(BaseModel):
    account_sid: str = Field(pattern=SID)
    auth_token: str | None = Field(default=None, min_length=8, max_length=200)  # keep if empty
    numbers: list[str] = Field(min_length=1, max_length=20)
    forward_to: str | None = Field(default=None, max_length=40)


class TwilioOut(BaseModel):
    connected: bool
    account_sid: str | None = None
    numbers: list[str] = []
    forward_to: str | None = None
    voice_url: str  # paste into each Twilio number: "A call comes in" → this, HTTP POST
    test_mode: bool


class MyPhoneIn(BaseModel):
    phone: str | None = Field(default=None, max_length=40)


class MyPhoneOut(BaseModel):
    phone: str | None
    calling: bool  # the company has a calling account, so the Call button rings this phone


class CallStartOut(BaseModel):
    status: str = "ringing_you"  # Twilio is ringing the rep's phone first


async def _account(db) -> CallingAccount | None:
    return await db.scalar(select(CallingAccount).where(CallingAccount.provider == "twilio"))


async def _e164(db, tenant_id: uuid.UUID, raw: str) -> str:
    return normalize("phone", raw, await L.tenant_country(db, tenant_id))


def _out(acct: CallingAccount | None, request: Request) -> TwilioOut:
    from app.core.config import get_settings

    return TwilioOut(
        connected=acct is not None, account_sid=acct.account_sid if acct else None,
        numbers=acct.numbers if acct else [], forward_to=acct.forward_to if acct else None,
        voice_url=f"{T.origin(request)}/api/v1/twilio/voice",
        test_mode=get_settings().twilio_mode == "test",
    )  # fmt: skip


# ---------- settings ----------
@router.get("/calling/twilio", response_model=TwilioOut)
async def get_twilio(request: Request, db: CrmDb, actor: Admin) -> TwilioOut:
    return _out(await _account(db), request)


@router.put("/calling/twilio", response_model=TwilioOut)
async def put_twilio(body: TwilioIn, request: Request, db: CrmDb, actor: Admin) -> TwilioOut:
    """Connect (or change) the company's own Twilio account. The token is checked with Twilio
    first and stored encrypted; it is never shown again."""
    tid = actor.user.tenant_id
    acct = await _account(db)
    if acct is None and not body.auth_token:
        raise Invalid("Enter the auth token")
    numbers = list(dict.fromkeys([await _e164(db, tid, n) for n in body.numbers]))
    forward = await _e164(db, tid, body.forward_to) if body.forward_to else None
    if acct is None:
        acct = CallingAccount(id=uuid.uuid4(), tenant_id=tid, provider="twilio")
        db.add(acct)
    acct.account_sid, acct.numbers, acct.forward_to = body.account_sid, numbers, forward
    if body.auth_token:
        acct.auth_token_enc = SEC.encrypt(body.auth_token)
    await T.client(acct).verify()
    await db.flush()
    after = {"provider": "twilio", "account_sid": acct.account_sid, "numbers": numbers}
    await audit(db, actor, "calling.connected", "calling_account", acct.id, None, after)
    return _out(acct, request)


@router.delete("/calling/twilio", status_code=status.HTTP_204_NO_CONTENT)
async def delete_twilio(db: CrmDb, actor: Admin) -> None:
    acct = await _account(db)
    if acct is not None:
        await db.delete(acct)
        await audit(db, actor, "calling.disconnected", "calling_account", acct.id)


@router.get("/calling/my-phone", response_model=MyPhoneOut)
async def my_phone(db: CrmDb, actor: ActiveUser) -> MyPhoneOut:
    return MyPhoneOut(phone=actor.user.phone, calling=await _account(db) is not None)


@router.put("/calling/my-phone", response_model=MyPhoneOut)
async def set_my_phone(body: MyPhoneIn, db: CrmDb, actor: ActiveUser) -> MyPhoneOut:
    """The phone the Call button rings first (the rep's own mobile)."""
    user = await db.get(User, actor.user.id)
    user.phone = await _e164(db, user.tenant_id, body.phone) if body.phone else None
    return MyPhoneOut(phone=user.phone, calling=await _account(db) is not None)


# ---------- click-to-call ----------
@router.post("/leads/{lead_id}/call", response_model=CallStartOut)
async def call_lead(lead_id: uuid.UUID, request: Request, db: CrmDb, actor: Worker) -> CallStartOut:
    """Twilio rings the rep's phone; when the rep answers, it connects the lead."""
    lead = await L.get_visible(db, actor, lead_id)
    acct = await _account(db)
    if acct is None or not acct.numbers:
        raise Invalid(
            "Connect your calling account first (Settings → Calls)", code="calling_not_connected"
        )
    if not actor.user.phone:
        raise Invalid("Add your phone number in My account first", code="my_phone_missing")
    if not lead.primary_phone:
        raise Invalid("This lead has no phone number", code="lead_has_no_phone")
    if not await hit(f"rl:call:{actor.user.id}", 10, 60):
        raise Invalid("Too many calls started. Wait a minute.", code="rate_limited")
    token = await T.new_context({"tenant_id": str(acct.tenant_id), "direction": "out",
                                 "user_id": str(actor.user.id), "number": lead.primary_phone,
                                 "from": acct.numbers[0]})  # fmt: skip
    await T.client(acct).create_call(
        to=actor.user.phone,
        from_=acct.numbers[0],
        url=T.link(T.origin(request), "connect", ctx=token),
    )
    return CallStartOut()


# ---------- requests from Twilio ----------
def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


async def _checked(request: Request, db) -> tuple[CallingAccount, dict[str, str]]:
    """The company's account and Twilio's fields, only when Twilio's signature is right."""
    acct = await _account(db)
    raw = await request.body()  # Twilio posts a plain URL-encoded form
    if len(raw) > 64 * 1024:
        raise NotFound("Not found")
    form = dict(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))
    if acct is None or not T.signature_ok(acct, T.external_url(request), form,
                                          request.headers.get("x-twilio-signature")):  # fmt: skip
        raise NotFound("Not found")
    return acct, form


@public.post("/voice")
async def incoming(request: Request, ws: WorkspaceDep, db: CrmDb) -> Response:
    """A call to one of the company's Twilio numbers: ring the lead's owner, then the company's
    main number; nobody answers → voicemail."""
    acct, form = await _checked(request, db)
    base = T.origin(request)
    caller = form.get("From", "")
    lead = None
    try:
        lead = await S.find_lead(db, await _e164(db, ws.id, caller))
    except Invalid:
        pass
    owner = await db.get(User, lead.owner_user_id) if lead and lead.owner_user_id else None
    ring = owner.phone if owner and owner.status == "active" and owner.phone else acct.forward_to
    token = await T.new_context({"tenant_id": str(ws.id), "direction": "in", "number": caller,
                                 "user_id": str(owner.id) if owner else None})  # fmt: skip
    cfg = await S.settings_of(db, ws.id)
    if not ring:  # nobody to ring: a missed call, and the caller may leave a message
        call = await S.report(
            db, ws.id, actor=None, user_id=None, source="twilio",
            external_id=form.get("CallSid") or token, direction="in", status="missed",
            number=caller, started_at=L.now(), duration_seconds=0,
        )  # fmt: skip
        if call is None or not cfg["record"]:
            return _xml(T.twiml("<Say>Sorry, no one could take your call.</Say><Hangup/>"))
        await T.save_context(token, {"tenant_id": str(ws.id), "direction": "in",
                                     "number": caller, "call_id": str(call.id)})  # fmt: skip
        return _xml(T.twiml(T.voicemail(base, token)))
    caller_id = form.get("To") or acct.numbers[0]
    return _xml(T.twiml(T.dial(base, token, ring, caller_id, cfg["record"])))


@public.post("/connect")
async def connect(request: Request, ws: WorkspaceDep, db: CrmDb, ctx: str = "") -> Response:
    """The rep answered (click-to-call): connect the lead."""
    _, _form = await _checked(request, db)
    data = await T.context(ctx)
    if data is None or data["tenant_id"] != str(ws.id):
        return _xml(T.twiml("<Say>This call has expired.</Say>"))
    cfg = await S.settings_of(db, ws.id)
    return _xml(
        T.twiml(T.dial(T.origin(request), ctx, data["number"], data["from"], cfg["record"], 30))
    )


STATUS = {"completed": "answered", "answered": "answered", "no-answer": "no_answer",
          "busy": "busy", "failed": "failed", "canceled": "no_answer"}  # fmt: skip


@public.post("/dial-done")
async def dial_done(request: Request, ws: WorkspaceDep, db: CrmDb, ctx: str = "") -> Response:
    """The dialled side finished: the call goes into the pipeline. Unanswered incoming calls
    get the voicemail prompt."""
    _, form = await _checked(request, db)
    data = await T.context(ctx)
    if data is None or data["tenant_id"] != str(ws.id):
        return _xml(T.twiml("<Hangup/>"))
    state = STATUS.get(form.get("DialCallStatus", ""), "failed")
    if data["direction"] == "in" and state != "answered":
        state = "missed"
    seconds = int(form.get("DialCallDuration") or 0) if state == "answered" else 0
    call = await S.report(
        db, ws.id, actor=None, user_id=uuid.UUID(data["user_id"]) if data.get("user_id") else None,
        source="twilio", external_id=form.get("CallSid") or ctx, direction=data["direction"],
        status=state, number=data["number"], started_at=L.now() - timedelta(seconds=seconds),
        duration_seconds=seconds,
    )  # fmt: skip
    if call is not None:
        data["call_id"] = str(call.id)
        if data.get("recording_url") and not call.recording_path:
            call.recording_pending_url = data.pop("recording_url")
            await _fetch_soon()
        await T.save_context(ctx, data)
    if data["direction"] == "in" and state == "missed" and call is not None:
        cfg = await S.settings_of(db, ws.id)
        if cfg["record"]:
            return _xml(T.twiml(T.voicemail(T.origin(request), ctx)))
    return _xml(T.twiml("<Hangup/>"))


@public.post("/hangup")
async def hangup(request: Request, db: CrmDb) -> Response:
    """After the voicemail: end the call."""
    await _checked(request, db)
    return _xml(T.twiml("<Hangup/>"))


@public.post("/recording", status_code=status.HTTP_204_NO_CONTENT)
async def recording(request: Request, ws: WorkspaceDep, db: CrmDb, ctx: str = "") -> None:
    """Twilio has the recording (or the voicemail): the worker fetches it into Core."""
    _, form = await _checked(request, db)
    data = await T.context(ctx)
    url = form.get("RecordingUrl")
    if (
        data is None
        or data["tenant_id"] != str(ws.id)
        or form.get("RecordingStatus") != "completed"
        or not url
    ):
        return
    call = await db.get(Call, uuid.UUID(data["call_id"])) if data.get("call_id") else None
    if call is None:  # the recording came before the call ended: keep it for dial-done
        data["recording_url"] = url
        await T.save_context(ctx, data)
        return
    if not call.recording_path and not call.recording_pending_url:
        call.recording_pending_url = url
        await _fetch_soon()


async def _fetch_soon() -> None:
    from app.workers.queue import enqueue

    await enqueue("call_recordings_job", job_id="call_recordings_job", defer_by=3)

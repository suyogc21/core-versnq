"""The one shape every CRM connector has (docs/plans/crm-connectors-plan.md). The call pipeline
and the inbox never know which CRM it is: they only produce events; the sync job uses this."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx


class CrmError(Exception):
    """The CRM said no or couldn't be reached. retry: worth trying again later."""

    def __init__(self, message: str, *, retry: bool = True):
        super().__init__(message[:300])
        self.retry = retry


@dataclass(frozen=True)
class NewLead:
    name: str | None
    phone: str  # E.164, e.g. +919876543210
    email: str | None
    owner_email: str | None


@dataclass(frozen=True)
class CallInfo:
    call_id: uuid.UUID
    direction: str  # in / out
    status: str  # answered, missed, no_answer, busy, failed
    number: str  # the lead's side, E.164
    started_at: datetime
    seconds: int
    rep_email: str | None
    rep_phone: str | None


@dataclass(frozen=True)
class MessageInfo:
    message_id: uuid.UUID
    direction: str  # in / out
    text: str
    at: datetime
    rep_email: str | None


@dataclass(frozen=True)
class CallNote:
    """After a call: its recording link and, with ACE, the summary and next step."""

    call_id: uuid.UUID
    at: datetime
    summary: str | None
    next_step: str | None
    recording_url: str | None

    def text(self) -> str:
        parts = [f"Summary: {self.summary}" if self.summary else None,
                 f"Next step: {self.next_step}" if self.next_step else None,
                 f"Recording: {self.recording_url}" if self.recording_url else None]  # fmt: skip
        return "\n".join(p for p in parts if p)


class Connector(Protocol):
    async def find_by_phone(self, phone: str) -> str | None: ...
    async def create_lead(self, lead: NewLead) -> str: ...
    async def log_call(self, lead_id: str, call: CallInfo) -> str | None: ...
    async def log_message(self, lead_id: str, msg: MessageInfo) -> str | None: ...
    async def log_note(self, lead_id: str, note: CallNote) -> str | None: ...


def client() -> httpx.AsyncClient:  # patched in tests
    return httpx.AsyncClient(timeout=15, follow_redirects=False)


def check(r: httpx.Response) -> None:
    """Too many requests / the CRM's own trouble: later. Wrong keys or a refused request: no."""
    if r.status_code == 429:
        raise CrmError("The CRM says too many requests; trying again shortly")
    if r.status_code in (401, 403):
        raise CrmError(f"The CRM refused the keys ({r.status_code})", retry=False)
    if r.status_code >= 500:
        raise CrmError(f"The CRM answered {r.status_code}")
    if r.status_code >= 400:
        raise CrmError(f"The CRM answered {r.status_code}: {r.text[:200]}", retry=False)


async def send(method: str, url: str, **kw) -> httpx.Response:
    try:
        async with client() as c:
            r = await c.request(method, url, **kw)
    except httpx.TimeoutException:
        raise CrmError("No answer from the CRM within 15 seconds") from None
    except httpx.HTTPError as e:
        raise CrmError(f"Could not reach the CRM ({type(e).__name__})") from None
    check(r)
    return r

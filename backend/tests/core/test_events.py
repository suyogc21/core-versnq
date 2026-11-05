import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.events import CATALOGUE, UnknownEvent, emit
from app.core.events_model import Event
from app.core.modules import set_module
from app.core.tenancy import tenant_session
from tests.factories import make_workspace

SPEC = (
    Path(__file__).resolve().parents[3] / "docs/specs/Versnq Core — Product & Feature Spec (v0).md"
)


def test_catalogue_matches_the_spec():
    text = SPEC.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("**Outbound event catalogue"))
    assert set(CATALOGUE) == set(re.findall(r"`([a-z_]+\.[a-z_]+)`", line))


async def _count(tenant_id, type_=None):
    async with tenant_session(tenant_id) as s:
        q = select(func.count()).select_from(Event)
        if type_:
            q = q.where(Event.type == type_)
        return await s.scalar(q)


async def test_event_written_in_same_transaction():
    tenant_id, _ = await make_workspace()
    async with tenant_session(tenant_id) as s:
        assert await emit(s, tenant_id, "lead.created", {"lead_id": "x"}) is True
    assert await _count(tenant_id, "lead.created") == 1


async def test_rollback_leaves_no_event():
    tenant_id, _ = await make_workspace()
    with pytest.raises(RuntimeError):
        async with tenant_session(tenant_id) as s:
            await emit(s, tenant_id, "lead.created", {"lead_id": "x"})
            raise RuntimeError("the change failed")
    assert await _count(tenant_id) == 0


async def test_unknown_event_type_rejected():
    tenant_id, _ = await make_workspace()
    with pytest.raises(UnknownEvent):
        async with tenant_session(tenant_id) as s:
            await emit(s, tenant_id, "lead.teleported", {})


async def test_switched_off_module_emits_nothing():
    tenant_id, _ = await make_workspace()
    async with tenant_session(tenant_id) as s:
        await set_module(s, tenant_id, "money", False)
        assert await emit(s, tenant_id, "invoice.created", {"invoice_id": "i"}) is False
    assert await _count(tenant_id) == 0

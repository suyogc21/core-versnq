"""Conditions on a lead or deal, shared by scoring rules and automations:
{"field": "source_id", "op": "is", "value": "<id>"}. Any built-in or custom field, plus tags.

Operators: is, is_not, any_of, none_of, contains, empty, not_empty, gt, lt.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Invalid
from app.modules.crm import leads as L
from app.modules.crm.models import Deal, Lead, Tagging

OPS = {"is", "is_not", "any_of", "none_of", "contains", "empty", "not_empty", "gt", "lt"}
NO_VALUE = {"empty", "not_empty"}

LEAD_FIELDS = {
    "kind", "first_name", "last_name", "org_name", "email", "phone", "website", "industry",
    "city", "region", "country_code", "preferred_language", "source_id", "stage_id",
    "owner_user_id", "team_id", "is_open", "created_via", "origin", "campaign", "utm_source",
    "utm_medium", "utm_campaign", "utm_term", "utm_content", "score", "fit_score",
    "engagement_score", "score_band", "intent", "email_consent", "whatsapp_consent",
    "last_disposition", "tags",
}  # fmt: skip
DEAL_FIELDS = {
    "name", "pipeline_id", "stage_id", "status", "owner_user_id", "team_id", "amount_minor",
    "currency", "expected_close_on", "lost_reason_id", "tags",
}  # fmt: skip
# Fit scoring cannot read the score itself.
SCORE_FIELDS = {"score", "fit_score", "engagement_score", "score_band"}


def _plain(v):
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


async def _tag_ids(db: AsyncSession, col, subject_id) -> list[str]:
    return [str(t) for t in (await db.scalars(select(Tagging.tag_id).where(col == subject_id)))]


async def lead_facts(db: AsyncSession, lead: Lead) -> dict:
    facts = {f: _plain(getattr(lead, f, None)) for f in LEAD_FIELDS - {"email", "phone", "tags"}}
    facts["email"], facts["phone"] = lead.primary_email, lead.primary_phone
    facts["tags"] = await _tag_ids(db, Tagging.lead_id, lead.id)
    return facts | dict(lead.custom_fields or {})


async def deal_facts(db: AsyncSession, deal: Deal) -> dict:
    facts = {f: _plain(getattr(deal, f, None)) for f in DEAL_FIELDS - {"tags"}}
    facts["tags"] = await _tag_ids(db, Tagging.deal_id, deal.id)
    return facts | dict(deal.custom_fields or {})


async def check(db: AsyncSession, subject: str, cond: dict, *, for_fit: bool = False) -> dict:
    """Validate one condition for 'lead' or 'deal'. Returns the clean form."""
    field, op, value = cond.get("field"), cond.get("op"), cond.get("value")
    known = (LEAD_FIELDS if subject == "lead" else DEAL_FIELDS) | set(
        await L.lead_fields(db, subject)
    )
    if for_fit:
        known -= SCORE_FIELDS
    if field not in known:
        raise Invalid(f"Unknown field in a condition: {field}")
    if op not in OPS:
        raise Invalid(f"Unknown comparison: {op}")
    if op in NO_VALUE:
        return {"field": field, "op": op}
    if op in ("any_of", "none_of"):
        if not isinstance(value, list) or not value or len(value) > 100:
            raise Invalid("Choose one or more values")
        value = [str(v) for v in value]
    elif value is None or isinstance(value, list | dict) or len(str(value)) > 200:
        raise Invalid("Give a value to compare with")
    if op in ("gt", "lt"):
        _num_or_text(value)
    return {"field": field, "op": op, "value": value}


def _num_or_text(v):
    if isinstance(v, bool):
        return str(v).lower()
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return str(v)


def _norm(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    return str(v).strip().lower()


def match(cond: dict, facts: dict) -> bool:
    op, have = cond["op"], facts.get(cond["field"])
    is_list = isinstance(have, list)
    empty = have is None or have == "" or have == []
    if op == "empty":
        return empty
    if op == "not_empty":
        return not empty
    want = cond.get("value")
    if op in ("any_of", "none_of"):
        wants = {_norm(w) for w in want}
        hit = (
            bool(wants & {_norm(h) for h in have})
            if is_list
            else (not empty and _norm(have) in wants)
        )
        return hit if op == "any_of" else not hit
    if op in ("is", "is_not"):
        hit = (
            (_norm(want) in {_norm(h) for h in have})
            if is_list
            else (not empty and _norm(have) == _norm(want))
        )
        return hit if op == "is" else not hit
    if empty:
        return False
    if op == "contains":
        if is_list:
            return _norm(want) in {_norm(h) for h in have}
        return _norm(want) in _norm(have)
    a, b = _num_or_text(have), _num_or_text(want)
    if type(a) is not type(b):
        return False
    return a > b if op == "gt" else a < b


def match_all(conds: list[dict], facts: dict) -> bool:
    return all(match(c, facts) for c in conds)

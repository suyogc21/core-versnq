"""Turning outside data (a CSV row, a web form post) into an Incoming lead.

Targets are built-in names (below) or `cf.<custom field key>`. Several columns may map to the
same target (e.g. two phone columns). Text is converted the forgiving way people type it:
dropdowns match an option's label or value in any case, multi-selects split on ; or ,
numbers drop thousands separators, dates accept 2026-11-07, 07/11/2026 and 07-11-2026.
A value that still does not fit is reported, never silently guessed.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.errors import Invalid
from app.modules.crm import fields as F
from app.modules.crm import leads as L
from app.modules.crm.models import CustomFieldDefinition

# target -> label shown when mapping columns
BUILTIN_TARGETS: dict[str, str] = {
    "full_name": "Full name",
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "phone": "Phone",
    "whatsapp": "WhatsApp number",
    "linkedin": "LinkedIn profile",
    "org_name": "Company / organisation",
    "website": "Website",
    "industry": "Industry",
    "city": "City",
    "region": "State / region",
    "country_code": "Country code (IN, AE, US…)",
    "preferred_language": "Language",
    "message": "Message / notes",
    "campaign": "Campaign",
    "utm_source": "UTM source",
    "utm_medium": "UTM medium",
    "utm_campaign": "UTM campaign",
    "utm_term": "UTM term",
    "utm_content": "UTM content",
    "external_id": "Your own ID for this lead",
    "consent_email": "Agreed to email (yes/no)",
    "consent_whatsapp": "Agreed to WhatsApp (yes/no)",
}
IMPORT_ONLY_TARGETS = {
    "owner_email": "Owner (their email)",
    "stage": "Stage (its name)",
    "source": "Source (its name)",
}
ATTRIBUTION_KEYS = ("referrer", "page_url", "landing_page", "gclid", "fbclid", "msclkid")
YES = {"1", "true", "yes", "y", "on", "agreed", "opt-in", "opted_in"}
NO = {"0", "false", "no", "n", "off", "opt-out", "opted_out"}
_SPLIT = re.compile(r"\s*[;,]\s*")
_ALIASES = {
    "name": "full_name", "fullname": "full_name", "your name": "full_name",
    "firstname": "first_name", "first": "first_name", "lastname": "last_name",
    "surname": "last_name", "last": "last_name", "e-mail": "email", "email address": "email",
    "mobile": "phone", "mobile number": "phone", "phone number": "phone", "contact number": "phone",
    "whatsapp number": "whatsapp", "company": "org_name", "company name": "org_name",
    "organisation": "org_name", "organization": "org_name", "state": "region",
    "country": "country_code", "language": "preferred_language", "comments": "message",
    "notes": "message", "enquiry": "message", "id": "external_id", "owner": "owner_email",
    "lead owner": "owner_email", "status": "stage", "lead source": "source",
}  # fmt: skip


def _norm(header: str) -> str:
    return " ".join(re.sub(r"[_\-\.]+", " ", header.strip().lower()).split())


_ALIASES = {_norm(k): v for k, v in _ALIASES.items()}  # compare like headers are compared


def suggest(headers: list[str], defs: list[CustomFieldDefinition], import_mode: bool) -> dict:
    """Best-guess column → target, by name or label (each target used once)."""
    targets = dict(BUILTIN_TARGETS)
    if import_mode:
        targets |= IMPORT_ONLY_TARGETS
    by_name = {_norm(k): k for k in targets} | {_norm(v): k for k, v in targets.items()}
    by_name |= {a: t for a, t in _ALIASES.items() if t in targets}
    for d in defs:
        by_name.setdefault(_norm(d.key), f"cf.{d.key}")
        by_name.setdefault(_norm(d.label), f"cf.{d.key}")
    out, used = {}, set()
    for h in headers:
        target = by_name.get(_norm(h))
        if target and (target not in used or target in ("phone", "email")):
            out[h] = target
            used.add(target)
    return out


def from_text(defn: dict, raw):
    """A typed-in value → the stored form of a custom field (raises Invalid if it won't fit)."""
    if isinstance(raw, str):
        raw = raw.strip()
    if raw in (None, "", []):
        return None
    ftype = defn["type"]
    if ftype in ("select", "multi_select") and isinstance(raw, str | list):
        options = defn.get("options", [])
        lookup = {o["value"].lower(): o["value"] for o in options}
        lookup |= {o["label"].lower(): o["value"] for o in options}
        parts = (
            raw if isinstance(raw, list) else ([raw] if ftype == "select" else _SPLIT.split(raw))
        )
        mapped = [
            lookup.get(str(p).strip().lower(), str(p).strip()) for p in parts if str(p).strip()
        ]
        raw = mapped[0] if ftype == "select" else mapped
    elif ftype == "number" and isinstance(raw, str):
        raw = raw.replace(",", "").replace(" ", "")
    elif ftype == "date" and isinstance(raw, str):
        raw = _date(raw)
    return F.coerce(defn, raw)


def _date(text: str) -> str:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return text  # coerce() reports it


def yes_no(raw: str | None) -> bool | None:
    value = (raw or "").strip().lower()
    if value in YES:
        return True
    if value in NO:
        return False
    return None


@dataclass
class Parsed:
    identities: list[L.IdentityInput] = field(default_factory=list)
    fields: dict = field(default_factory=dict)
    custom_fields: dict = field(default_factory=dict)
    consents: dict = field(default_factory=dict)
    message_parts: list[str] = field(default_factory=list)
    external_id: str | None = None
    owner_email: str | None = None
    stage: str | None = None
    source: str | None = None
    problems: list[str] = field(default_factory=list)  # values that did not fit


def parse(values: dict[str, list[str]], defs: dict[str, CustomFieldDefinition]) -> Parsed:
    """values: target -> raw strings (several columns may share a target)."""
    p = Parsed()

    def first(target: str) -> str | None:
        for v in values.get(target, []):
            if v and v.strip():
                return v.strip()
        return None

    for kind, target, whatsapp in (
        ("phone", "phone", False),
        ("phone", "whatsapp", True),
        ("email", "email", False),
        ("linkedin", "linkedin", False),
    ):
        for raw in values.get(target, []):
            for item in _SPLIT.split(raw.strip()) if kind == "email" else [raw.strip()]:
                if item:
                    p.identities.append(L.IdentityInput(kind, item[:320], is_whatsapp=whatsapp))

    full = first("full_name")
    if full and not (first("first_name") or first("last_name")):
        bits = full.split(None, 1)
        p.fields["first_name"] = bits[0][:120]
        if len(bits) > 1:
            p.fields["last_name"] = bits[1][:120]
    limits = {"org_name": 200, "website": 300, "industry": 120, "city": 120, "region": 120,
              "preferred_language": 10, "first_name": 120, "last_name": 120}  # fmt: skip
    for key in ("first_name", "last_name", "org_name", "website", "industry", "city", "region"):
        if v := first(key):
            p.fields[key] = v[: limits[key]]
    if v := first("preferred_language"):
        p.fields["preferred_language"] = v.lower()[:10]
    if v := first("country_code"):
        if re.fullmatch(r"[A-Za-z]{2}", v):
            p.fields["country_code"] = v.upper()
        else:
            p.problems.append(f"Country code '{v}' should be two letters like IN")
            p.message_parts.append(f"Country: {v}")
    for key in ("campaign", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
        if v := first(key):
            p.fields[key] = v[:200]
    for channel in ("email", "whatsapp"):
        answer = yes_no(first(f"consent_{channel}"))
        if answer is not None:
            p.consents[channel] = "opted_in" if answer else "opted_out"
    notes = [v.strip() for v in values.get("message", []) if v and v.strip()]
    if notes:  # several columns may be notes (e.g. a CRM export's extra fields)
        p.message_parts.append("\n".join(notes)[:4000])
    p.external_id = (first("external_id") or "")[:200] or None
    p.owner_email = first("owner_email")
    p.stage, p.source = first("stage"), first("source")

    for target, raws in values.items():
        if not target.startswith("cf."):
            continue
        key = target[3:]
        d = defs.get(key)
        if d is None:
            continue
        raw = [r for r in raws if r and r.strip()]
        if not raw:
            continue
        joined = raw if d.type == "multi_select" and len(raw) > 1 else raw[0]
        try:
            value = from_text({"type": d.type, "label": d.label, "options": d.options}, joined)
        except Invalid as e:
            p.problems.append(e.detail)
            p.message_parts.append(f"{d.label}: {joined}")
            continue
        if value is not None:
            p.custom_fields[key] = value
    return p

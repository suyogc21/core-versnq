"""Custom field rules shared by lead custom fields and activity-type fields. Generic: a field
knows its type and options, never what business it belongs to."""

import re
from datetime import date

from app.core.errors import Invalid

KEY = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
TYPES = {"text", "number", "date", "select", "multi_select", "phone", "email", "url"}
CHOICE_TYPES = {"select", "multi_select"}
UNIQUE_TYPES = {"text", "number", "email", "phone", "url"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Built-in lead fields a stage may require (besides custom field keys).
BUILTIN_REQUIRABLE = {
    "first_name",
    "last_name",
    "org_name",
    "email",
    "phone",
    "owner",
    "website",
    "city",
    "region",
    "country_code",
    "preferred_language",
}
# Custom keys may not shadow built-in lead columns.
RESERVED_KEYS = BUILTIN_REQUIRABLE | {
    "id",
    "kind",
    "display_name",
    "stage",
    "source",
    "owner_user_id",
    "stage_id",
    "source_id",
    "custom_fields",
    "next_follow_up_at",
}


def check_options(field_type: str, options: list[dict]) -> list[dict]:
    if field_type not in CHOICE_TYPES:
        if options:
            raise Invalid("Only dropdown fields have options")
        return []
    if not options:
        raise Invalid("A dropdown needs at least one option")
    seen: set[str] = set()
    clean = []
    for o in options:
        value, label = str(o.get("value", "")).strip(), str(o.get("label", "")).strip()
        if not value or not label or len(value) > 100 or len(label) > 120:
            raise Invalid("Each option needs a value and a label (up to 100/120 characters)")
        if value in seen:
            raise Invalid(f"Option '{value}' appears twice")
        seen.add(value)
        item = {"value": value, "label": label}
        if o.get("parent"):
            item["parent"] = str(o["parent"])
        clean.append(item)
    return clean


def check_dependency(options: list[dict], parent_options: list[dict] | None) -> None:
    """A linked dropdown: every option names a parent option that exists."""
    if parent_options is None:
        if any("parent" in o for o in options):
            raise Invalid("Options name a parent, but the field does not depend on another field")
        return
    parents = {o["value"] for o in parent_options}
    for o in options:
        if o.get("parent") not in parents:
            raise Invalid(f"Option '{o['value']}' must belong to one of the parent field's options")


def check_field_list(fields: list[dict]) -> list[dict]:
    """Activity-type fields: key, label, type, options, required."""
    keys: set[str] = set()
    clean = []
    for f in fields:
        key, label, ftype = f.get("key", ""), str(f.get("label", "")).strip(), f.get("type")
        if not KEY.match(key) or key in keys:
            raise Invalid(f"Field key '{key}' is invalid or repeated")
        if not label or ftype not in TYPES:
            raise Invalid(f"Field '{key}' needs a label and a known type")
        keys.add(key)
        clean.append(
            {
                "key": key,
                "label": label,
                "type": ftype,
                "options": check_options(ftype, f.get("options", [])),
                "required": bool(f.get("required", False)),
            }
        )
    return clean


def coerce(field: dict, value):
    """Validate one value against its field. Returns the stored form (None = empty)."""
    if value is None or value == "" or value == []:
        return None
    ftype, label = field["type"], field["label"]
    allowed = {o["value"] for o in field.get("options", [])}
    if ftype == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise Invalid(f"{label}: enter a number") from None
        return int(value) if float(value).is_integer() else float(value)
    if ftype == "date":
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise Invalid(f"{label}: use a date like 2026-11-07") from None
    if ftype == "select":
        if str(value) not in allowed:
            raise Invalid(f"{label}: '{value}' is not one of the options")
        return str(value)
    if ftype == "multi_select":
        values = value if isinstance(value, list) else [value]
        bad = [v for v in values if str(v) not in allowed]
        if bad:
            raise Invalid(f"{label}: '{bad[0]}' is not one of the options")
        return sorted({str(v) for v in values})
    text = str(value).strip()
    if len(text) > 1000:
        raise Invalid(f"{label}: too long")
    if ftype == "email" and not EMAIL.match(text):
        raise Invalid(f"{label}: enter a valid email")
    if ftype == "url" and not text.startswith(("http://", "https://")):
        raise Invalid(f"{label}: enter a link starting with https://")
    return text or None


def unique_form(value) -> str:
    """How a unique value is compared: case- and space-insensitive."""
    return str(value).strip().lower()[:500]

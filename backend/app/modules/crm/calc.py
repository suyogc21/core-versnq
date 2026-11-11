"""Calculated custom fields on leads, deals and records: checking formulas when a field is set
up, and filling the values in whenever the lead/deal/record is saved (and nightly)."""

from datetime import UTC, datetime
from decimal import Decimal

from app.core.errors import Invalid
from app.core.money import EXPONENT
from app.modules.crm import formula as FX

# Built-in values a formula may use, per kind of record.
BUILTINS: dict[str, dict[str, str]] = {
    "lead": {"score": "number", "created_on": "date"},
    "deal": {"amount": "number", "expected_close_on": "date", "created_on": "date"},
    "record": {"created_on": "date"},
}


def _kind(entity: str) -> str:
    return entity if entity in ("lead", "deal") else "record"


def input_types(defs: dict, entity: str, *, skip: str | None = None) -> dict[str, str]:
    """Field keys a formula may read -> number/date."""
    out = dict(BUILTINS[_kind(entity)])
    for d in defs.values():
        if d.key == skip:
            continue
        if d.type in ("number", "calculated"):
            out[d.key] = "number"
        elif d.type == "date":
            out[d.key] = "date"
    return out


def check_formula(defs: dict, entity: str, key: str, text: str) -> str:
    """Valid, refers to existing number/date fields, and makes no circle with other formulas."""
    node = FX.check(text, input_types(defs, entity, skip=key))
    formulas = {
        d.key: FX.parse(d.formula) for d in defs.values() if d.type == "calculated" and d.formula
    }
    formulas[key] = node
    FX.order(formulas)
    return text.strip()


def _builtin_values(obj, entity: str) -> dict:
    created = getattr(obj, "created_at", None) or datetime.now(UTC)
    values = {"created_on": created.date()}
    if entity == "lead":
        values["score"] = Decimal(obj.score or 0)
    if entity == "deal":
        exp = EXPONENT.get(obj.currency, 2)
        values["amount"] = Decimal(obj.amount_minor or 0) / (Decimal(10) ** exp)
        values["expected_close_on"] = obj.expected_close_on
    return values


def fill(defs: dict, entity: str, obj, merged: dict) -> list[str]:
    """Recompute every calculated field into `merged`. Returns keys whose value changed."""
    calcs = {d.key: d for d in defs.values() if d.type == "calculated" and d.formula}
    if not calcs:
        return []
    nodes = {k: FX.parse(d.formula) for k, d in calcs.items()}
    values = _builtin_values(obj, entity)
    for d in defs.values():
        if d.type in ("number", "date"):
            values[d.key] = FX.as_input(merged.get(d.key), d.type)
    today = datetime.now(UTC).date()
    changed = []
    for key in FX.order(nodes):
        result = FX.to_stored(FX.evaluate(nodes[key], values, today))
        values[key] = FX.as_input(result, "number")
        if merged.get(key) != result:
            changed.append(key)
        if result is None:
            merged.pop(key, None)
        else:
            merged[key] = result
    return changed


def refuse_input(defs: dict, incoming: dict, current: dict) -> None:
    """Typing into a calculated field is refused; a form sending back the value it was
    shown (unchanged) is fine, and that key is then ignored."""
    for key in list(incoming):
        if key in defs and defs[key].type == "calculated":
            if incoming[key] != current.get(key):
                raise Invalid(f"{defs[key].label} is calculated and cannot be typed in")
            del incoming[key]


def users_of(defs: dict, key: str) -> list[str]:
    """Labels of calculated fields whose formula reads `key`."""
    return [
        d.label
        for d in defs.values()
        if d.type == "calculated" and d.formula and key in FX.names(FX.parse(d.formula))
    ]


def ensure_valid_field(body_type: str, formula: str | None) -> None:
    if body_type == "calculated" and not (formula or "").strip():
        raise Invalid("A calculated field needs a formula")
    if body_type != "calculated" and formula:
        raise Invalid("Only calculated fields have a formula")


async def recalc_tenant(tenant_id) -> int:
    """Nightly: formulas that use today() move with the date."""
    from sqlalchemy import select

    from app.core.tenancy import tenant_session
    from app.modules.crm import leads as L
    from app.modules.crm.models import CustomFieldDefinition, Deal, Lead, Record, RecordType

    changed = 0
    async with tenant_session(tenant_id) as db:
        dated = (
            await db.scalars(
                select(CustomFieldDefinition.entity)
                .where(
                    CustomFieldDefinition.type == "calculated",
                    CustomFieldDefinition.formula.ilike("%today(%"),
                )
                .distinct()
            )
        ).all()
        for entity in dated:
            if entity == "lead":
                q = select(Lead)
            elif entity == "deal":
                q = select(Deal)
            else:
                type_id = await db.scalar(select(RecordType.id).where(RecordType.key == entity[3:]))
                q = select(Record).where(Record.record_type_id == type_id)
            for obj in (await db.scalars(q.limit(100_000))).all():
                changed += bool(await L.refresh_calculated(db, obj, entity))
    return changed

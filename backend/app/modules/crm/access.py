"""Field permissions (step 8, Decision log #38).

For each role, kind of record and field the admin picks Edit (no row), View only or Hidden.
Fields are named "cf.<key>" for custom fields, or by their built-in name below. Owner and Admin
always edit everything, and so does anything running without a person (automations, nightly
jobs). The name and the owner can never be restricted; phone and email can be view only but
not hidden, so a rep can always call and write.

Everything that shows or changes a record asks `rules()` once and then:
- `redact()` removes hidden values before the record leaves the server (page, lists, export,
  API — keys follow their role);
- `check_value()` refuses a change to a field the person may not edit.
A calculated field built from a hidden field is hidden too, unless the admin allowed it.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden
from app.modules.auth.deps import CurrentUser
from app.modules.crm import formula as FX
from app.modules.crm.models import CustomFieldDefinition, FieldPermission

UNRESTRICTED_ROLES = ("owner", "admin")

# built-in fields that can be restricted, per kind of record -> (label, attributes it covers)
BUILTINS: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {
    "lead": {
        "email": ("Email", ()),
        "phone": ("Phone", ()),
        "org_name": ("Company", ("org_name",)),
        "website": ("Website", ("website",)),
        "industry": ("Industry", ("industry",)),
        "employee_range": ("Company size", ("employee_range",)),
        "city": ("City", ("city",)),
        "region": ("Region", ("region",)),
        "country_code": ("Country", ("country_code",)),
        "preferred_language": ("Language", ("preferred_language",)),
        "unqualified_reason": ("Unqualified reason", ("unqualified_reason",)),
        "attribution": (
            "Campaign and UTM",
            ("campaign", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"),
        ),
    },
    "deal": {
        "amount": ("Value", ("amount_minor",)),
        "expected_close_on": ("Expected close", ("expected_close_on",)),
    },
}
NEVER_HIDDEN = {"email", "phone"}  # view only at most


def builtins(entity: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    return BUILTINS.get(entity, {})


def allowed_access(entity: str, name: str) -> tuple[str, ...]:
    if name in NEVER_HIDDEN and entity == "lead":
        return ("edit", "view")
    return ("edit", "view", "hidden")


@dataclass
class Rules:
    """One person's restrictions on one kind of record. Empty = edits everything."""

    entity: str
    access: dict[str, str] = field(default_factory=dict)  # field -> view / hidden
    labels: dict[str, str] = field(default_factory=dict)

    def hidden(self, name: str) -> bool:
        return self.access.get(name) == "hidden"

    def editable(self, name: str) -> bool:
        return name not in self.access

    @property
    def any(self) -> bool:
        return bool(self.access)

    def hidden_custom(self) -> set[str]:
        return {k[3:] for k, v in self.access.items() if v == "hidden" and k.startswith("cf.")}

    def locked_custom(self) -> set[str]:
        """Custom field keys this person cannot change."""
        return {k[3:] for k in self.access if k.startswith("cf.")}

    def redact_custom(self, values: dict | None) -> dict:
        hide = self.hidden_custom()
        return {k: v for k, v in (values or {}).items() if k not in hide}

    def redact(self, item) -> None:
        """Blank hidden fields on an output model (LeadOut, DealOut, CustomerOut, RecordOut)."""
        if not self.access:
            return
        if hasattr(item, "custom_fields"):
            item.custom_fields = self.redact_custom(item.custom_fields)
        for name, (_, attrs) in builtins(self.entity).items():
            if self.hidden(name):
                for a in attrs:
                    if hasattr(item, a):
                        setattr(item, a, None)

    def check_value(self, name: str, old, new) -> None:
        """Refuse a change to a field this person may not edit (unchanged values pass)."""
        if not self.editable(name) and old != new:
            raise Forbidden(f"You can't change {self.labels.get(name, name)}")


def unrestricted(actor: CurrentUser | None) -> bool:
    return actor is None or actor.role.key in UNRESTRICTED_ROLES


async def rules(db: AsyncSession, actor: CurrentUser | None, entity: str) -> Rules:
    if unrestricted(actor):
        return Rules(entity)
    rows = (
        await db.scalars(
            select(FieldPermission).where(
                FieldPermission.role_id == actor.role.id, FieldPermission.entity == entity
            )
        )
    ).all()
    access = {r.field: r.access for r in rows}
    defs = (
        await db.scalars(
            select(CustomFieldDefinition).where(CustomFieldDefinition.entity == entity)
        )
    ).all()
    labels = {f"cf.{d.key}": d.label for d in defs} | {
        k: label for k, (label, _) in builtins(entity).items()
    }
    # a calculated field shows nothing its inputs hide (unless the admin allowed it)
    hidden_inputs = {k for k, v in access.items() if v == "hidden"}
    if hidden_inputs:
        for d in defs:
            if d.type != "calculated" or not d.formula or d.show_with_hidden_inputs:
                continue
            try:
                reads = FX.names(FX.parse(d.formula))
            except Exception:  # noqa: BLE001  a broken formula simply shows nothing
                reads = set()
            reads = {f"cf.{n}" if f"cf.{n}" in labels else n for n in reads}
            if reads & hidden_inputs:
                access[f"cf.{d.key}"] = "hidden"
    return Rules(entity, access, labels)


async def for_role(db: AsyncSession, role_id: uuid.UUID, entity: str) -> dict[str, str]:
    rows = (
        await db.scalars(
            select(FieldPermission).where(
                FieldPermission.role_id == role_id, FieldPermission.entity == entity
            )
        )
    ).all()
    return {r.field: r.access for r in rows}

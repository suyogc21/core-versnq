from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.core import money
from app.core.modules import MODULES, module_states
from app.core.validators import valid_timezone
from app.modules.audit.models import record
from app.modules.auth.deps import ActiveUser, CurrentUser, TenantDb, require
from app.modules.settings.models import TenantSettings
from app.platform.packs import LABEL_KEYS

router = APIRouter(prefix="/api/v1", tags=["settings"])


class Label(BaseModel):
    singular: str = Field(min_length=1, max_length=60)
    plural: str = Field(min_length=1, max_length=60)


class Branding(BaseModel):
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    logo_url: str | None = Field(default=None, max_length=500, pattern=r"^https://\S+$")


class SettingsOut(BaseModel):
    labels: dict
    timezone: str
    locale: str
    default_country: str
    default_currency: str
    branding: dict
    follow_up_required: bool
    duplicate_policy: str
    org_grouping: str
    leakage_hours: int | None
    leakage_action: str


class SettingsPatch(BaseModel):
    """Company settings. CRM rules (follow-up, duplicates, leakage) are /crm-rules."""

    model_config = {"extra": "forbid"}

    labels: dict[str, Label] | None = None
    timezone: str | None = None
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    default_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    default_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    branding: Branding | None = None

    _tz = field_validator("timezone")(lambda v: v if v is None else valid_timezone(v))

    @field_validator("labels")
    @classmethod
    def _keys(cls, v: dict | None) -> dict | None:
        if v is not None:
            unknown = set(v) - set(LABEL_KEYS)
            if unknown:
                raise ValueError(f"Unknown label keys: {sorted(unknown)}")
        return v


class ModuleOut(BaseModel):
    key: str
    name: str
    core: bool
    enabled: bool


def _out(s: TenantSettings) -> SettingsOut:
    return SettingsOut(
        labels=s.labels,
        timezone=s.timezone,
        locale=s.locale,
        default_country=s.default_country,
        default_currency=s.default_currency,
        branding=s.branding,
        follow_up_required=s.follow_up_required,
        duplicate_policy=s.duplicate_policy,
        org_grouping=s.org_grouping,
        leakage_hours=s.leakage_hours,
        leakage_action=s.leakage_action,
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings_(current: ActiveUser, db: TenantDb) -> SettingsOut:
    return _out(await db.get(TenantSettings, current.user.tenant_id))


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsPatch,
    db: TenantDb,
    actor: Annotated[CurrentUser, require("settings.manage")],
) -> SettingsOut:
    s = await db.get(TenantSettings, actor.user.tenant_id)
    before = _out(s).model_dump()
    if body.labels:
        s.labels = s.labels | {k: v.model_dump() for k, v in body.labels.items()}
    if body.branding:
        s.branding = s.branding | body.branding.model_dump(exclude_none=True)
    if body.default_currency is not None:
        body.default_currency = money.currency(body.default_currency)
    for field in ("timezone", "locale", "default_country", "default_currency"):
        value = getattr(body, field)
        if value is not None:
            setattr(s, field, value)
    after = _out(s).model_dump()
    await record(
        db,
        tenant_id=s.tenant_id,
        actor_id=actor.user.id,
        action="settings.updated",
        entity_type="settings",
        entity_id=s.tenant_id,
        before=before,
        after=after,
    )
    return _out(s)


@router.get("/modules", response_model=list[ModuleOut])
async def list_modules(current: ActiveUser, db: TenantDb) -> list[ModuleOut]:
    states = await module_states(db, current.user.tenant_id)
    return [
        ModuleOut(key=k, name=m.name, core=m.core, enabled=states[k]) for k, m in MODULES.items()
    ]

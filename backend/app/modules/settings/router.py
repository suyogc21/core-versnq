from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.auth.deps import ActiveUser, TenantDb
from app.modules.settings.models import TenantSettings

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class SettingsOut(BaseModel):
    labels: dict
    timezone: str
    locale: str
    default_country: str
    branding: dict


@router.get("", response_model=SettingsOut)
async def get_settings_(current: ActiveUser, db: TenantDb) -> SettingsOut:
    s = await db.get(TenantSettings, current.user.tenant_id)
    return SettingsOut(
        labels=s.labels,
        timezone=s.timezone,
        locale=s.locale,
        default_country=s.default_country,
        branding=s.branding,
    )

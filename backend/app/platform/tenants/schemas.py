import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.validators import valid_timezone
from app.platform.packs import available_packs
from app.platform.tenants.slugs import validate_slug


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str
    industry_pack: str
    timezone: str
    default_country: str = Field(pattern=r"^[A-Z]{2}$")
    owner_name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return validate_slug(v)

    @field_validator("industry_pack")
    @classmethod
    def _pack(cls, v: str) -> str:
        if v not in available_packs():
            raise ValueError(
                f"Unknown industry pack. Choose one of: {', '.join(available_packs())}"
            )
        return v

    _tz = field_validator("timezone")(valid_timezone)


class TenantUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    status: str
    industry_pack: str
    created_at: datetime


class TenantCreated(TenantOut):
    invite_sent: bool


class InviteResult(BaseModel):
    invite_sent: bool


class AuditOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    staff_id: uuid.UUID | None
    action: str
    target_type: str
    target_id: uuid.UUID | None
    tenant_slug_snapshot: str | None
    before: dict | None
    after: dict | None
    created_at: datetime

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.core.auth_schemas import PASSWORD


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = PASSWORD


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = PASSWORD


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = PASSWORD


class RoleOut(BaseModel):
    key: str | None
    name: str
    scope: str


class TenantRef(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: RoleOut
    tenant: TenantRef
    restrictions: list[str]
    permissions: list[str]
    two_factor_enabled: bool
    recovery_codes_left: int = 0  # unused backup codes (go-live G-4)
    ace_console: bool = False  # C13: show Open ACE (set up, and this person has ace.use)
    brand_ids: list[uuid.UUID] | None = None  # brands this person is limited to; None = all

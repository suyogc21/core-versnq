import uuid

from pydantic import BaseModel, EmailStr, Field

from app.core.auth_schemas import PASSWORD


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class StaffOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    restrictions: list[str] = []
    recovery_codes_left: int = 0  # backup codes not yet used (go-live G-4)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = PASSWORD

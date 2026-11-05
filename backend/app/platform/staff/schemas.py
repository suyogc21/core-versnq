import uuid

from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class StaffOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
